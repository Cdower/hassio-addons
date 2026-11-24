"""Fixtures for the Sleeptracker integration tests.

Run with the Home Assistant test harness installed, from the repository root:

    pytest tests/sleeptracker

The JSON fixtures are real cloud responses from a 2023 Ergo Smart base with
serial numbers, MAC addresses and IDs replaced. The sleep summaries are
synthetic.
"""

from __future__ import annotations

import io
import json
import sys
import zipfile
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from homeassistant.const import CONF_EMAIL, CONF_PASSWORD  # noqa: E402
from pytest_homeassistant_custom_component.common import MockConfigEntry  # noqa: E402

from custom_components.sleeptracker.api import SleeptrackerApi  # noqa: E402
from custom_components.sleeptracker.const import DOMAIN  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"
PROCESSOR_ID = 100001
EMAIL = "sleeper@example.com"


def load(name: str) -> dict[str, Any]:
    """Return a JSON fixture."""
    return json.loads((FIXTURES / f"{name}.json").read_text())


def sleep_summary(day: str, end: int, score: int) -> dict[str, Any]:
    """Return a synthetic nightly summary shaped like the portal's."""
    return {
        "sleepSummaryDay": day,
        "startTimeUtcSecs": end - 8 * 3600,
        "fellAsleepTimeUtcSecs": end - 8 * 3600 + 600,
        "endTimeUtcSecs": end,
        "sleepQuality": score,
        "totalSleepSecs": 7 * 3600,
        "deepSleepSecs": 3600,
        "lightSleepSecs": 4 * 3600,
        "remSleepSecs": 2 * 3600,
        "totalAwakeSecs": 1800,
        "sleepEfficiency": 92.5,
        "sleepGoalPercentage": 93.0,
        "wakeups": 2,
        "hrAverage": 61.0,
        "rrAverage": 14.6,
        "hrvRmssdMean": 31.24,
        "hrvSdnnMean": 40.55,
        "arousalIndex": 12.34,
        "outOfBedCount": 1,
        "outOfBedSecs": 300,
        "breathingDisturbanceCategory": "Few",
        "sleepSummarySpans": [
            {"startTimeUtcSecs": end - 8 * 3600, "durationSecs": 600, "sleepType": "AWAKE"},
            {"startTimeUtcSecs": end - 8 * 3600 + 600, "durationSecs": 3000, "sleepType": "LIGHT"},
        ],
        "sleepEvents": [
            {"startTimeUtcSecs": end - 3600, "durationSecs": 60, "eventType": "Restless"}
        ],
    }


SUMMARIES = [
    sleep_summary("20261105", 1793900000, 71),
    sleep_summary("20261106", 1793986400, 75),
    sleep_summary("20261107", 1794072600, 80),
]


def sleep_zip(summaries: list[dict[str, Any]]) -> bytes:
    """Return a portal-style data download ZIP."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr("User.json", "{}")
        for summary in summaries:
            day = summary["sleepSummaryDay"]
            name = f"{day[:4]}/Sleep_Summary_{day[:4]}-{day[4:6]}-{day[6:]}.json"
            archive.writestr(name, json.dumps({"sleepSummary": summary}))
        archive.writestr("2026/Sleep_Summary_2026-11-08.json", json.dumps({"sleepSummary": {}}))
    return buf.getvalue()


class FakeApi(SleeptrackerApi):
    """SleeptrackerApi answering from fixtures and recording commands."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Ignore the sessions and credentials."""
        self.commands: list[tuple[int, dict[str, Any]]] = []
        self.status = load("status")["body"]
        self.snore = {"snoreReliefTilt": True, "snoreReliefVibration": True}
        self.snore_sets: list[tuple[bool, bool]] = []
        self.summaries = list(SUMMARIES)
        self.username = EMAIL

    async def async_login(self, force: bool = False) -> None:
        """Pretend to log in."""

    async def async_get_devices(self) -> list[dict[str, Any]]:
        """Return the device fixture."""
        return load("devices")["deviceList"]

    async def async_get_hello(self, processor_id: int) -> dict[str, Any]:
        """Return the hello fixture."""
        return load("hello")["helloData"]

    async def async_get_sensor_map(self, processor_id: int) -> list[dict[str, Any]]:
        """Return the sensor map fixture."""
        return load("sensormap")["sensorMap"]

    async def async_get_environment(self, processor_id: int) -> dict[str, Any]:
        """Return the environment fixture's valid readings."""
        data = load("env")
        return {k: v for k, v in data.items() if isinstance(v, dict)}

    async def async_send_command(
        self, processor_id: int, command: int, extra: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Record a command and simulate its effect on the light."""
        if command != 1:
            self.commands.append((command, extra or {}))
        if command == 230:
            snap = self.status["snapshots"][0]
            snap["safetyLightOn"] = not snap["safetyLightOn"]
        return json.loads(json.dumps(self.status))

    async def async_get_snore_relief(self) -> dict[str, bool]:
        """Return the stored snore-relief settings."""
        return dict(self.snore)

    async def async_set_snore_relief(self, tilt: bool, vibration: bool) -> None:
        """Store snore-relief settings."""
        self.snore_sets.append((tilt, vibration))
        self.snore = {"snoreReliefTilt": tilt, "snoreReliefVibration": vibration}

    async def async_download_sleep_data(self) -> bytes:
        """Return the synthetic summaries as a portal ZIP."""
        return sleep_zip(self.summaries)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Let Home Assistant load custom_components/sleeptracker."""


@pytest.fixture
def fake_api() -> FakeApi:
    """Return the fake API that setup will use."""
    return FakeApi()


@pytest.fixture
def mock_api(fake_api: FakeApi):
    """Make the integration use the fake API."""
    with (
        patch("custom_components.sleeptracker.SleeptrackerApi", return_value=fake_api),
        patch("custom_components.sleeptracker.coordinator.FOLLOW_UP_DELAY", 0),
    ):
        yield fake_api


@pytest.fixture
def config_entry() -> MockConfigEntry:
    """Return a config entry for the test account."""
    return MockConfigEntry(
        domain=DOMAIN,
        title=EMAIL,
        unique_id=EMAIL,
        data={CONF_EMAIL: EMAIL, CONF_PASSWORD: "hunter2"},  # pragma: allowlist secret
    )
