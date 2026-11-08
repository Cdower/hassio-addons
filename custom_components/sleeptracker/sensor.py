"""Bed, room-environment and sleep sensors."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    CONCENTRATION_PARTS_PER_BILLION,
    CONCENTRATION_PARTS_PER_MILLION,
    DEGREE,
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    EntityCategory,
    UnitOfTemperature,
    UnitOfTime,
)

from .const import MASSAGE_PATTERNS
from .cover import pulse_count
from .entity import SleeptrackerBedEntity, SleeptrackerSleepEntity

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.device_registry import DeviceInfo
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from . import SleeptrackerConfigEntry
    from .coordinator import BedData, SleeptrackerBedCoordinator, SleeptrackerSleepCoordinator

PARALLEL_UPDATES = 0

MASSAGE_PATTERN_OPTIONS = sorted(set(MASSAGE_PATTERNS.values()))


def _ts(value: Any) -> datetime | None:
    return datetime.fromtimestamp(value, UTC) if value else None


def _angle(zone: str, ticks_field: str) -> Callable[[BedData], float | None]:
    def value(bed: BedData) -> float | None:
        count = pulse_count(bed.snapshot or {}, zone)
        ticks = (bed.device.get("powerBase") or {}).get(ticks_field)
        if count is None or not ticks:
            return None
        return round(count / ticks, 1)

    return value


def _pulses(zone: str) -> Callable[[BedData], int | None]:
    return lambda bed: pulse_count(bed.snapshot or {}, zone)


def _massage_strength(zone: str) -> Callable[[BedData], int | None]:
    def value(bed: BedData) -> int | None:
        massage = ((bed.snapshot or {}).get(zone) or {}).get("massage")
        return None if massage is None else int(massage.get("strength", 0))

    return value


def _massage_pattern(bed: BedData) -> str | None:
    snapshot = bed.snapshot
    if snapshot is None or "massagePattern" not in snapshot:
        return None
    return MASSAGE_PATTERNS.get(int(snapshot["massagePattern"]))


def _massage_timer(bed: BedData) -> int | None:
    snapshot = bed.snapshot
    if snapshot is None:
        return None
    return int(snapshot.get("massageTimerMins", 0)) * 60 + int(snapshot.get("massageTimerSecs", 0))


def _env(field: str, digits: int = 1) -> Callable[[BedData], float | None]:
    def value(bed: BedData) -> float | None:
        reading = bed.environment.get(field)
        if not reading or reading.get("value") is None:
            return None
        return round(float(reading["value"]), digits)

    return value


@dataclass(frozen=True, kw_only=True)
class BedSensorDescription(SensorEntityDescription):
    """A sensor computed from BedData."""

    value_fn: Callable[[BedData], Any]
    supported: Callable[[BedData], bool] = lambda _bed: True


BED_SENSORS: tuple[BedSensorDescription, ...] = (
    BedSensorDescription(
        key="head_angle",
        native_unit_of_measurement=DEGREE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_angle("head", "headAngleTicksPerDegree"),
        supported=lambda bed: bed.has_motor("head"),
    ),
    BedSensorDescription(
        key="foot_angle",
        native_unit_of_measurement=DEGREE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_angle("foot", "footAngleTicksPerDegree"),
        supported=lambda bed: bed.has_motor("foot"),
    ),
    BedSensorDescription(
        key="lumbar_position",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_pulses("lumbar"),
        supported=lambda bed: bed.has_motor("lumbar"),
    ),
    BedSensorDescription(
        key="head_tilt_position",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_pulses("headTilt"),
        supported=lambda bed: bed.has_motor("headTilt"),
    ),
    BedSensorDescription(
        key="head_massage_strength",
        value_fn=_massage_strength("head"),
        supported=lambda bed: bed.has_massage("head"),
    ),
    BedSensorDescription(
        key="foot_massage_strength",
        value_fn=_massage_strength("foot"),
        supported=lambda bed: bed.has_massage("foot"),
    ),
    BedSensorDescription(
        key="massage_pattern",
        device_class=SensorDeviceClass.ENUM,
        options=MASSAGE_PATTERN_OPTIONS,
        value_fn=_massage_pattern,
        supported=lambda bed: bed.has_massage("head") or bed.has_massage("foot"),
    ),
    BedSensorDescription(
        key="massage_timer",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        value_fn=_massage_timer,
        supported=lambda bed: bed.has_massage("head") or bed.has_massage("foot"),
    ),
    BedSensorDescription(
        key="temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_env("degreesCelsius"),
    ),
    BedSensorDescription(
        key="humidity",
        device_class=SensorDeviceClass.HUMIDITY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_env("humidityPercentage"),
    ),
    BedSensorDescription(
        key="co2",
        device_class=SensorDeviceClass.CO2,
        native_unit_of_measurement=CONCENTRATION_PARTS_PER_MILLION,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_env("co2Ppm", 0),
    ),
    BedSensorDescription(
        key="voc",
        device_class=SensorDeviceClass.VOLATILE_ORGANIC_COMPOUNDS_PARTS,
        native_unit_of_measurement=CONCENTRATION_PARTS_PER_BILLION,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_env("vocPpb", 0),
    ),
    BedSensorDescription(
        key="air_quality_index",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_env("iaq", 0),
    ),
    BedSensorDescription(
        key="wifi_signal",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda bed: bed.device.get("lastWiFiSignal"),
    ),
    BedSensorDescription(
        key="wifi_rssi",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda bed: bed.device.get("lastWiFiRSSI"),
    ),
    BedSensorDescription(
        key="last_heartbeat",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda bed: _ts(bed.device.get("lastHeartbeatGMTSecs")),
    ),
    BedSensorDescription(
        key="last_sleep_upload",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda bed: _ts(bed.hello.get("gmtLastGoodSleepUpload")),
    ),
    BedSensorDescription(
        key="last_movement",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda bed: _ts((bed.snapshot or {}).get("timeLastActuatorMovement")),
    ),
)


@dataclass(frozen=True, kw_only=True)
class SleepSensorDescription(SensorEntityDescription):
    """A sensor computed from the latest night's summary."""

    value_fn: Callable[[dict[str, Any]], Any]


def _field(name: str, digits: int | None = None) -> Callable[[dict[str, Any]], Any]:
    def value(summary: dict[str, Any]) -> Any:
        raw = summary.get(name)
        if raw is None or digits is None:
            return raw
        return round(float(raw), digits)

    return value


def _minutes(name: str) -> Callable[[dict[str, Any]], float | None]:
    def value(summary: dict[str, Any]) -> float | None:
        raw = summary.get(name)
        return None if raw is None else round(raw / 60, 1)

    return value


def _night(summary: dict[str, Any]) -> date | None:
    day = str(summary.get("sleepSummaryDay") or "")
    try:
        return date(int(day[:4]), int(day[4:6]), int(day[6:8]))
    except ValueError:
        return None


def _duration(key: str, field: str) -> SleepSensorDescription:
    return SleepSensorDescription(
        key=key,
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        suggested_unit_of_measurement=UnitOfTime.HOURS,
        suggested_display_precision=1,
        value_fn=_minutes(field),
    )


SLEEP_SENSORS: tuple[SleepSensorDescription, ...] = (
    SleepSensorDescription(key="sleep_score", value_fn=_field("sleepQuality")),
    SleepSensorDescription(key="night", device_class=SensorDeviceClass.DATE, value_fn=_night),
    _duration("total_sleep", "totalSleepSecs"),
    _duration("deep_sleep", "deepSleepSecs"),
    _duration("light_sleep", "lightSleepSecs"),
    _duration("rem_sleep", "remSleepSecs"),
    _duration("awake_time", "totalAwakeSecs"),
    _duration("out_of_bed_time", "outOfBedSecs"),
    SleepSensorDescription(
        key="sleep_efficiency",
        native_unit_of_measurement=PERCENTAGE,
        value_fn=_field("sleepEfficiency", 1),
    ),
    SleepSensorDescription(
        key="sleep_goal",
        native_unit_of_measurement=PERCENTAGE,
        value_fn=_field("sleepGoalPercentage", 0),
    ),
    SleepSensorDescription(key="wakeups", value_fn=_field("wakeups")),
    SleepSensorDescription(key="out_of_bed_count", value_fn=_field("outOfBedCount")),
    SleepSensorDescription(
        key="heart_rate",
        native_unit_of_measurement="bpm",
        value_fn=_field("hrAverage", 0),
    ),
    SleepSensorDescription(
        key="respiration_rate",
        native_unit_of_measurement="br/min",
        value_fn=_field("rrAverage", 1),
    ),
    SleepSensorDescription(
        key="hrv_rmssd",
        native_unit_of_measurement=UnitOfTime.MILLISECONDS,
        value_fn=_field("hrvRmssdMean", 1),
    ),
    SleepSensorDescription(
        key="hrv_sdnn",
        native_unit_of_measurement=UnitOfTime.MILLISECONDS,
        value_fn=_field("hrvSdnnMean", 1),
    ),
    SleepSensorDescription(key="arousal_index", value_fn=_field("arousalIndex", 1)),
    SleepSensorDescription(
        key="breathing_disturbance", value_fn=_field("breathingDisturbanceCategory")
    ),
    SleepSensorDescription(
        key="bedtime",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda s: _ts(s.get("startTimeUtcSecs")),
    ),
    SleepSensorDescription(
        key="fell_asleep",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda s: _ts(s.get("fellAsleepTimeUtcSecs")),
    ),
    SleepSensorDescription(
        key="wake_time",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda s: _ts(s.get("endTimeUtcSecs")),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SleeptrackerConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add bed and sleep sensors."""
    runtime = entry.runtime_data
    entities: list[SensorEntity] = [
        SleeptrackerBedSensor(coordinator, description)
        for coordinator in runtime.beds.values()
        for description in BED_SENSORS
        if description.supported(coordinator.data)
    ]
    entities.extend(
        SleeptrackerSleepSensor(runtime.sleep, description, runtime.sleep_device)
        for description in SLEEP_SENSORS
    )
    async_add_entities(entities)


class SleeptrackerBedSensor(SleeptrackerBedEntity, SensorEntity):
    """A bed sensor."""

    entity_description: BedSensorDescription

    def __init__(
        self, coordinator: SleeptrackerBedCoordinator, description: BedSensorDescription
    ) -> None:
        """Create the sensor."""
        super().__init__(coordinator, description.key)
        self.entity_description = description
        self._attr_translation_key = description.key

    @property
    def native_value(self) -> Any:
        """Return the sensor value."""
        return self.entity_description.value_fn(self.bed)


class SleeptrackerSleepSensor(SleeptrackerSleepEntity, SensorEntity):
    """One metric from the latest night."""

    entity_description: SleepSensorDescription
    # The hypnogram and events change once a night and are large; keep them
    # out of the recorder (the nightly numbers go to statistics instead).
    _unrecorded_attributes = frozenset({"stages", "events"})

    def __init__(
        self,
        coordinator: SleeptrackerSleepCoordinator,
        description: SleepSensorDescription,
        device_info: DeviceInfo,
    ) -> None:
        """Create the sensor."""
        super().__init__(coordinator, description.key, device_info)
        self.entity_description = description
        self._attr_translation_key = description.key

    @property
    def native_value(self) -> Any:
        """Return the metric for the latest night."""
        summary = self.coordinator.latest
        return None if summary is None else self.entity_description.value_fn(summary)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Attach the sleep-stage timeline and events to the score sensor."""
        summary = self.coordinator.latest
        if summary is None or self.entity_description.key != "sleep_score":
            return None
        return {
            "nights_recorded": len(self.coordinator.data or []),
            "stages": [
                {
                    "start": _ts(span.get("startTimeUtcSecs")),
                    "minutes": round(span.get("durationSecs", 0) / 60),
                    "stage": str(span.get("sleepType", "")).lower(),
                }
                for span in summary.get("sleepSummarySpans") or []
            ],
            "events": [
                {
                    "start": _ts(event.get("startTimeUtcSecs")),
                    "minutes": round(event.get("durationSecs", 0) / 60),
                    "type": event.get("eventType"),
                }
                for event in summary.get("sleepEvents") or []
            ],
        }
