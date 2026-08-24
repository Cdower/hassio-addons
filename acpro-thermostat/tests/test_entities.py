"""Tests for the mapping between control columns and Home Assistant entities."""

from __future__ import annotations

import dataclasses

import pytest

from acpro_thermostat.const import (
    PROP_CURRENT_TEMP,
    PROP_FAN_SPEED,
    PROP_MODE,
    PROP_POWER,
    PROP_TARGET_TEMP,
    PROP_TEMP_HALF,
    PROP_TEMP_UNIT,
)
from acpro_thermostat.device import DeviceInfo
from acpro_thermostat.entities import EntityMap

FULL_PROPERTIES = [
    PROP_POWER,
    PROP_MODE,
    PROP_TARGET_TEMP,
    PROP_TEMP_UNIT,
    PROP_TEMP_HALF,
    PROP_FAN_SPEED,
    PROP_CURRENT_TEMP,
    "StHt",
    "SvSt",
    "Quiet",
    "Lig",
]

MINIMAL_PROPERTIES = [PROP_POWER, PROP_MODE, PROP_TARGET_TEMP]


@pytest.fixture(name="info")
def info_fixture() -> DeviceInfo:
    return DeviceInfo(
        mac="502cc6aabbcc",
        host="192.168.1.50",
        port=7000,
        name="Hallway",
        model="WK-010WD1",
        firmware="V1.2.1",
    )


@pytest.fixture(name="entity_map")
def entity_map_fixture(info: DeviceInfo) -> EntityMap:
    return EntityMap(info, FULL_PROPERTIES)


def test_object_id_is_topic_safe(info: DeviceInfo) -> None:
    entity_map = EntityMap(dataclasses.replace(info, mac="50:2C:C6:AA:BB:CC"), [])

    assert entity_map.object_id == "acpro_502cc6aabbcc"
    assert "/" not in entity_map.object_id
    assert ":" not in entity_map.object_id


def test_device_block_reports_the_thermostat(entity_map: EntityMap) -> None:
    device = entity_map.climate_config()["device"]

    assert device["manufacturer"] == "AC Pro"
    assert "85432" in device["model"]
    assert device["connections"] == [["mac", "50:2c:c6:aa:bb:cc"]]
    assert device["sw_version"] == "V1.2.1"


def test_device_block_omits_a_malformed_mac(info: DeviceInfo) -> None:
    entity_map = EntityMap(dataclasses.replace(info, mac="not-a-mac"), FULL_PROPERTIES)

    assert "connections" not in entity_map.climate_config()["device"]


def test_climate_config_offers_every_mode(entity_map: EntityMap) -> None:
    config = entity_map.climate_config()

    assert set(config["modes"]) == {"off", "heat_cool", "cool", "dry", "fan_only", "heat"}
    assert config["mode_command_topic"].endswith("/set/mode")
    assert config["temperature_command_topic"].endswith("/set/temperature")


def test_climate_config_drops_capabilities_the_control_lacks(info: DeviceInfo) -> None:
    config = EntityMap(info, MINIMAL_PROPERTIES).climate_config()

    assert "fan_modes" not in config
    assert "preset_modes" not in config
    assert "current_temperature_topic" not in config


def test_climate_config_follows_the_panel_display_unit(entity_map: EntityMap) -> None:
    celsius = entity_map.climate_config(unit=0)
    fahrenheit = entity_map.climate_config(unit=1)

    assert celsius["temperature_unit"] == "C"
    assert (celsius["min_temp"], celsius["max_temp"]) == (16, 30)
    assert fahrenheit["temperature_unit"] == "F"
    assert fahrenheit["min_temp"] < fahrenheit["max_temp"]
    assert fahrenheit["max_temp"] >= 84


def test_presets_use_the_columns_the_control_has(entity_map: EntityMap) -> None:
    assert entity_map.presets == ["none", "eco", "comfort"]
    assert entity_map.climate_config()["preset_modes"] == ["eco", "comfort"]


def test_preset_columns_are_not_also_exposed_as_switches(entity_map: EntityMap) -> None:
    assert "SvSt" not in entity_map.switches
    assert "Quiet" not in entity_map.switches
    assert set(entity_map.switches) == {"StHt", "Lig"}


def test_discovery_topics_are_namespaced(entity_map: EntityMap) -> None:
    payloads = entity_map.discovery_payloads()

    assert set(payloads) == {
        "climate/thermostat",
        "sensor/indoor_temperature",
        "switch/stht",
        "switch/lig",
    }
    assert (
        entity_map.discovery_topic("climate/thermostat")
        == "homeassistant/climate/acpro_502cc6aabbcc/thermostat/config"
    )


def test_unique_ids_do_not_collide(entity_map: EntityMap) -> None:
    unique_ids = [payload["unique_id"] for payload in entity_map.discovery_payloads().values()]

    assert len(unique_ids) == len(set(unique_ids))


def test_state_payload_in_celsius(entity_map: EntityMap) -> None:
    state = {
        PROP_POWER: 1,
        PROP_MODE: 1,
        PROP_TARGET_TEMP: 22,
        PROP_TEMP_UNIT: 0,
        PROP_TEMP_HALF: 0,
        PROP_FAN_SPEED: 3,
        PROP_CURRENT_TEMP: 61,
        "StHt": 0,
        "Lig": 1,
        "SvSt": 1,
    }

    payload = entity_map.state_payload(state)

    assert payload["mode"] == "cool"
    assert payload["target_temperature"] == 22
    assert payload["current_temperature"] == 21
    assert payload["indoor_temperature_c"] == 21
    assert payload["fan_mode"] == "medium"
    assert payload["preset_mode"] == "eco"
    assert payload["switches"] == {"stht": "OFF", "lig": "ON"}
    assert payload["temperature_unit"] == "C"


def test_state_payload_in_fahrenheit(entity_map: EntityMap) -> None:
    """Both temperatures follow the panel, so the climate card stays consistent."""
    state = {
        PROP_POWER: 1,
        PROP_MODE: 4,
        PROP_TARGET_TEMP: 21,
        PROP_TEMP_UNIT: 1,
        PROP_TEMP_HALF: 1,
        PROP_CURRENT_TEMP: 61,
    }

    payload = entity_map.state_payload(state)

    assert payload["mode"] == "heat"
    assert payload["target_temperature"] == 70
    assert payload["current_temperature"] == 70
    assert payload["indoor_temperature_c"] == 21
    assert payload["temperature_unit"] == "F"


def test_power_off_wins_over_the_reported_mode(entity_map: EntityMap) -> None:
    assert entity_map.state_payload({PROP_POWER: 0, PROP_MODE: 1})["mode"] == "off"


def test_command_topics_cover_every_entity(entity_map: EntityMap) -> None:
    topics = entity_map.command_topics()

    assert topics == [
        "acpro/acpro_502cc6aabbcc/set/mode",
        "acpro/acpro_502cc6aabbcc/set/temperature",
        "acpro/acpro_502cc6aabbcc/set/fan_mode",
        "acpro/acpro_502cc6aabbcc/set/preset_mode",
        "acpro/acpro_502cc6aabbcc/set/switch/stht",
        "acpro/acpro_502cc6aabbcc/set/switch/lig",
    ]


def test_selecting_a_mode_also_powers_the_system_on(entity_map: EntityMap) -> None:
    columns = entity_map.columns_for("acpro/acpro_502cc6aabbcc/set/mode", "heat", {})

    assert columns == {PROP_POWER: 1, PROP_MODE: 4}


def test_mode_off_only_cuts_power(entity_map: EntityMap) -> None:
    columns = entity_map.columns_for("acpro/acpro_502cc6aabbcc/set/mode", "off", {})

    assert columns == {PROP_POWER: 0}


def test_temperature_command_in_celsius(entity_map: EntityMap) -> None:
    columns = entity_map.columns_for(
        "acpro/acpro_502cc6aabbcc/set/temperature", "21.0", {PROP_TEMP_UNIT: 0}
    )

    assert columns == {PROP_TARGET_TEMP: 21}


def test_temperature_command_in_fahrenheit_sets_both_columns(entity_map: EntityMap) -> None:
    columns = entity_map.columns_for(
        "acpro/acpro_502cc6aabbcc/set/temperature", "70", {PROP_TEMP_UNIT: 1}
    )

    assert set(columns) == {PROP_TARGET_TEMP, PROP_TEMP_HALF}
    assert entity_map.target_temperature({**columns, PROP_TEMP_UNIT: 1}) == 70


def test_fahrenheit_columns_are_not_used_when_the_control_lacks_them(info: DeviceInfo) -> None:
    """Without TemUn/TemRec the setpoint is plain Celsius whatever is asked for."""
    entity_map = EntityMap(info, MINIMAL_PROPERTIES)

    columns = entity_map.columns_for(
        "acpro/acpro_502cc6aabbcc/set/temperature", "70", {PROP_TEMP_UNIT: 1}
    )

    assert columns == {PROP_TARGET_TEMP: 30}


def test_selecting_a_preset_clears_the_others(entity_map: EntityMap) -> None:
    columns = entity_map.columns_for("acpro/acpro_502cc6aabbcc/set/preset_mode", "eco", {})

    assert columns == {"SvSt": 1, "Quiet": 0}


def test_preset_none_clears_them_all(entity_map: EntityMap) -> None:
    columns = entity_map.columns_for("acpro/acpro_502cc6aabbcc/set/preset_mode", "none", {})

    assert columns == {"SvSt": 0, "Quiet": 0}


def test_switch_commands(entity_map: EntityMap) -> None:
    topic = "acpro/acpro_502cc6aabbcc/set/switch/stht"

    assert entity_map.columns_for(topic, "ON", {}) == {"StHt": 1}
    assert entity_map.columns_for(topic, "OFF", {}) == {"StHt": 0}
    assert entity_map.columns_for(topic, " on ", {}) == {"StHt": 1}


@pytest.mark.parametrize("payload", ["0", "1", "false", "toggle", "", "ONWARD"])
def test_a_switch_payload_that_is_not_on_or_off_writes_nothing(
    entity_map: EntityMap, payload: str
) -> None:
    """A stray retained message must not be read as "off" and written through."""
    topic = "acpro/acpro_502cc6aabbcc/set/switch/stht"

    assert entity_map.columns_for(topic, payload, {}) == {}


def test_the_climate_entity_is_deliberately_unnamed(entity_map: EntityMap) -> None:
    """A null name makes the entity adopt the device name (Home Assistant 2023.8+).

    Giving it a string instead would render as "AC Pro Thermostat Thermostat".
    """
    config = entity_map.climate_config()

    assert "name" in config
    assert config["name"] is None
    assert all(payload["name"] for key, payload in entity_map.discovery_payloads().items()
               if key != "climate/thermostat")


@pytest.mark.parametrize(
    ("topic", "payload"),
    [
        ("acpro/acpro_502cc6aabbcc/set/mode", "sauna"),
        ("acpro/acpro_502cc6aabbcc/set/fan_mode", "hurricane"),
        ("acpro/acpro_502cc6aabbcc/set/temperature", "warm"),
        ("acpro/acpro_502cc6aabbcc/set/preset_mode", "away"),
        ("acpro/acpro_502cc6aabbcc/set/switch/nope", "ON"),
        ("some/other/topic", "ON"),
    ],
)
def test_unusable_commands_write_nothing(
    entity_map: EntityMap, topic: str, payload: str
) -> None:
    assert entity_map.columns_for(topic, payload, {}) == {}


def test_topic_prefixes_are_configurable(info: DeviceInfo) -> None:
    entity_map = EntityMap(
        info,
        FULL_PROPERTIES,
        topic_prefix="hvac",
        discovery_prefix="ha",
        device_name="Upstairs",
    )

    assert entity_map.state_topic.startswith("hvac/")
    assert entity_map.discovery_topic("climate/thermostat").startswith("ha/climate/")
    assert entity_map.climate_config()["device"]["name"] == "Upstairs"
