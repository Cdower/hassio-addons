"""Preset, preset-programming and massage buttons."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.const import EntityCategory

from .const import MASSAGE_STEP_PAYLOAD, Command
from .entity import SleeptrackerControlEntity

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from . import SleeptrackerConfigEntry
    from .coordinator import BedData, SleeptrackerBedCoordinator

PARALLEL_UPDATES = 1


def _anti_snore(bed: BedData) -> bool:
    return bool((bed.device.get("powerBase") or {}).get("antiSnorePresetSupported", True))


def _any_massage(bed: BedData) -> bool:
    return bed.has_massage("head") or bed.has_massage("foot")


@dataclass(frozen=True, kw_only=True)
class SleeptrackerButtonDescription(ButtonEntityDescription):
    """A button that sends one frame command."""

    command: Command
    payload: dict[str, Any] = field(default_factory=dict)
    # Whether the command moves motors, so status should be followed.
    moves: bool = False
    supported: Callable[[BedData], bool] = lambda _bed: True


BUTTONS: tuple[SleeptrackerButtonDescription, ...] = (
    SleeptrackerButtonDescription(key="preset_flat", command=Command.PRESET_FLAT, moves=True),
    SleeptrackerButtonDescription(key="preset_zero_g", command=Command.PRESET_ZERO_G, moves=True),
    SleeptrackerButtonDescription(key="preset_tv", command=Command.PRESET_TV, moves=True),
    SleeptrackerButtonDescription(
        key="preset_anti_snore",
        command=Command.PRESET_ANTI_SNORE,
        moves=True,
        supported=_anti_snore,
    ),
    SleeptrackerButtonDescription(
        key="preset_favorite", command=Command.PRESET_FAVORITE, moves=True
    ),
    SleeptrackerButtonDescription(
        key="program_zero_g",
        command=Command.PROGRAM_ZERO_G,
        entity_category=EntityCategory.CONFIG,
    ),
    SleeptrackerButtonDescription(
        key="program_tv", command=Command.PROGRAM_TV, entity_category=EntityCategory.CONFIG
    ),
    SleeptrackerButtonDescription(
        key="program_anti_snore",
        command=Command.PROGRAM_ANTI_SNORE,
        entity_category=EntityCategory.CONFIG,
        supported=_anti_snore,
    ),
    SleeptrackerButtonDescription(
        key="program_favorite",
        command=Command.PROGRAM_FAVORITE,
        entity_category=EntityCategory.CONFIG,
    ),
    SleeptrackerButtonDescription(
        key="massage_head_step",
        command=Command.MASSAGE_HEAD_STEP,
        payload=MASSAGE_STEP_PAYLOAD,
        supported=lambda bed: bed.has_massage("head"),
    ),
    SleeptrackerButtonDescription(
        key="massage_foot_step",
        command=Command.MASSAGE_FOOT_STEP,
        payload=MASSAGE_STEP_PAYLOAD,
        supported=lambda bed: bed.has_massage("foot"),
    ),
    SleeptrackerButtonDescription(
        key="massage_step",
        command=Command.MASSAGE_STEP,
        supported=lambda bed: bed.has_massage("head") and bed.has_massage("foot"),
    ),
    SleeptrackerButtonDescription(
        key="massage_pattern_step", command=Command.MASSAGE_PATTERN_STEP, supported=_any_massage
    ),
    SleeptrackerButtonDescription(
        key="massage_timer_step", command=Command.MASSAGE_TIMER_STEP, supported=_any_massage
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SleeptrackerConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the buttons each bed supports."""
    async_add_entities(
        SleeptrackerButton(coordinator, description)
        for coordinator in entry.runtime_data.beds.values()
        for description in BUTTONS
        if description.supported(coordinator.data)
    )


class SleeptrackerButton(SleeptrackerControlEntity, ButtonEntity):
    """Send one frame command."""

    entity_description: SleeptrackerButtonDescription

    def __init__(
        self,
        coordinator: SleeptrackerBedCoordinator,
        description: SleeptrackerButtonDescription,
    ) -> None:
        """Create the button."""
        super().__init__(coordinator, description.key)
        self.entity_description = description
        self._attr_translation_key = description.key

    async def async_press(self) -> None:
        """Send the command."""
        description = self.entity_description
        await self.coordinator.async_command(
            description.command, dict(description.payload), follow=description.moves
        )
