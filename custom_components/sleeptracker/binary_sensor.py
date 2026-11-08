"""Connectivity and activity binary sensors for the bed."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory

from .entity import SleeptrackerBedEntity

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from . import SleeptrackerConfigEntry
    from .coordinator import BedData, SleeptrackerBedCoordinator

PARALLEL_UPDATES = 0


def _snap(bed: BedData, key: str) -> bool | None:
    snapshot = bed.snapshot
    if snapshot is None or key not in snapshot:
        return None
    return bool(snapshot[key])


def _sensor_connected(side: str) -> Callable[[BedData], bool | None]:
    def value(bed: BedData) -> bool | None:
        status = (bed.hello.get(f"{side}Sensor") or {}).get("status")
        return None if status is None else status == "connected"

    return value


def _massage_active(bed: BedData) -> bool | None:
    snapshot = bed.snapshot
    if snapshot is None:
        return None
    return any(
        ((snapshot.get(zone) or {}).get("massage") or {}).get("active")
        for zone in ("head", "foot", "lumbar", "headTilt")
    )


@dataclass(frozen=True, kw_only=True)
class SleeptrackerBinarySensorDescription(BinarySensorEntityDescription):
    """A binary sensor computed from BedData."""

    value_fn: Callable[[BedData], bool | None]


BINARY_SENSORS: tuple[SleeptrackerBinarySensorDescription, ...] = (
    SleeptrackerBinarySensorDescription(
        key="frame_connected",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda bed: bed.online if bed.status else None,
    ),
    SleeptrackerBinarySensorDescription(
        key="cloud_connected",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda bed: bed.hello.get("ServerConnectivity") if bed.hello else None,
    ),
    SleeptrackerBinarySensorDescription(
        key="left_sensor_connected",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_sensor_connected("left"),
    ),
    SleeptrackerBinarySensorDescription(
        key="right_sensor_connected",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_sensor_connected("right"),
    ),
    SleeptrackerBinarySensorDescription(
        key="massage_active",
        device_class=BinarySensorDeviceClass.RUNNING,
        value_fn=_massage_active,
    ),
    SleeptrackerBinarySensorDescription(
        key="moving",
        device_class=BinarySensorDeviceClass.MOVING,
        value_fn=lambda bed: _snap(bed, "busyWithCommand"),
    ),
    SleeptrackerBinarySensorDescription(
        key="panel_light",
        device_class=BinarySensorDeviceClass.LIGHT,
        entity_registry_enabled_default=False,
        value_fn=lambda bed: _snap(bed, "panelLightOn"),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SleeptrackerConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the bed's binary sensors."""
    async_add_entities(
        SleeptrackerBinarySensor(coordinator, description)
        for coordinator in entry.runtime_data.beds.values()
        for description in BINARY_SENSORS
    )


class SleeptrackerBinarySensor(SleeptrackerBedEntity, BinarySensorEntity):
    """A bed binary sensor."""

    entity_description: SleeptrackerBinarySensorDescription

    def __init__(
        self,
        coordinator: SleeptrackerBedCoordinator,
        description: SleeptrackerBinarySensorDescription,
    ) -> None:
        """Create the sensor."""
        super().__init__(coordinator, description.key)
        self.entity_description = description
        self._attr_translation_key = description.key

    @property
    def is_on(self) -> bool | None:
        """Return the sensor value."""
        return self.entity_description.value_fn(self.bed)
