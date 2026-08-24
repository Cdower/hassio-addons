"""Add-on entry point: find the control, bind to it, and keep MQTT in step."""

from __future__ import annotations

import dataclasses
import logging
import signal
import sys
import threading
import time
from types import FrameType

from . import device as device_module
from .bridge import Bridge
from .config import (
    ConfigError,
    Options,
    cached_device,
    configure_logging,
    load_options,
    resolve_mqtt,
    save_device_cache,
)
from .const import CANDIDATE_PROPERTIES
from .device import AcProDevice, DeviceError, DeviceInfo, Transport
from .entities import EntityMap
from .protocol import ProtocolError

_LOGGER = logging.getLogger("acpro_thermostat")

#: How long to wait before retrying after the control could not be found.
RETRY_SECONDS = 30

#: Consecutive failed polls before the entities are marked unavailable.  One
#: dropped datagram is normal on Wi-Fi and should not flap the dashboard.
FAILURES_BEFORE_UNAVAILABLE = 3


def _find_device(options: Options, transport: Transport) -> DeviceInfo:
    """Locate the control, honouring a configured host and encryption version."""
    targets = options.discovery_targets
    _LOGGER.info("Looking for the control via %s", ", ".join(targets))

    found = device_module.discover(
        transport,
        targets=targets,
        port=options.device_port,
        duration=max(options.request_timeout * 2, 3.0),
    )
    if not found:
        raise DeviceError(
            "No AC Pro control answered. Check that the panel is on the same network "
            "segment as Home Assistant, or set device_host in the add-on options."
        )
    if len(found) > 1 and not options.device_host:
        _LOGGER.warning(
            "Found %s controls (%s); using the first. Set device_host to pick one.",
            len(found),
            ", ".join(info.mac for info in found),
        )

    info = found[0]
    if options.encryption_version:
        # A manual override wins: some panels answer discovery under one scheme
        # and then expect the other for the session that follows.
        info = dataclasses.replace(info, encryption_version=options.encryption_version)
    _LOGGER.info(
        "Using control %s at %s (model %r, firmware %r, encryption v%s)",
        info.mac,
        info.host,
        info.model,
        info.firmware,
        info.encryption_version,
    )
    return info


def _connect_device(options: Options, transport: Transport) -> AcProDevice:
    """Attach with what an earlier run learned when possible, otherwise bind afresh."""
    info = _find_device(options, transport)
    candidates = (*CANDIDATE_PROPERTIES, *options.extra_properties)

    cached = cached_device(info.mac, options)
    if cached and cached.get("encryption_version") == info.encryption_version:
        device = device_module.attach(transport, info, str(cached["key"]))
        properties = [str(name) for name in cached.get("properties") or []]
        try:
            if properties:
                # Reuse the probed capabilities: a read that comes back proves
                # both the stored key and the stored column list.
                device.properties = properties
                device.refresh()
            else:
                device.probe(candidates, ignore=options.ignored_properties)
                save_device_cache(
                    info.mac,
                    key=device.key,
                    encryption_version=info.encryption_version,
                    properties=device.properties,
                    options=options,
                )
        except DeviceError as err:
            _LOGGER.info("Stored details for %s no longer work (%s); binding again", info.mac, err)
        else:
            _LOGGER.info(
                "Reused the stored key for %s (%s properties)", info.mac, len(device.properties)
            )
            return device

    device = device_module.bind(transport, info)
    device.probe(candidates, ignore=options.ignored_properties)
    save_device_cache(
        info.mac,
        key=device.key,
        encryption_version=info.encryption_version,
        properties=device.properties,
        options=options,
    )
    return device


def _run(options: Options, stop: threading.Event) -> None:
    while not stop.is_set():
        try:
            # Resolved inside the loop so a broker that starts after this
            # add-on -- Mosquitto on a cold boot, say -- is picked up on a
            # later attempt instead of taking the add-on down for good.
            settings = resolve_mqtt(options)
        except ConfigError as err:
            _LOGGER.error("%s", err)
            _wait_before_retry(stop)
            continue

        transport = Transport(timeout=options.request_timeout)
        bridge: Bridge | None = None
        try:
            device = _connect_device(options, transport)
            entity_map = EntityMap(
                device.info,
                device.properties,
                topic_prefix=settings.topic_prefix,
                discovery_prefix=settings.discovery_prefix,
                device_name=options.device_name,
            )
            bridge = Bridge(device, entity_map, settings)
            bridge.start()
            _serve(bridge, options, stop)
        except (DeviceError, ProtocolError) as err:
            _LOGGER.error("%s", err)
        except OSError as err:
            _LOGGER.error("Network error talking to the control or broker: %s", err)
        finally:
            if bridge is not None:
                bridge.stop()
            transport.close()

        _wait_before_retry(stop)


def _wait_before_retry(stop: threading.Event) -> None:
    if stop.is_set():
        return
    _LOGGER.info("Retrying in %s seconds", RETRY_SECONDS)
    stop.wait(RETRY_SECONDS)


def _serve(bridge: Bridge, options: Options, stop: threading.Event) -> None:
    """Poll the control and service commands until asked to stop."""
    failures = 0
    available = True

    while not stop.is_set():
        if bridge.poll():
            failures = 0
            if not available:
                bridge.publish_availability(True)
                available = True
        else:
            failures += 1
            if failures >= FAILURES_BEFORE_UNAVAILABLE and available:
                _LOGGER.error("Control unreachable after %s attempts", failures)
                bridge.publish_availability(False)
                available = False
            if failures >= FAILURES_BEFORE_UNAVAILABLE * 2:
                # The panel may have changed address; start over from discovery.
                raise DeviceError("Giving up on the current session; rediscovering")

        _wait_for_next_poll(bridge, options.scan_interval, stop)


def _wait_for_next_poll(bridge: Bridge, interval: float, stop: threading.Event) -> None:
    """Sleep out the polling interval, cutting it short when a command arrives.

    ``drain_commands`` blocks on its queue, so this is a sleep a command can
    interrupt: a write is answered by an immediate read rather than leaving the
    dashboard on a stale value for the rest of the interval.
    """
    deadline = time.monotonic() + interval
    while not stop.is_set():
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        if bridge.drain_commands(timeout=min(remaining, 1.0)):
            return


def main() -> int:
    stop = threading.Event()

    def _handle_signal(signum: int, _frame: FrameType | None) -> None:
        _LOGGER.info("Received signal %s; shutting down", signum)
        stop.set()

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    try:
        options = load_options()
    except ConfigError as err:
        logging.basicConfig(level=logging.INFO)
        _LOGGER.error("%s", err)
        return 1

    configure_logging(options.log_level)
    _LOGGER.info("Starting the AC Pro thermostat bridge")

    try:
        _run(options, stop)
    except ConfigError as err:
        _LOGGER.error("%s", err)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
