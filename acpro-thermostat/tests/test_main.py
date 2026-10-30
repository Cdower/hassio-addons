"""Tests for the poll/command loop and its availability policy."""

from __future__ import annotations

import threading
import time

import pytest

from acpro_thermostat import __main__ as main_module
from acpro_thermostat.config import Options
from acpro_thermostat.device import DeviceError


class StubBridge:
    """Drives :func:`_serve` through a scripted sequence of poll results."""

    def __init__(self, results: list[bool], commands: list[bool] | None = None) -> None:
        self._results = list(results)
        self._commands = list(commands or [])
        self.availability: list[bool] = []
        self.polls = 0
        self.drains = 0
        self.stop: threading.Event | None = None

    def drain_commands(self, timeout: float) -> bool:
        self.drains += 1
        if self._commands:
            return self._commands.pop(0)
        assert self.stop is not None
        if not self._results:
            # The script is spent; end the loop from where the real bridge
            # would be waiting rather than letting it poll again.
            self.stop.set()
            return False
        # The real bridge blocks on its command queue for the timeout, and the
        # poll loop relies on that to pace itself.
        time.sleep(min(timeout, 0.01))
        return False

    def poll(self) -> bool:
        self.polls += 1
        assert self._results, "the poll loop ran past the end of the script"
        return self._results.pop(0)

    def publish_availability(self, available: bool) -> None:
        self.availability.append(available)


def _serve(bridge: StubBridge, scan_interval: float = 0.02) -> None:
    stop = threading.Event()
    bridge.stop = stop
    main_module._serve(bridge, Options(scan_interval=scan_interval), stop)


def test_a_single_failed_poll_does_not_flap_availability() -> None:
    bridge = StubBridge([False, True])

    _serve(bridge)

    assert bridge.availability == []


def test_repeated_failures_mark_the_device_unavailable_once() -> None:
    bridge = StubBridge([False, False, False, False])

    _serve(bridge)

    assert bridge.availability == [False]


def test_recovery_marks_the_device_available_again() -> None:
    bridge = StubBridge([False, False, False, True])

    _serve(bridge)

    assert bridge.availability == [False, True]


def test_a_run_of_failures_forces_rediscovery() -> None:
    bridge = StubBridge([False] * main_module.FAILURES_BEFORE_UNAVAILABLE * 2)

    with pytest.raises(DeviceError, match="rediscovering"):
        _serve(bridge)


def test_a_command_cuts_the_polling_interval_short() -> None:
    """Without this the dashboard would show the old value for a whole interval."""
    bridge = StubBridge([True, True], commands=[False, True])

    started = time.monotonic()
    _serve(bridge, scan_interval=30)
    elapsed = time.monotonic() - started

    # Two polls happened despite a 30 second interval, because the queued
    # command interrupted the wait after the first one.
    assert bridge.polls >= 2
    assert elapsed < 5


def test_stopping_ends_the_loop() -> None:
    bridge = StubBridge([True, True])
    stop = threading.Event()
    bridge.stop = stop
    stop.set()

    main_module._serve(bridge, Options(), stop)

    assert bridge.polls == 0


def test_waiting_to_retry_returns_at_once_when_stopping() -> None:
    stop = threading.Event()
    stop.set()

    main_module._wait_before_retry(stop)  # would otherwise block for RETRY_SECONDS
