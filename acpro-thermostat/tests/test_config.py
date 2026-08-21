"""Tests for option parsing and MQTT credential resolution."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from acpro_thermostat import config
from acpro_thermostat.config import ConfigError, Options


def _write(tmp_path: Path, options: dict) -> str:
    path = tmp_path / "options.json"
    path.write_text(json.dumps(options), encoding="utf-8")
    return str(path)


def test_missing_options_file_falls_back_to_defaults(tmp_path: Path) -> None:
    assert config.load_options(str(tmp_path / "absent.json")) == Options()


def test_options_are_coerced_to_their_declared_types(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        {
            "device_host": "192.168.1.50",
            "device_port": "7000",
            "scan_interval": "45",
            "request_timeout": "1.5",
            "mqtt_ssl": 1,
            "extra_properties": ["Health"],
        },
    )

    options = config.load_options(path)

    assert options.device_host == "192.168.1.50"
    assert options.device_port == 7000
    assert options.scan_interval == 45
    assert options.request_timeout == 1.5
    assert options.mqtt_ssl is True
    assert options.extra_properties == ["Health"]


def test_blank_and_absent_options_keep_their_defaults(tmp_path: Path) -> None:
    options = config.load_options(_write(tmp_path, {"device_host": None, "scan_interval": None}))

    assert options.device_host == ""
    assert options.scan_interval == 30


def test_nonsense_numbers_do_not_crash_the_add_on(tmp_path: Path) -> None:
    options = config.load_options(_write(tmp_path, {"device_port": "not-a-port"}))

    assert options.device_port == 7000


def test_unusable_options_file_is_reported(tmp_path: Path) -> None:
    path = tmp_path / "options.json"
    path.write_text("not json", encoding="utf-8")

    with pytest.raises(ConfigError, match="Could not read"):
        config.load_options(str(path))


def test_options_must_be_an_object(tmp_path: Path) -> None:
    path = tmp_path / "options.json"
    path.write_text("[1, 2]", encoding="utf-8")

    with pytest.raises(ConfigError, match="JSON object"):
        config.load_options(str(path))


def test_encryption_version_is_validated(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="encryption_version"):
        config.load_options(_write(tmp_path, {"encryption_version": 5}))


def test_scan_interval_has_a_floor(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="scan_interval"):
        config.load_options(_write(tmp_path, {"scan_interval": 1}))


def test_a_configured_host_is_probed_directly() -> None:
    assert Options(device_host="192.168.1.50").discovery_targets == ["192.168.1.50"]
    assert Options().discovery_targets == ["255.255.255.255"]
    assert Options(broadcast_address="192.168.1.255").discovery_targets == ["192.168.1.255"]


def test_supervisor_service_supplies_the_broker() -> None:
    settings = config.resolve_mqtt(
        Options(),
        service={
            "host": "core-mosquitto",
            "port": 1883,
            "username": "addons",
            "password": "s3cr3t",
        },
    )

    assert settings.host == "core-mosquitto"
    assert settings.port == 1883
    assert settings.username == "addons"
    assert settings.password == "s3cr3t"
    assert settings.ssl is False


def test_manual_options_override_the_supervisor() -> None:
    settings = config.resolve_mqtt(
        Options(mqtt_host="broker.lan", mqtt_port=8883, mqtt_ssl=True, mqtt_username="me"),
        service={"host": "core-mosquitto", "port": 1883, "username": "addons"},
    )

    assert (settings.host, settings.port, settings.ssl) == ("broker.lan", 8883, True)
    assert settings.username == "me"


def test_no_broker_anywhere_is_an_error() -> None:
    with pytest.raises(ConfigError, match="No MQTT broker configured"):
        config.resolve_mqtt(Options(), service={})


def test_topic_prefixes_come_from_the_options() -> None:
    settings = config.resolve_mqtt(
        Options(mqtt_host="broker.lan", mqtt_topic_prefix="hvac", mqtt_discovery_prefix="ha"),
        service={},
    )

    assert settings.topic_prefix == "hvac"
    assert settings.discovery_prefix == "ha"


def test_device_cache_round_trip(tmp_path: Path) -> None:
    path = str(tmp_path / "device.json")
    options = Options()

    config.save_device_cache(
        "502cc6aabbcc",
        key="St8Vw1Yz4Bc7Ted6",
        encryption_version=2,
        properties=["Pow", "Mod", "SetTem"],
        options=options,
        path=path,
    )

    entry = config.cached_device("502cc6aabbcc", options, path)

    assert entry["key"] == "St8Vw1Yz4Bc7Ted6"
    assert entry["encryption_version"] == 2
    assert entry["properties"] == ["Pow", "Mod", "SetTem"]


def test_device_cache_keeps_other_controls(tmp_path: Path) -> None:
    path = str(tmp_path / "device.json")
    options = Options()
    config.save_device_cache(
        "aaaaaaaaaaaa", key="key-one-aaaaaaaa", encryption_version=1,
        properties=["Pow"], options=options, path=path,
    )

    config.save_device_cache(
        "bbbbbbbbbbbb", key="key-two-bbbbbbbb", encryption_version=1,
        properties=["Pow"], options=options, path=path,
    )

    assert set(config.load_device_cache(path)) == {"aaaaaaaaaaaa", "bbbbbbbbbbbb"}


def test_changing_the_probe_options_discards_cached_capabilities(tmp_path: Path) -> None:
    """Otherwise an edited ignore list would keep publishing the old entities."""
    path = str(tmp_path / "device.json")
    config.save_device_cache(
        "502cc6aabbcc", key="St8Vw1Yz4Bc7Ted6", encryption_version=1,
        properties=["Pow", "Mod", "SetTem", "Lig"], options=Options(), path=path,
    )

    entry = config.cached_device("502cc6aabbcc", Options(ignored_properties=["Lig"]), path)

    assert entry["key"] == "St8Vw1Yz4Bc7Ted6"
    assert entry["properties"] == []


def test_reordering_the_probe_options_keeps_the_cache(tmp_path: Path) -> None:
    path = str(tmp_path / "device.json")
    config.save_device_cache(
        "502cc6aabbcc", key="St8Vw1Yz4Bc7Ted6", encryption_version=1,
        properties=["Pow"], options=Options(extra_properties=["A", "B"]), path=path,
    )

    entry = config.cached_device("502cc6aabbcc", Options(extra_properties=["B", "A"]), path)

    assert entry["properties"] == ["Pow"]


def test_an_entry_without_a_key_is_not_usable(tmp_path: Path) -> None:
    path = tmp_path / "device.json"
    path.write_text(json.dumps({"502cc6aabbcc": {"properties": ["Pow"]}}), encoding="utf-8")

    assert config.cached_device("502cc6aabbcc", Options(), str(path)) is None


def test_unreadable_device_cache_is_ignored(tmp_path: Path) -> None:
    path = tmp_path / "device.json"
    path.write_text("{ broken", encoding="utf-8")

    assert config.load_device_cache(str(path)) == {}
    assert config.cached_device("502cc6aabbcc", Options(), str(path)) is None


def test_absent_device_cache_is_empty(tmp_path: Path) -> None:
    assert config.load_device_cache(str(tmp_path / "absent.json")) == {}
