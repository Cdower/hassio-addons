"""Base entities for Sleeptracker."""

from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .coordinator import BedData, SleeptrackerBedCoordinator, SleeptrackerSleepCoordinator


def bed_device_info(data: BedData) -> DeviceInfo:
    """Return the device registry entry for a bed."""
    device = data.device
    base = device.get("powerBase") or {}
    mac = (device.get("macAddress") or "").replace("-", ":")
    return DeviceInfo(
        identifiers={(DOMAIN, str(data.processor_id))},
        connections={(CONNECTION_NETWORK_MAC, mac)} if mac else set(),
        name=device.get("name") or "Sleeptracker bed",
        manufacturer=MANUFACTURER,
        model=base.get("modelDescription") or device.get("modelID"),
        model_id=base.get("modelNumber"),
        sw_version=device.get("processorVersionFirmware"),
        hw_version=device.get("modelID"),
        serial_number=device.get("processorSerialNumber"),
    )


class SleeptrackerBedEntity(CoordinatorEntity[SleeptrackerBedCoordinator]):
    """An entity attached to a bed."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: SleeptrackerBedCoordinator, key: str) -> None:
        """Bind the entity to the bed and give it a stable unique ID."""
        super().__init__(coordinator)
        data = coordinator.data
        # On a split base each account controls its own side, and both
        # accounts may load the same bed, so the side keeps their IDs apart.
        if len(data.controllers) > 1:
            key = f"side{data.side}_{key}"
        self._attr_unique_id = f"{coordinator.processor_id}_{key}"
        self._attr_device_info = bed_device_info(data)

    @property
    def bed(self) -> BedData:
        """Return the bed's current data."""
        return self.coordinator.data

    @property
    def snapshot(self) -> dict[str, Any]:
        """Return this account's side snapshot, or an empty dict."""
        return self.coordinator.data.snapshot or {}


class SleeptrackerControlEntity(SleeptrackerBedEntity):
    """A bed entity that is only meaningful while the frame is connected."""

    @property
    def available(self) -> bool:
        """Return False when the cloud or the frame is unreachable."""
        return super().available and self.bed.online and self.bed.snapshot is not None


class SleeptrackerSleepEntity(CoordinatorEntity[SleeptrackerSleepCoordinator]):
    """An entity for the account's sleep data."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: SleeptrackerSleepCoordinator, key: str, device_info: DeviceInfo
    ) -> None:
        """Bind the entity to the account's sleep device."""
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.unique_id or entry.entry_id}_sleep_{key}"
        self._attr_device_info = device_info
