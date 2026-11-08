"""Import nightly sleep summaries into Home Assistant long-term statistics.

Each night becomes one hourly statistics row, at the hour the night ended, for
each metric below. That puts the whole history the portal holds (back to the
first night the bed recorded) into the statistics graph card and the energy-
style history views, not just what the sensors saw since the integration was
installed. Re-importing a night overwrites the same row, so this is idempotent.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from homeassistant.components.recorder.models import (
    StatisticData,
    StatisticMeanType,
    StatisticMetaData,
)
from homeassistant.components.recorder.statistics import async_add_external_statistics
from homeassistant.const import PERCENTAGE, UnitOfTime
from homeassistant.util import slugify

from .const import DOMAIN

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class SleepStatistic:
    """One summary field to import."""

    key: str
    field: str
    name: str
    unit: str | None
    unit_class: str | None = None
    scale: float = 1.0


SLEEP_STATISTICS = (
    SleepStatistic("sleep_score", "sleepQuality", "Sleep score", None),
    SleepStatistic(
        "total_sleep", "totalSleepSecs", "Total sleep", UnitOfTime.HOURS, "duration", 1 / 3600
    ),
    SleepStatistic(
        "deep_sleep", "deepSleepSecs", "Deep sleep", UnitOfTime.HOURS, "duration", 1 / 3600
    ),
    SleepStatistic(
        "light_sleep", "lightSleepSecs", "Light sleep", UnitOfTime.HOURS, "duration", 1 / 3600
    ),
    SleepStatistic(
        "rem_sleep", "remSleepSecs", "REM sleep", UnitOfTime.HOURS, "duration", 1 / 3600
    ),
    SleepStatistic(
        "awake_time", "totalAwakeSecs", "Awake time", UnitOfTime.HOURS, "duration", 1 / 3600
    ),
    SleepStatistic("sleep_efficiency", "sleepEfficiency", "Sleep efficiency", PERCENTAGE),
    SleepStatistic("wakeups", "wakeups", "Wake-ups", None),
    SleepStatistic("heart_rate", "hrAverage", "Average heart rate", "bpm"),
    SleepStatistic("respiration_rate", "rrAverage", "Average respiration rate", "br/min"),
    SleepStatistic("hrv_rmssd", "hrvRmssdMean", "HRV (RMSSD)", UnitOfTime.MILLISECONDS, "duration"),
    SleepStatistic("hrv_sdnn", "hrvSdnnMean", "HRV (SDNN)", UnitOfTime.MILLISECONDS, "duration"),
)


def statistic_id(entry: ConfigEntry, key: str) -> str:
    """Return the external statistic ID for one metric of one account."""
    account = slugify(entry.unique_id or entry.entry_id)
    return f"{DOMAIN}:{account}_{key}"


def build_statistics(
    entry: ConfigEntry, summaries: list[dict[str, Any]], device_name: str
) -> list[tuple[StatisticMetaData, list[StatisticData]]]:
    """Turn sleep summaries into (metadata, rows) pairs, one pair per metric."""
    result = []
    for stat in SLEEP_STATISTICS:
        rows: dict[datetime, StatisticData] = {}
        for summary in summaries:
            value = summary.get(stat.field)
            end = summary.get("endTimeUtcSecs")
            if value is None or not end:
                continue
            start = datetime.fromtimestamp(end, UTC).replace(minute=0, second=0, microsecond=0)
            scaled = round(float(value) * stat.scale, 3)
            # Two recordings ending in the same hour: the later one wins.
            rows[start] = StatisticData(start=start, mean=scaled, min=scaled, max=scaled)
        if not rows:
            continue
        metadata = StatisticMetaData(
            mean_type=StatisticMeanType.ARITHMETIC,
            has_sum=False,
            name=f"{device_name} {stat.name.lower()}",
            source=DOMAIN,
            statistic_id=statistic_id(entry, stat.key),
            unit_class=stat.unit_class,
            unit_of_measurement=stat.unit,
        )
        result.append((metadata, [rows[k] for k in sorted(rows)]))
    return result


async def async_import_sleep_statistics(
    hass: HomeAssistant,
    entry: ConfigEntry,
    summaries: list[dict[str, Any]],
    device_name: str,
) -> None:
    """Write every night's metrics to the recorder."""
    if "recorder" not in hass.config.components:
        return
    for metadata, rows in build_statistics(entry, summaries, device_name):
        async_add_external_statistics(hass, metadata, rows)
    _LOGGER.debug("Imported %d nights of Sleeptracker statistics", len(summaries))
