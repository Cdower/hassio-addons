"""Bed-frame motors (head, foot, lumbar, head tilt) as covers.

Open raises the section, close lowers it and stop halts it, mirroring the
remote's buttons. The cloud reports each motor's position as a pulse count;
covers expose the pulse count and, for head and foot where the base reports a
ticks-per-degree factor, the angle as attributes. The cloud has no "move to
position" command, so covers do not support set_position; use the preset
buttons to go to a stored position.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from homeassistant.components.cover import CoverEntity, CoverEntityFeature

from .const import Command
from .entity import SleeptrackerControlEntity

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from . import SleeptrackerConfigEntry
    from .coordinator import SleeptrackerBedCoordinator

PARALLEL_UPDATES = 1


@dataclass(frozen=True)
class Motor:
    """One motorised zone."""

    zone: str  # key in the snapshot and capability roster
    key: str  # unique ID / translation key
    up: Command
    down: Command
    stop: Command
    ticks_field: str | None = None  # powerBase field giving ticks per degree


MOTORS = (
    Motor(
        "head",
        "head",
        Command.HEAD_UP,
        Command.HEAD_DOWN,
        Command.HEAD_STOP,
        "headAngleTicksPerDegree",
    ),
    Motor(
        "foot",
        "foot",
        Command.FOOT_UP,
        Command.FOOT_DOWN,
        Command.FOOT_STOP,
        "footAngleTicksPerDegree",
    ),
    Motor("lumbar", "lumbar", Command.LUMBAR_UP, Command.LUMBAR_DOWN, Command.LUMBAR_STOP),
    Motor("headTilt", "head_tilt", Command.TILT_UP, Command.TILT_DOWN, Command.TILT_STOP),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SleeptrackerConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add a cover for each motor the frame has."""
    async_add_entities(
        SleeptrackerMotorCover(coordinator, motor)
        for coordinator in entry.runtime_data.beds.values()
        for motor in MOTORS
        if coordinator.data.has_motor(motor.zone)
    )


def pulse_count(snapshot: dict[str, Any], zone: str) -> int | None:
    """Return a zone's motor pulse count from a snapshot."""
    value = ((snapshot.get(zone) or {}).get("motor") or {}).get("pulseCount")
    return None if value is None else int(value)


class SleeptrackerMotorCover(SleeptrackerControlEntity, CoverEntity):
    """One section of the frame."""

    _attr_supported_features = (
        CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE | CoverEntityFeature.STOP
    )

    def __init__(self, coordinator: SleeptrackerBedCoordinator, motor: Motor) -> None:
        """Create the cover."""
        super().__init__(coordinator, f"motor_{motor.key}")
        self._motor = motor
        self._attr_translation_key = f"motor_{motor.key}"
        self._direction: str | None = None

    @property
    def is_closed(self) -> bool | None:
        """Return True when the section is fully lowered."""
        count = pulse_count(self.snapshot, self._motor.zone)
        return None if count is None else count == 0

    @property
    def is_opening(self) -> bool:
        """Return whether a raise command is in progress."""
        return self._direction == "up" and bool(self.snapshot.get("busyWithCommand"))

    @property
    def is_closing(self) -> bool:
        """Return whether a lower command is in progress."""
        return self._direction == "down" and bool(self.snapshot.get("busyWithCommand"))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose the raw position and, where known, the angle."""
        count = pulse_count(self.snapshot, self._motor.zone)
        attrs: dict[str, Any] = {"pulse_count": count}
        ticks = (self.bed.device.get("powerBase") or {}).get(self._motor.ticks_field or "")
        if count is not None and ticks:
            attrs["angle"] = round(count / ticks, 1)
        return attrs

    async def _send(self, command: Command, direction: str | None) -> None:
        self._direction = direction
        await self.coordinator.async_command(command, follow=True)

    async def async_open_cover(self, **kwargs: Any) -> None:
        """Raise the section."""
        await self._send(self._motor.up, "up")

    async def async_close_cover(self, **kwargs: Any) -> None:
        """Lower the section."""
        await self._send(self._motor.down, "down")

    async def async_stop_cover(self, **kwargs: Any) -> None:
        """Stop the section."""
        await self._send(self._motor.stop, None)
