"""Ties the control, the entity map and the MQTT broker together."""

from __future__ import annotations

import json
import logging
import queue
import ssl
import threading
from typing import Any

import paho.mqtt.client as mqtt

from .config import MqttSettings
from .const import PROP_TEMP_UNIT
from .device import AcProDevice, DeviceError
from .entities import EntityMap

_LOGGER = logging.getLogger(__name__)

PAYLOAD_ONLINE = "online"
PAYLOAD_OFFLINE = "offline"


class Bridge:
    """Publishes one control to Home Assistant and applies commands back to it."""

    def __init__(
        self,
        device: AcProDevice,
        entity_map: EntityMap,
        settings: MqttSettings,
    ) -> None:
        self.device = device
        self.map = entity_map
        self.settings = settings

        self._commands: queue.Queue[tuple[str, str]] = queue.Queue()
        self._stop = threading.Event()
        self._published_unit: int | None = None
        self._last_payload: str | None = None

        self.client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"{self.map.object_id}_bridge",
        )
        if settings.username:
            self.client.username_pw_set(settings.username, settings.password)
        if settings.ssl:
            self.client.tls_set_context(ssl.create_default_context())
        self.client.will_set(self.map.availability_topic, PAYLOAD_OFFLINE, qos=1, retain=True)
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message

    # --- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        _LOGGER.info(
            "Connecting to MQTT broker at %s:%s", self.settings.host, self.settings.port
        )
        self.client.connect(self.settings.host, self.settings.port, keepalive=60)
        self.client.loop_start()

    def stop(self) -> None:
        self._stop.set()
        try:
            self.client.publish(
                self.map.availability_topic, PAYLOAD_OFFLINE, qos=1, retain=True
            ).wait_for_publish(timeout=5)
        except (RuntimeError, ValueError) as err:
            _LOGGER.debug("Could not publish the offline notice: %s", err)
        self.client.loop_stop()
        self.client.disconnect()

    # --- MQTT callbacks ----------------------------------------------------

    def _on_connect(
        self,
        client: mqtt.Client,
        _userdata: Any,
        _flags: Any,
        reason: Any,
        *_: Any,
    ) -> None:
        if reason != 0:
            _LOGGER.error("MQTT connection refused: %s", reason)
            return

        _LOGGER.info("Connected to MQTT broker")
        # Discovery and subscriptions are re-established on every connect so a
        # broker restart -- which drops retained state on some setups -- heals
        # itself without restarting the add-on.
        self.publish_discovery(force=True)
        for topic in self.map.command_topics():
            client.subscribe(topic, qos=1)
        client.publish(self.map.availability_topic, PAYLOAD_ONLINE, qos=1, retain=True)
        self.publish_state(force=True)

    def _on_message(self, _client: mqtt.Client, _userdata: Any, message: mqtt.MQTTMessage) -> None:
        try:
            payload = message.payload.decode("utf-8")
        except UnicodeDecodeError:
            _LOGGER.warning("Ignoring non-text payload on %s", message.topic)
            return
        self._commands.put((message.topic, payload))

    # --- publishing --------------------------------------------------------

    def publish_discovery(self, *, force: bool = False) -> None:
        """(Re)publish the retained discovery configs.

        The panel's display unit is baked into the climate config, so flipping
        the panel between Celsius and Fahrenheit republishes rather than
        leaving Home Assistant showing the wrong scale.
        """
        unit = int(self.device.state.get(PROP_TEMP_UNIT, 0))
        if not force and unit == self._published_unit:
            return

        for key, payload in self.map.discovery_payloads(unit).items():
            self.client.publish(
                self.map.discovery_topic(key),
                json.dumps(payload, separators=(",", ":")),
                qos=1,
                retain=True,
            )
        self._published_unit = unit
        _LOGGER.debug("Published discovery for %s (unit %s)", self.map.object_id, unit)

    def publish_state(self, *, force: bool = False) -> None:
        """Publish the current state, skipping unchanged documents."""
        payload = json.dumps(
            self.map.state_payload(self.device.state), separators=(",", ":"), sort_keys=True
        )
        if not force and payload == self._last_payload:
            return
        self.client.publish(self.map.state_topic, payload, qos=1, retain=True)
        self._last_payload = payload

    def publish_availability(self, available: bool) -> None:
        self.client.publish(
            self.map.availability_topic,
            PAYLOAD_ONLINE if available else PAYLOAD_OFFLINE,
            qos=1,
            retain=True,
        )

    # --- the work ----------------------------------------------------------

    def drain_commands(self, timeout: float) -> bool:
        """Apply queued commands, waiting up to ``timeout`` for the first.

        Returns whether anything was written, so the caller can poll the
        control immediately instead of waiting out the rest of its interval.
        """
        applied = False
        try:
            topic, payload = self._commands.get(timeout=timeout)
        except queue.Empty:
            return applied

        pending: list[tuple[str, str]] = [(topic, payload)]
        while True:
            try:
                pending.append(self._commands.get_nowait())
            except queue.Empty:
                break

        for topic, payload in pending:
            columns = self.map.columns_for(topic, payload, self.device.state)
            if not columns:
                _LOGGER.warning("Ignoring unusable command %r on %s", payload, topic)
                continue
            _LOGGER.info("Applying %s from %s", columns, topic)
            try:
                self.device.apply(columns)
                applied = True
            except DeviceError as err:
                _LOGGER.error("Could not apply %s: %s", columns, err)
        return applied

    def poll(self) -> bool:
        """Read the control and publish what came back.  Returns success."""
        try:
            self.device.refresh()
        except DeviceError as err:
            _LOGGER.warning("Could not read the control: %s", err)
            return False
        self.publish_discovery()
        self.publish_state()
        return True
