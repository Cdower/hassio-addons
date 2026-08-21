"""Translation between the control's columns and Home Assistant entities.

Everything in here is pure: it turns a device's supported columns into MQTT
discovery payloads, turns raw column values into a state document, and turns
Home Assistant commands back into column writes.  Keeping the translation free
of sockets is what makes it straightforward to test.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from . import temperature
from .const import (
    FAN_MODES,
    FAN_MODES_REVERSE,
    HVAC_MODES,
    HVAC_MODES_REVERSE,
    PRESET_NONE,
    PRESET_PROPERTIES,
    PROP_CURRENT_TEMP,
    PROP_FAN_SPEED,
    PROP_MODE,
    PROP_POWER,
    PROP_TARGET_TEMP,
    PROP_TEMP_HALF,
    PROP_TEMP_UNIT,
    SWITCH_PROPERTIES,
    TEMP_MAX_C,
    TEMP_MIN_C,
    TEMP_SENSOR_OFFSET,
)
from .device import DeviceInfo

#: Value of ``TemUn`` that means the panel is displaying Fahrenheit.
UNIT_FAHRENHEIT = 1


def _normalise_mac(mac: str) -> str:
    """Strip the separators the control may or may not include in its MAC."""
    return mac.lower().replace(":", "").replace("-", "")


def _object_id(mac: str) -> str:
    """A stable, topic-safe identifier for one control."""
    return f"acpro_{_normalise_mac(mac)}"


def _formatted_mac(mac: str) -> str | None:
    """Return the colon-separated MAC Home Assistant expects, if it looks like one."""
    plain = _normalise_mac(mac)
    if len(plain) != 12 or any(character not in "0123456789abcdef" for character in plain):
        return None
    return ":".join(plain[index : index + 2] for index in range(0, 12, 2))


class EntityMap:
    """Describes the Home Assistant entities one control should present."""

    def __init__(
        self,
        info: DeviceInfo,
        properties: Sequence[str],
        *,
        topic_prefix: str = "acpro",
        discovery_prefix: str = "homeassistant",
        device_name: str = "",
    ) -> None:
        self.info = info
        self.properties = list(properties)
        self.discovery_prefix = discovery_prefix
        self.object_id = _object_id(info.mac)
        self.name = device_name or info.display_name

        base = f"{topic_prefix}/{self.object_id}"
        self.state_topic = f"{base}/state"
        self.command_topic = f"{base}/set"
        self.availability_topic = f"{topic_prefix}/status"

    # --- capabilities ------------------------------------------------------

    @property
    def switches(self) -> list[str]:
        """Columns that become standalone switches, minus any used as presets."""
        preset_columns = set(PRESET_PROPERTIES.values())
        return [
            name
            for name in self.properties
            if name in SWITCH_PROPERTIES and name not in preset_columns
        ]

    @property
    def presets(self) -> list[str]:
        """Preset names the control can actually offer."""
        available = [
            preset for preset, column in PRESET_PROPERTIES.items() if column in self.properties
        ]
        return [PRESET_NONE, *available] if available else []

    @property
    def fahrenheit(self) -> bool:
        """Whether the panel is set to Fahrenheit, which changes the setpoint columns."""
        return PROP_TEMP_UNIT in self.properties and PROP_TEMP_HALF in self.properties

    def temperature_bounds(self, unit: int) -> tuple[int, int, str]:
        """Return ``(min, max, unit)`` for the setpoint in the panel's own scale."""
        if self.fahrenheit and unit == UNIT_FAHRENHEIT:
            low, high = temperature.fahrenheit_range()
            return low, high, "F"
        return TEMP_MIN_C, TEMP_MAX_C, "C"

    # --- discovery ---------------------------------------------------------

    def _device_block(self) -> dict[str, Any]:
        block: dict[str, Any] = {
            "identifiers": [self.object_id],
            "name": self.name,
            "manufacturer": "AC Pro",
            "model": "X/XB-Series Smart Communicating Control (SKU 85432)",
        }
        formatted_mac = _formatted_mac(self.info.mac)
        if formatted_mac:
            block["connections"] = [["mac", formatted_mac]]
        if self.info.firmware:
            block["sw_version"] = self.info.firmware
        if self.info.model:
            block["model_id"] = self.info.model
        return block

    def _common(self, suffix: str, name: str | None) -> dict[str, Any]:
        """Fields every entity shares.  A ``name`` of ``None`` makes the entity
        adopt the device name, which reads better than "Thermostat Thermostat"."""
        return {
            "name": name,
            "unique_id": f"{self.object_id}_{suffix}",
            "object_id": f"{self.object_id}_{suffix}",
            "state_topic": self.state_topic,
            "availability_topic": self.availability_topic,
            "payload_available": "online",
            "payload_not_available": "offline",
            "device": self._device_block(),
        }

    def climate_config(self, unit: int = 0) -> dict[str, Any]:
        """Discovery payload for the thermostat itself."""
        low, high, scale = self.temperature_bounds(unit)
        config = self._common("climate", None)
        # A climate entity has per-attribute state topics rather than one shared
        # topic, so the inherited default would be ignored anyway.
        config.pop("state_topic")
        config.update(
            {
                "modes": ["off", *[HVAC_MODES[m] for m in sorted(HVAC_MODES)]],
                "mode_state_topic": self.state_topic,
                "mode_state_template": "{{ value_json.mode }}",
                "mode_command_topic": f"{self.command_topic}/mode",
                "temperature_state_topic": self.state_topic,
                "temperature_state_template": "{{ value_json.target_temperature }}",
                "temperature_command_topic": f"{self.command_topic}/temperature",
                "temperature_unit": scale,
                "min_temp": low,
                "max_temp": high,
                "temp_step": 1,
                "qos": 1,
            }
        )

        if PROP_CURRENT_TEMP in self.properties:
            config["current_temperature_topic"] = self.state_topic
            config["current_temperature_template"] = "{{ value_json.current_temperature }}"

        if PROP_FAN_SPEED in self.properties:
            config.update(
                {
                    "fan_modes": [FAN_MODES[s] for s in sorted(FAN_MODES)],
                    "fan_mode_state_topic": self.state_topic,
                    "fan_mode_state_template": "{{ value_json.fan_mode }}",
                    "fan_mode_command_topic": f"{self.command_topic}/fan_mode",
                }
            )

        if self.presets:
            config.update(
                {
                    "preset_modes": self.presets[1:],
                    "preset_mode_state_topic": self.state_topic,
                    "preset_mode_value_template": "{{ value_json.preset_mode }}",
                    "preset_mode_command_topic": f"{self.command_topic}/preset_mode",
                }
            )

        return config

    def sensor_configs(self) -> dict[str, dict[str, Any]]:
        """Discovery payloads for read-only sensors, keyed by discovery component."""
        configs: dict[str, dict[str, Any]] = {}
        if PROP_CURRENT_TEMP in self.properties:
            config = self._common("indoor_temperature", "Indoor temperature")
            config.update(
                {
                    "value_template": "{{ value_json.indoor_temperature_c }}",
                    "device_class": "temperature",
                    "state_class": "measurement",
                    "unit_of_measurement": "°C",
                }
            )
            configs["sensor/indoor_temperature"] = config
        return configs

    def switch_configs(self) -> dict[str, dict[str, Any]]:
        """Discovery payloads for the toggles this control supports."""
        configs: dict[str, dict[str, Any]] = {}
        for column in self.switches:
            label, icon = SWITCH_PROPERTIES[column]
            slug = column.lower()
            config = self._common(slug, label)
            config.update(
                {
                    "value_template": f"{{{{ value_json.switches.{slug} }}}}",
                    "command_topic": f"{self.command_topic}/switch/{slug}",
                    "payload_on": "ON",
                    "payload_off": "OFF",
                    "icon": icon,
                }
            )
            configs[f"switch/{slug}"] = config
        return configs

    def discovery_payloads(self, unit: int = 0) -> dict[str, dict[str, Any]]:
        """Every discovery payload for this control, keyed by ``component/object``."""
        payloads: dict[str, dict[str, Any]] = {"climate/thermostat": self.climate_config(unit)}
        payloads.update(self.sensor_configs())
        payloads.update(self.switch_configs())
        return payloads

    def discovery_topic(self, key: str) -> str:
        """Full retained-config topic for one entry of :meth:`discovery_payloads`."""
        component, _, suffix = key.partition("/")
        return f"{self.discovery_prefix}/{component}/{self.object_id}/{suffix}/config"

    # --- state -------------------------------------------------------------

    def state_payload(self, state: Mapping[str, int]) -> dict[str, Any]:
        """Turn raw column values into the JSON document the entities read."""
        unit = int(state.get(PROP_TEMP_UNIT, 0))
        payload: dict[str, Any] = {
            "mode": self.hvac_mode(state),
            "target_temperature": self.target_temperature(state),
        }

        if PROP_CURRENT_TEMP in self.properties and PROP_CURRENT_TEMP in state:
            celsius = state[PROP_CURRENT_TEMP] - TEMP_SENSOR_OFFSET
            payload["indoor_temperature_c"] = celsius
            # The climate entity reads current and target temperature in the
            # same scale, so this one follows the panel while the sensor above
            # stays in Celsius.
            payload["current_temperature"] = (
                temperature.celsius_to_fahrenheit(celsius)
                if self.fahrenheit and unit == UNIT_FAHRENHEIT
                else celsius
            )

        if PROP_FAN_SPEED in self.properties:
            payload["fan_mode"] = FAN_MODES.get(int(state.get(PROP_FAN_SPEED, 0)), "auto")

        if self.presets:
            payload["preset_mode"] = self.preset_mode(state)

        payload["switches"] = {
            column.lower(): "ON" if state.get(column) else "OFF" for column in self.switches
        }
        payload["temperature_unit"] = "F" if unit == UNIT_FAHRENHEIT else "C"
        return payload

    @staticmethod
    def hvac_mode(state: Mapping[str, int]) -> str:
        """The control reports "off" through its power column, not its mode column."""
        if not state.get(PROP_POWER, 0):
            return "off"
        return HVAC_MODES.get(int(state.get(PROP_MODE, 0)), "heat_cool")

    def target_temperature(self, state: Mapping[str, int]) -> int:
        """The setpoint in whatever scale the panel is displaying."""
        set_tem = int(state.get(PROP_TARGET_TEMP, TEMP_MIN_C))
        if self.fahrenheit and int(state.get(PROP_TEMP_UNIT, 0)) == UNIT_FAHRENHEIT:
            return temperature.decode_fahrenheit(set_tem, int(state.get(PROP_TEMP_HALF, 0)))
        return set_tem

    @staticmethod
    def preset_mode(state: Mapping[str, int]) -> str:
        """The first active preset, or "none" when the control is running plain."""
        for preset, column in PRESET_PROPERTIES.items():
            if state.get(column):
                return preset
        return PRESET_NONE

    # --- commands ----------------------------------------------------------

    def command_topics(self) -> list[str]:
        """Every topic the bridge needs to subscribe to."""
        topics = [f"{self.command_topic}/mode", f"{self.command_topic}/temperature"]
        if PROP_FAN_SPEED in self.properties:
            topics.append(f"{self.command_topic}/fan_mode")
        if self.presets:
            topics.append(f"{self.command_topic}/preset_mode")
        topics.extend(f"{self.command_topic}/switch/{column.lower()}" for column in self.switches)
        return topics

    def columns_for(
        self,
        topic: str,
        payload: str,
        state: Mapping[str, int],
    ) -> dict[str, int]:
        """Translate one MQTT command into the columns to write.

        Returns an empty mapping for anything unrecognised so a stray retained
        message cannot put the control into a strange state.
        """
        if not topic.startswith(f"{self.command_topic}/"):
            return {}
        suffix = topic[len(self.command_topic) + 1 :]

        if suffix == "mode":
            return self._mode_columns(payload)
        if suffix == "temperature":
            return self._temperature_columns(payload, state)
        if suffix == "fan_mode":
            speed = FAN_MODES_REVERSE.get(payload)
            return {PROP_FAN_SPEED: speed} if speed is not None else {}
        if suffix == "preset_mode":
            return self._preset_columns(payload)
        if suffix.startswith("switch/"):
            return self._switch_columns(suffix[len("switch/") :], payload)
        return {}

    def _mode_columns(self, payload: str) -> dict[str, int]:
        if payload == "off":
            return {PROP_POWER: 0}
        mode = HVAC_MODES_REVERSE.get(payload)
        if mode is None:
            return {}
        # Selecting a mode implies turning the system on; the panel keeps the
        # two as separate columns and expects both in one write.
        return {PROP_POWER: 1, PROP_MODE: mode}

    def _temperature_columns(self, payload: str, state: Mapping[str, int]) -> dict[str, int]:
        try:
            wanted = float(payload)
        except (TypeError, ValueError):
            return {}

        if self.fahrenheit and int(state.get(PROP_TEMP_UNIT, 0)) == UNIT_FAHRENHEIT:
            set_tem, tem_rec = temperature.encode_fahrenheit(wanted)
            return {PROP_TARGET_TEMP: set_tem, PROP_TEMP_HALF: tem_rec}
        return {PROP_TARGET_TEMP: temperature.clamp_celsius(wanted)}

    def _preset_columns(self, payload: str) -> dict[str, int]:
        if payload != PRESET_NONE and payload not in self.presets:
            return {}
        # Presets are mutually exclusive, so every supported preset column is
        # written on each change rather than only the one being selected.
        return {
            column: 1 if payload == preset else 0
            for preset, column in PRESET_PROPERTIES.items()
            if column in self.properties
        }

    def _switch_columns(self, slug: str, payload: str) -> dict[str, int]:
        # Only the two payloads the discovery config declares are accepted, so a
        # stray retained message ("0", "toggle", an empty string) is ignored
        # rather than read as "off" and silently written to the control.
        wanted = {"ON": 1, "OFF": 0}.get(payload.strip().upper())
        if wanted is None:
            return {}
        for column in self.switches:
            if column.lower() == slug:
                return {column: wanted}
        return {}
