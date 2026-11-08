"""Recorder test for the sleep statistics import."""

from __future__ import annotations

import pytest
from homeassistant.components.recorder import Recorder
from homeassistant.components.recorder.statistics import statistics_during_period
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.recorder.common import (
    async_wait_recording_done,
)

from custom_components.sleeptracker.statistics import async_import_sleep_statistics

from .conftest import EMAIL, SUMMARIES


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(
    recorder_mock: Recorder, enable_custom_integrations: None
) -> None:
    """Start the recorder before hass, as the recorder fixtures require."""


async def test_statistics_import(recorder_mock: Recorder, hass: HomeAssistant) -> None:
    """Nightly metrics land in the recorder as external statistics."""
    entry = MockConfigEntry(domain="sleeptracker", unique_id=EMAIL, title=EMAIL)
    await async_import_sleep_statistics(hass, entry, SUMMARIES, "Bedroom sleep")
    await async_wait_recording_done(hass)

    stat_id = "sleeptracker:sleeper_example_com_sleep_score"
    rows = await recorder_mock.async_add_executor_job(
        statistics_during_period,
        hass,
        dt_util.utc_from_timestamp(SUMMARIES[0]["endTimeUtcSecs"] - 7200),
        None,
        {stat_id},
        "hour",
        None,
        {"mean"},
    )
    assert [r["mean"] for r in rows[stat_id]] == [71, 75, 80]
