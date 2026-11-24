"""Snore-relief settings.

These are account settings in the Sleeptracker cloud: when the sleep sensor
hears snoring, the base can tilt the head up and/or vibrate.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.exceptions import HomeAssistantError

from .api import SleeptrackerError
from .entity import SleeptrackerBedEntity

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from . import SleeptrackerConfigEntry
    from .coordinator import SleeptrackerBedCoordinator

PARALLEL_UPDATES = 1

SETTINGS = {
    "snore_relief_tilt": "snoreReliefTilt",
    "snore_relief_vibration": "snoreReliefVibration",
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SleeptrackerConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the snore-relief switches."""
    async_add_entities(
        SleeptrackerSnoreReliefSwitch(coordinator, key, field)
        for coordinator in entry.runtime_data.beds.values()
        if coordinator.data.snore_relief is not None
        for key, field in SETTINGS.items()
    )


class SleeptrackerSnoreReliefSwitch(SleeptrackerBedEntity, SwitchEntity):
    """One snore-relief response."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: SleeptrackerBedCoordinator, key: str, field: str) -> None:
        """Create the switch."""
        super().__init__(coordinator, key)
        self._attr_translation_key = key
        self._field = field

    @property
    def available(self) -> bool:
        """Return whether the setting is known."""
        return super().available and self.bed.snore_relief is not None

    @property
    def is_on(self) -> bool | None:
        """Return whether this response is enabled."""
        settings = self.bed.snore_relief
        return None if settings is None else settings.get(self._field)

    async def _async_set(self, value: bool) -> None:
        current = dict(self.bed.snore_relief or {})
        current[self._field] = value
        api = self.coordinator.api
        try:
            await api.async_set_snore_relief(
                current.get("snoreReliefTilt", False), current.get("snoreReliefVibration", False)
            )
            settings = await api.async_get_snore_relief()
        except SleeptrackerError as err:
            raise HomeAssistantError(f"Could not change snore relief: {err}") from err
        self.coordinator.async_set_updated_data(
            replace(self.coordinator.data, snore_relief=settings)
        )

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable this response."""
        await self._async_set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable this response."""
        await self._async_set(False)
