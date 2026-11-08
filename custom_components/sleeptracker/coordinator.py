"""Data update coordinators for Sleeptracker."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import (
    SleeptrackerApi,
    SleeptrackerAuthError,
    SleeptrackerError,
    parse_sleep_zip,
)
from .const import DOMAIN, FOLLOW_UP_DELAY, FOLLOW_UP_POLLS, SLOW_REFRESH

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

ZONES = ("head", "foot", "lumbar", "headTilt")


@dataclass
class BedData:
    """Everything known about one bed (one Sleeptracker processor)."""

    device: dict[str, Any]
    hello: dict[str, Any] = field(default_factory=dict)
    status: dict[str, Any] = field(default_factory=dict)
    environment: dict[str, Any] = field(default_factory=dict)
    snore_relief: dict[str, bool] | None = None
    sensor_map: list[dict[str, Any]] = field(default_factory=list)

    @property
    def processor_id(self) -> int:
        """Return the processor ID that identifies the bed."""
        return int(self.device["sleeptrackerProcessorID"])

    @property
    def controllers(self) -> list[dict[str, Any]]:
        """Return the frame controllers (one, or two on a split base)."""
        from_status = [
            inv for inv in self.status.get("invariants") or [] if inv.get("type") == "controller"
        ]
        if from_status:
            return from_status
        caps = (self.hello.get("motorMeta") or {}).get("capabilities") or []
        return [
            {
                "position": {"side": c.get("side", 0)},
                "memorySlots": c.get("memSlotCount", 0),
                "model": c.get("controllerModel"),
                "roster": {
                    "motors": c.get("motorRoster", {}),
                    "massage": c.get("massageRoster", {}),
                },
            }
            for c in caps
        ]

    @property
    def side(self) -> int | None:
        """Return the controller side this account's commands move.

        A split base has one controller per side and the cloud routes each
        account's commands to the side its sleep sensor is on.
        """
        controllers = self.controllers
        if not controllers:
            return None
        sides = [(c.get("position") or {}).get("side", 0) for c in controllers]
        if len(sides) == 1:
            return sides[0]
        own = next((s["unitNumber"] for s in self.sensor_map if s.get("self")), None)
        return own if own in sides else sides[0]

    @property
    def controller(self) -> dict[str, Any] | None:
        """Return the controller for this account's side."""
        side = self.side
        return next(
            (c for c in self.controllers if (c.get("position") or {}).get("side", 0) == side),
            None,
        )

    @property
    def snapshot(self) -> dict[str, Any] | None:
        """Return the latest status snapshot for this account's side."""
        side = self.side
        return next(
            (s for s in self.status.get("snapshots") or [] if s.get("side", 0) == side),
            None,
        )

    def has_motor(self, zone: str) -> bool:
        """Return whether the frame has a motor for ``zone``."""
        roster = ((self.controller or {}).get("roster") or {}).get("motors") or {}
        # The app's capability roster has been seen spelling lumbar "lumber".
        return bool(roster.get(zone) or (zone == "lumbar" and roster.get("lumber")))

    def has_massage(self, zone: str) -> bool:
        """Return whether the frame has a massage motor for ``zone``."""
        roster = ((self.controller or {}).get("roster") or {}).get("massage") or {}
        return bool(roster.get(zone) or (zone == "lumbar" and roster.get("lumber")))

    @property
    def online(self) -> bool:
        """Return whether the bed frame is connected to the processor."""
        return self.status.get("connectionStatus", "online") == "online"


class SleeptrackerBedCoordinator(DataUpdateCoordinator[BedData]):
    """Poll one bed's status, and send its commands."""

    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        api: SleeptrackerApi,
        device: dict[str, Any],
        interval: timedelta,
    ) -> None:
        """Set up the coordinator for one processor from its device record."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} bed {device['sleeptrackerProcessorID']}",
            update_interval=interval,
        )
        self.api = api
        self._device = device
        self._last_slow: datetime | None = None
        self._follow_task: asyncio.Task[None] | None = None

    @property
    def processor_id(self) -> int:
        """Return the processor ID."""
        return int(self._device["sleeptrackerProcessorID"])

    async def _async_update_data(self) -> BedData:
        previous = self.data or BedData(device=self._device)
        now = dt_util.utcnow()
        slow_due = self._last_slow is None or now - self._last_slow >= SLOW_REFRESH
        try:
            data = replace(previous)
            if slow_due:
                data = await self._refresh_slow(data)
                self._last_slow = now
            data.status = await self.api.async_get_status(self.processor_id)
        except SleeptrackerAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except SleeptrackerError as err:
            raise UpdateFailed(str(err)) from err
        return data

    async def _refresh_slow(self, data: BedData) -> BedData:
        """Refresh the parts of BedData that change slowly.

        Only the first refresh has to succeed in full; later failures keep the
        previous values so a hiccup in one endpoint does not take the bed's
        controls offline.
        """
        first = not data.hello
        pid = self.processor_id
        calls = {
            "device": self._fetch_device(),
            "hello": self.api.async_get_hello(pid),
            "environment": self.api.async_get_environment(pid),
            "snore_relief": self.api.async_get_snore_relief(),
            "sensor_map": self.api.async_get_sensor_map(pid),
        }
        results = await asyncio.gather(*calls.values(), return_exceptions=True)
        for key, result in zip(calls, results, strict=True):
            if isinstance(result, SleeptrackerAuthError):
                raise result
            if isinstance(result, BaseException):
                if first and key in ("device", "hello"):
                    raise result
                _LOGGER.debug("Sleeptracker %s refresh failed: %s", key, result)
                continue
            if result is not None:
                setattr(data, key, result)
        self._device = data.device
        return data

    async def _fetch_device(self) -> dict[str, Any] | None:
        for device in await self.api.async_get_devices():
            if int(device["sleeptrackerProcessorID"]) == self.processor_id:
                return device
        return None

    # ------------------------------------------------------------ commands

    async def async_command(
        self, command: int, extra: dict[str, Any] | None = None, follow: bool = False
    ) -> dict[str, Any]:
        """Send a frame command and fold the returned snapshots into the state.

        With ``follow``, keep polling status for a short while so position
        sensors track a motor or preset movement until it finishes.
        """
        try:
            body = await self.api.async_send_command(self.processor_id, command, extra)
        except SleeptrackerAuthError as err:
            self.config_entry.async_start_reauth(self.hass)
            raise HomeAssistantError(f"Sleeptracker login failed: {err}") from err
        except SleeptrackerError as err:
            raise HomeAssistantError(f"Sleeptracker command {command} failed: {err}") from err
        self._apply_status(body)
        if follow:
            self._start_follow_up()
        return body

    def _apply_status(self, body: dict[str, Any]) -> None:
        if not body.get("snapshots") or self.data is None:
            return
        status = {**self.data.status, **body}
        if not body.get("invariants") and self.data.status.get("invariants"):
            status["invariants"] = self.data.status["invariants"]
        self.async_set_updated_data(replace(self.data, status=status))

    def _start_follow_up(self) -> None:
        if self._follow_task and not self._follow_task.done():
            self._follow_task.cancel()
        self._follow_task = self.config_entry.async_create_background_task(
            self.hass, self._follow_up(), f"{self.name} follow-up"
        )

    async def _follow_up(self) -> None:
        last: tuple[int, ...] | None = None
        for _ in range(FOLLOW_UP_POLLS):
            await asyncio.sleep(FOLLOW_UP_DELAY)
            try:
                body = await self.api.async_get_status(self.processor_id)
            except SleeptrackerError as err:
                _LOGGER.debug("Sleeptracker follow-up poll failed: %s", err)
                return
            self._apply_status(body)
            snapshot = self.data.snapshot if self.data else None
            if not snapshot:
                return
            positions = tuple(
                int(((snapshot.get(z) or {}).get("motor") or {}).get("pulseCount", 0))
                for z in ZONES
            )
            if not snapshot.get("busyWithCommand") and positions == last:
                return
            last = positions


class SleeptrackerSleepCoordinator(DataUpdateCoordinator[list[dict[str, Any]]]):
    """Download the account's nightly sleep summaries from the portal."""

    config_entry: ConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, api: SleeptrackerApi, interval: timedelta
    ) -> None:
        """Set up the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} sleep",
            update_interval=interval,
        )
        self.api = api

    async def _async_update_data(self) -> list[dict[str, Any]]:
        try:
            payload = await self.api.async_download_sleep_data()
            return await self.hass.async_add_executor_job(parse_sleep_zip, payload)
        except SleeptrackerAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except SleeptrackerError as err:
            raise UpdateFailed(str(err)) from err

    @property
    def latest(self) -> dict[str, Any] | None:
        """Return the most recent night's summary."""
        return self.data[-1] if self.data else None
