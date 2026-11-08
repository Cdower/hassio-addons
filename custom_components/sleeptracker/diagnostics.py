"""Diagnostics for Sleeptracker."""

from __future__ import annotations

from dataclasses import asdict
from typing import TYPE_CHECKING, Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from . import SleeptrackerConfigEntry

TO_REDACT = {
    CONF_EMAIL,
    CONF_PASSWORD,
    "macAddress",
    "mac_address",
    "macOfRemoteAp",
    "SSIDBase64",
    # The hello payload's Wi-Fi block: network name and LAN addresses.
    "essid",
    "essid_b64",
    "ip",
    "gw",
    "Serial",
    "serial",
    "mfgSerial",
    "processorSerialNumber",
    "powerBaseSerialNumber",
    "boardSerialNumber",
    "userID",
    "userFirstName",
    "title",
    "unique_id",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: SleeptrackerConfigEntry
) -> dict[str, Any]:
    """Return the bed data and a summary of the sleep data, with identifiers removed."""
    runtime = entry.runtime_data
    sleep = runtime.sleep.data or []
    latest = dict(sleep[-1]) if sleep else None
    if latest:
        # Keep the shape of the timeline but not hundreds of rows.
        for key in ("sleepSummaryCardios", "sleepSummarySpans", "sleepEvents"):
            if key in latest:
                latest[key] = f"<{len(latest[key])} items>"
        latest.pop("environment", None)
    return async_redact_data(
        {
            "entry": {"data": dict(entry.data), "options": dict(entry.options)},
            "beds": {str(pid): asdict(c.data) for pid, c in runtime.beds.items()},
            "sleep": {"nights": len(sleep), "latest": latest},
        },
        TO_REDACT,
    )
