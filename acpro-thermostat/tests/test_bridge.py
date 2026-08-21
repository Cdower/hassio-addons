"""Tests for the MQTT side of the bridge, against a stub broker client."""

from __future__ import annotations

import json
from typing import Any

import pytest

from acpro_thermostat.bridge import PAYLOAD_OFFLINE, PAYLOAD_ONLINE, Bridge
from acpro_thermostat.config import MqttSettings
from acpro_thermostat.device import DeviceError, DeviceInfo
from acpro_thermostat.entities import EntityMap

PROPERTIES = ["Pow", "Mod", "SetTem", "TemUn", "TemRec", "WdSpd", "TemSen", "Lig"]


class FakeClient:
    """Records what the bridge publishes instead of talking to a broker."""

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        self.published: list[tuple[str, str, bool]] = []
        self.subscriptions: list[str] = []
        self.will: tuple[str, str] | None = None
        self.credentials: tuple[str, str] | None = None
        self.tls = False
        self.on_connect = None
        self.on_message = None

    def username_pw_set(self, username: str, password: str) -> None:
        self.credentials = (username, password)

    def tls_set_context(self, _context: Any) -> None:
        self.tls = True

    def will_set(self, topic: str, payload: str, **_kwargs: Any) -> None:
        self.will = (topic, payload)

    def subscribe(self, topic: str, **_kwargs: Any) -> None:
        self.subscriptions.append(topic)

    def publish(self, topic: str, payload: str, **kwargs: Any) -> FakeClient:
        self.published.append((topic, payload, bool(kwargs.get("retain"))))
        return self

    def wait_for_publish(self, timeout: float | None = None) -> None:
        pass

    def connect(self, *_args: Any, **_kwargs: Any) -> None:
        pass

    def loop_start(self) -> None:
        pass

    def loop_stop(self) -> None:
        pass

    def disconnect(self) -> None:
        pass

    # Test helpers ---------------------------------------------------------

    def topics(self) -> list[str]:
        return [topic for topic, _payload, _retain in self.published]

    def last(self, topic: str) -> str:
        for published_topic, payload, _retain in reversed(self.published):
            if published_topic == topic:
                return payload
        raise AssertionError(f"nothing was published to {topic}")


class FakeDevice:
    """A device whose reads and writes are recorded rather than sent."""

    def __init__(self, state: dict[str, int] | None = None) -> None:
        self.info = DeviceInfo(mac="502cc6aabbcc", host="192.168.1.50", port=7000, name="Hallway")
        self.properties = list(PROPERTIES)
        self.state = state or {
            "Pow": 1,
            "Mod": 1,
            "SetTem": 22,
            "TemUn": 0,
            "TemRec": 0,
            "WdSpd": 0,
            "TemSen": 61,
            "Lig": 1,
        }
        self.applied: list[dict[str, int]] = []
        self.refreshes = 0
        self.fail_refresh = False

    def refresh(self, _properties: Any = None) -> dict[str, int]:
        self.refreshes += 1
        if self.fail_refresh:
            raise DeviceError("unreachable")
        return dict(self.state)

    def apply(self, values: dict[str, int]) -> dict[str, int]:
        self.applied.append(dict(values))
        self.state.update(values)
        return dict(self.state)


@pytest.fixture(name="bridge")
def bridge_fixture(monkeypatch: pytest.MonkeyPatch) -> Bridge:
    monkeypatch.setattr("acpro_thermostat.bridge.mqtt.Client", FakeClient)
    device = FakeDevice()
    entity_map = EntityMap(device.info, device.properties)
    return Bridge(
        device,
        entity_map,
        MqttSettings(host="core-mosquitto", username="addons", password="s3cr3t"),
    )


def test_credentials_and_will_are_set_up(bridge: Bridge) -> None:
    assert bridge.client.credentials == ("addons", "s3cr3t")
    assert bridge.client.will == ("acpro/status", PAYLOAD_OFFLINE)
    assert bridge.client.tls is False


def test_tls_is_enabled_when_asked(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("acpro_thermostat.bridge.mqtt.Client", FakeClient)
    device = FakeDevice()

    bridge = Bridge(
        device,
        EntityMap(device.info, device.properties),
        MqttSettings(host="broker.lan", ssl=True),
    )

    assert bridge.client.tls is True


def test_connecting_publishes_discovery_and_subscribes(bridge: Bridge) -> None:
    bridge._on_connect(bridge.client, None, None, 0)

    assert bridge.client.subscriptions == bridge.map.command_topics()
    assert (
        "homeassistant/climate/acpro_502cc6aabbcc/thermostat/config" in bridge.client.topics()
    )
    assert bridge.client.last("acpro/status") == PAYLOAD_ONLINE
    assert json.loads(bridge.client.last("acpro/acpro_502cc6aabbcc/state"))["mode"] == "cool"


def test_a_refused_connection_publishes_nothing(bridge: Bridge) -> None:
    bridge._on_connect(bridge.client, None, None, 5)

    assert bridge.client.published == []
    assert bridge.client.subscriptions == []


def test_discovery_is_retained_so_entities_survive_a_restart(bridge: Bridge) -> None:
    bridge.publish_discovery(force=True)

    retained = {
        topic for topic, _payload, retain in bridge.client.published if retain
    }
    assert "homeassistant/switch/acpro_502cc6aabbcc/lig/config" in retained
    assert "homeassistant/sensor/acpro_502cc6aabbcc/indoor_temperature/config" in retained


def test_discovery_is_republished_when_the_panel_changes_unit(bridge: Bridge) -> None:
    bridge.publish_discovery()
    published = len(bridge.client.published)

    bridge.publish_discovery()
    assert len(bridge.client.published) == published

    bridge.device.state["TemUn"] = 1
    bridge.publish_discovery()

    assert len(bridge.client.published) > published
    config = json.loads(
        bridge.client.last("homeassistant/climate/acpro_502cc6aabbcc/thermostat/config")
    )
    assert config["temperature_unit"] == "F"


def test_unchanged_state_is_not_republished(bridge: Bridge) -> None:
    bridge.publish_state()
    published = len(bridge.client.published)

    bridge.publish_state()

    assert len(bridge.client.published) == published


def test_changed_state_is_republished(bridge: Bridge) -> None:
    bridge.publish_state()
    published = len(bridge.client.published)

    bridge.device.state["SetTem"] = 24
    bridge.publish_state()

    assert len(bridge.client.published) == published + 1


def test_a_command_is_applied_to_the_control(bridge: Bridge) -> None:
    bridge._on_message(bridge.client, None, _message("acpro/acpro_502cc6aabbcc/set/mode", "heat"))

    assert bridge.drain_commands(timeout=0.01) is True
    assert bridge.device.applied == [{"Pow": 1, "Mod": 4}]


def test_queued_commands_are_applied_together(bridge: Bridge) -> None:
    bridge._on_message(bridge.client, None, _message("acpro/acpro_502cc6aabbcc/set/mode", "cool"))
    bridge._on_message(
        bridge.client, None, _message("acpro/acpro_502cc6aabbcc/set/temperature", "24")
    )

    bridge.drain_commands(timeout=0.01)

    assert bridge.device.applied == [{"Pow": 1, "Mod": 1}, {"SetTem": 24}]


def test_an_unusable_command_is_dropped_rather_than_applied(bridge: Bridge) -> None:
    bridge._on_message(bridge.client, None, _message("acpro/acpro_502cc6aabbcc/set/mode", "sauna"))

    assert bridge.drain_commands(timeout=0.01) is False
    assert bridge.device.applied == []


def test_a_failing_write_does_not_take_the_bridge_down(bridge: Bridge) -> None:
    def explode(_values: dict[str, int]) -> dict[str, int]:
        raise DeviceError("no reply")

    bridge.device.apply = explode
    bridge._on_message(bridge.client, None, _message("acpro/acpro_502cc6aabbcc/set/mode", "heat"))

    assert bridge.drain_commands(timeout=0.01) is False


def test_binary_payloads_are_ignored(bridge: Bridge) -> None:
    message = _message("acpro/acpro_502cc6aabbcc/set/mode", "heat")
    message.payload = b"\xff\xfe"

    bridge._on_message(bridge.client, None, message)

    assert bridge.drain_commands(timeout=0.01) is False


def test_no_commands_means_no_work(bridge: Bridge) -> None:
    assert bridge.drain_commands(timeout=0.01) is False


def test_a_poll_that_fails_reports_it(bridge: Bridge) -> None:
    bridge.device.fail_refresh = True

    assert bridge.poll() is False


def test_a_poll_that_works_publishes_state(bridge: Bridge) -> None:
    assert bridge.poll() is True
    state = json.loads(bridge.client.last("acpro/acpro_502cc6aabbcc/state"))
    assert state["target_temperature"] == 22


def test_availability_is_published_retained(bridge: Bridge) -> None:
    bridge.publish_availability(False)

    assert bridge.client.published[-1] == ("acpro/status", PAYLOAD_OFFLINE, True)


def test_stopping_announces_the_bridge_is_gone(bridge: Bridge) -> None:
    bridge.stop()

    assert bridge.client.last("acpro/status") == PAYLOAD_OFFLINE


def _message(topic: str, payload: str):
    class Message:
        pass

    message = Message()
    message.topic = topic
    message.payload = payload.encode()
    return message


def test_connect_result_is_read_from_a_real_reason_code(bridge: Bridge) -> None:
    """paho hands the callback a ReasonCode, not the plain int the other tests use."""
    from paho.mqtt.reasoncodes import ReasonCode

    bridge._on_connect(bridge.client, None, None, ReasonCode(2, aName="Not authorized"))
    assert bridge.client.published == []

    bridge._on_connect(bridge.client, None, None, ReasonCode(2, aName="Success"))
    assert bridge.client.last("acpro/status") == PAYLOAD_ONLINE
