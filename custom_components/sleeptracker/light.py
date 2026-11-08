"""Under-bed safety light."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.light import ColorMode, LightEntity
from homeassistant.exceptions import HomeAssistantError

from .const import Command
from .entity import SleeptrackerControlEntity

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from . import SleeptrackerConfigEntry
    from .coordinator import SleeptrackerBedCoordinator

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SleeptrackerConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add a light for each bed."""
    async_add_entities(
        SleeptrackerSafetyLight(coordinator) for coordinator in entry.runtime_data.beds.values()
    )


class SleeptrackerSafetyLight(SleeptrackerControlEntity, LightEntity):
    """The light under the bed frame.

    The cloud only offers a toggle, so turning on or off sends the toggle when
    the reported state differs and then trusts the snapshot the bed returns.
    """

    _attr_translation_key = "safety_light"
    _attr_color_mode = ColorMode.ONOFF
    _attr_supported_color_modes = {ColorMode.ONOFF}

    def __init__(self, coordinator: SleeptrackerBedCoordinator) -> None:
        """Create the light."""
        super().__init__(coordinator, "safety_light")

    @property
    def is_on(self) -> bool | None:
        """Return whether the light is on."""
        value = self.snapshot.get("safetyLightOn")
        return None if value is None else bool(value)

    async def _async_set(self, on: bool) -> None:
        if self.is_on is None:
            # A toggle with an unknown starting state could do the opposite
            # of what was asked; read the state first.
            await self.coordinator.async_refresh()
            if self.is_on is None:
                raise HomeAssistantError("The bed did not report the light's state")
        if self.is_on is on:
            return
        await self.coordinator.async_command(Command.TOGGLE_SAFETY_LIGHT)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the light on."""
        await self._async_set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the light off."""
        await self._async_set(False)
