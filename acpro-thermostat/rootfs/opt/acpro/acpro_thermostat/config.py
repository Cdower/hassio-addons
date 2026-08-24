"""Add-on options and the MQTT credentials handed out by the Supervisor."""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from .protocol import DEFAULT_PORT

_LOGGER = logging.getLogger(__name__)

OPTIONS_PATH = "/data/options.json"
STATE_PATH = "/data/device.json"

SUPERVISOR_MQTT_URL = "http://supervisor/services/mqtt"

LOG_LEVELS = {
    "trace": logging.DEBUG,
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "notice": logging.INFO,
    "warning": logging.WARNING,
    "error": logging.ERROR,
    "fatal": logging.CRITICAL,
}


class ConfigError(Exception):
    """Raised when the add-on cannot work out how it is meant to be configured."""


@dataclass(frozen=True)
class MqttSettings:
    """Where to find the broker, and how to announce ourselves on it."""

    host: str
    port: int = 1883
    username: str = ""
    password: str = ""
    ssl: bool = False
    discovery_prefix: str = "homeassistant"
    topic_prefix: str = "acpro"


@dataclass(frozen=True)
class Options:
    """The add-on's user-facing configuration."""

    device_host: str = ""
    device_port: int = DEFAULT_PORT
    device_name: str = ""
    broadcast_address: str = "255.255.255.255"
    scan_interval: int = 30
    request_timeout: float = 2.0
    encryption_version: int = 0
    extra_properties: list[str] = field(default_factory=list)
    ignored_properties: list[str] = field(default_factory=list)
    mqtt_host: str = ""
    mqtt_port: int = 0
    mqtt_username: str = ""
    mqtt_password: str = ""
    mqtt_ssl: bool = False
    mqtt_discovery_prefix: str = "homeassistant"
    mqtt_topic_prefix: str = "acpro"
    log_level: str = "info"

    @property
    def discovery_targets(self) -> list[str]:
        """Addresses the discovery probe is sent to.

        A configured host is probed directly, which also works across subnets
        where a broadcast would not be forwarded.
        """
        return [self.device_host] if self.device_host else [self.broadcast_address]


def _coerce(value: Any, default: Any) -> Any:
    """Convert an option to the type of its default, leaving blanks alone."""
    if value is None:
        return default
    if isinstance(default, bool):
        return bool(value)
    if isinstance(default, int):
        try:
            return int(value)
        except (TypeError, ValueError):
            return default
    if isinstance(default, float):
        try:
            return float(value)
        except (TypeError, ValueError):
            return default
    if isinstance(default, list):
        return list(value) if isinstance(value, list) else default
    return str(value)


def load_options(path: str = OPTIONS_PATH) -> Options:
    """Read ``options.json``, falling back to defaults for anything absent."""
    try:
        with open(path, encoding="utf-8") as handle:
            raw = json.load(handle)
    except FileNotFoundError:
        _LOGGER.warning("No options file at %s; using defaults", path)
        raw = {}
    except (OSError, json.JSONDecodeError) as err:
        raise ConfigError(f"Could not read {path}: {err}") from err

    if not isinstance(raw, dict):
        raise ConfigError(f"{path} does not contain a JSON object")

    defaults = Options()
    values = {
        name: _coerce(raw.get(name), getattr(defaults, name))
        for name in Options.__dataclass_fields__
    }
    options = Options(**values)

    if options.encryption_version not in (0, 1, 2):
        raise ConfigError(
            f"encryption_version must be 0 (auto), 1 or 2, got {options.encryption_version}"
        )
    if options.scan_interval < 5:
        raise ConfigError("scan_interval must be at least 5 seconds")

    return options


def _supervisor_mqtt() -> dict[str, Any] | None:
    """Ask the Supervisor for the broker details of the MQTT service."""
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        return None

    request = urllib.request.Request(
        SUPERVISOR_MQTT_URL,
        headers={"Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as err:
        _LOGGER.warning("Could not read MQTT service details from the Supervisor: %s", err)
        return None

    data = payload.get("data")
    return data if isinstance(data, dict) else None


def resolve_mqtt(options: Options, service: dict[str, Any] | None = None) -> MqttSettings:
    """Combine the Supervisor's MQTT service with any manual overrides.

    Anything set in the add-on options wins, so a broker outside Home Assistant
    can be used without disabling the Mosquitto add-on.
    """
    if service is None and not options.mqtt_host:
        service = _supervisor_mqtt()
    service = service or {}

    host = options.mqtt_host or str(service.get("host") or "")
    if not host:
        raise ConfigError(
            "No MQTT broker configured. Install the Mosquitto broker add-on, or set "
            "mqtt_host in this add-on's configuration."
        )

    port = options.mqtt_port or int(service.get("port") or 1883)
    username = options.mqtt_username or str(service.get("username") or "")
    password = options.mqtt_password or str(service.get("password") or "")
    ssl = options.mqtt_ssl or bool(service.get("ssl"))

    return MqttSettings(
        host=host,
        port=port,
        username=username,
        password=password,
        ssl=ssl,
        discovery_prefix=options.mqtt_discovery_prefix,
        topic_prefix=options.mqtt_topic_prefix,
    )


def load_device_cache(path: str = STATE_PATH) -> dict[str, Any]:
    """Return what earlier runs learned about each control, keyed by MAC."""
    try:
        with open(path, encoding="utf-8") as handle:
            cached = json.load(handle)
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError) as err:
        _LOGGER.warning("Ignoring unreadable device cache at %s: %s", path, err)
        return {}
    return cached if isinstance(cached, dict) else {}


def save_device_cache(
    mac: str,
    *,
    key: str,
    encryption_version: int,
    properties: list[str],
    options: Options,
    path: str = STATE_PATH,
) -> None:
    """Remember a control's key and capabilities so a restart is quick.

    Binding is cheap but probing is not: a control that ignores requests naming
    a column it lacks costs a timeout per probe, which adds up to a slow start.
    """
    cached = load_device_cache(path)
    cached[mac] = {
        "key": key,
        "encryption_version": encryption_version,
        "properties": properties,
        "probe_signature": probe_signature(options),
    }
    try:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(cached, handle)
    except OSError as err:
        _LOGGER.warning("Could not write the device cache at %s: %s", path, err)


def probe_signature(options: Options) -> list[list[str]]:
    """Identify the options that decide which columns get probed.

    Cached capabilities are only reused while this matches, so editing
    ``extra_properties`` or ``ignored_properties`` re-probes rather than
    silently keeping the old answer.
    """
    return [sorted(options.extra_properties), sorted(options.ignored_properties)]


def cached_device(mac: str, options: Options, path: str = STATE_PATH) -> dict[str, Any] | None:
    """Return the usable cache entry for ``mac``, or ``None`` if there is none."""
    entry = load_device_cache(path).get(mac)
    if not isinstance(entry, dict) or not entry.get("key"):
        return None
    if entry.get("probe_signature") != probe_signature(options):
        _LOGGER.info("Probe options changed since %s was cached; probing again", mac)
        return {**entry, "properties": []}
    return entry


def configure_logging(level: str) -> None:
    """Set up logging at the level named in the add-on options."""
    logging.basicConfig(
        level=LOG_LEVELS.get(level.lower(), logging.INFO),
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
