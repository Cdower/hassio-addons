"""The Tempur-Pedic Sleeptracker integration."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

import voluptuous as vol
from aiohttp import ClientSession, DummyCookieJar
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, Platform
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    ConfigEntryNotReady,
    ServiceValidationError,
)
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.typing import ConfigType

from .api import SleeptrackerApi, SleeptrackerAuthError, SleeptrackerError
from .const import (
    ATTR_COMMAND,
    ATTR_CONFIG_ENTRY,
    ATTR_PAYLOAD,
    ATTR_PROCESSOR_ID,
    CONF_BED_CONTROLS,
    CONF_SLEEP_INTERVAL,
    CONF_STATUS_INTERVAL,
    DEFAULT_SLEEP_INTERVAL,
    DEFAULT_STATUS_INTERVAL,
    DOMAIN,
    MANUFACTURER,
    SERVICE_SEND_COMMAND,
)
from .coordinator import SleeptrackerBedCoordinator, SleeptrackerSleepCoordinator
from .entity import bed_device_info
from .statistics import async_import_sleep_statistics

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.COVER,
    Platform.LIGHT,
    Platform.SENSOR,
    Platform.SWITCH,
]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

SEND_COMMAND_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_CONFIG_ENTRY): cv.string,
        vol.Optional(ATTR_PROCESSOR_ID): vol.Coerce(int),
        vol.Required(ATTR_COMMAND): vol.All(vol.Coerce(int), vol.Range(min=0, max=9999)),
        vol.Optional(ATTR_PAYLOAD, default={}): dict,
    }
)


DATA_SESSION = f"{DOMAIN}_session"


@callback
def async_get_session(hass: HomeAssistant) -> ClientSession:
    """Return the integration's HTTP session, creating it on first use.

    It ignores cookies: the API keeps each account's portal cookies itself,
    so two accounts never share a login. Home Assistant closes it at shutdown.
    """
    if (session := hass.data.get(DATA_SESSION)) is None:
        session = hass.data[DATA_SESSION] = async_create_clientsession(
            hass, cookie_jar=DummyCookieJar()
        )
    return session


@dataclass
class SleeptrackerRuntimeData:
    """Objects shared by the platforms of one config entry."""

    api: SleeptrackerApi
    sleep: SleeptrackerSleepCoordinator
    sleep_device: DeviceInfo
    beds: dict[int, SleeptrackerBedCoordinator] = field(default_factory=dict)


type SleeptrackerConfigEntry = ConfigEntry[SleeptrackerRuntimeData]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the integration's services."""

    async def send_command(call: ServiceCall) -> ServiceResponse:
        entry = hass.config_entries.async_get_entry(call.data[ATTR_CONFIG_ENTRY])
        if entry is None or entry.domain != DOMAIN or entry.state is not ConfigEntryState.LOADED:
            raise ServiceValidationError("Unknown or unloaded Sleeptracker config entry")
        beds = entry.runtime_data.beds
        if not beds:
            raise ServiceValidationError("This Sleeptracker account has no bed controls loaded")
        pid = call.data.get(ATTR_PROCESSOR_ID)
        if pid is None:
            if len(beds) > 1:
                raise ServiceValidationError("Account has several beds; set processor_id")
            coordinator = next(iter(beds.values()))
        elif (coordinator := beds.get(pid)) is None:
            raise ServiceValidationError(f"No bed with processor_id {pid}")
        body = await coordinator.async_command(
            call.data[ATTR_COMMAND], call.data[ATTR_PAYLOAD], follow=True
        )
        return {"response": body}

    hass.services.async_register(
        DOMAIN,
        SERVICE_SEND_COMMAND,
        send_command,
        schema=SEND_COMMAND_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    return True


def _link_to_first_bed(
    hass: HomeAssistant,
    entry: SleeptrackerConfigEntry,
    beds: dict[int, SleeptrackerBedCoordinator],
) -> dict[str, Any]:
    """Return the device info fields that place the sleep device under the bed.

    Only an entry with bed controls creates the bed device, and the registry
    rejects a link to a device that does not exist, so without beds there is
    no link. Home Assistant 2026.8 replaced the `via_device` identifier with
    `via_device_id`, the bed's registry ID, so the bed device is registered
    here to get one; older releases still take the identifier.
    """
    if not beds:
        return {}
    first = next(iter(beds.values()))
    if "via_device_id" not in getattr(DeviceInfo, "__annotations__", {}):
        return {"via_device": (DOMAIN, str(first.processor_id))}
    bed_device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id, **bed_device_info(first.data)
    )
    return {"via_device_id": bed_device.id}


async def async_setup_entry(hass: HomeAssistant, entry: SleeptrackerConfigEntry) -> bool:
    """Log in, discover the account's beds and start polling."""
    api = SleeptrackerApi(
        async_get_session(hass), entry.data[CONF_EMAIL], entry.data[CONF_PASSWORD]
    )
    try:
        await api.async_login()
        devices = await api.async_get_devices()
    except SleeptrackerAuthError as err:
        raise ConfigEntryAuthFailed(str(err)) from err
    except SleeptrackerError as err:
        raise ConfigEntryNotReady(str(err)) from err

    options = entry.options
    status_interval = timedelta(seconds=options.get(CONF_STATUS_INTERVAL, DEFAULT_STATUS_INTERVAL))
    sleep_interval = timedelta(minutes=options.get(CONF_SLEEP_INTERVAL, DEFAULT_SLEEP_INTERVAL))

    beds: dict[int, SleeptrackerBedCoordinator] = {}
    if options.get(CONF_BED_CONTROLS, True):
        for device in devices:
            coordinator = SleeptrackerBedCoordinator(hass, entry, api, device, status_interval)
            await coordinator.async_config_entry_first_refresh()
            beds[coordinator.processor_id] = coordinator

    runtime = SleeptrackerRuntimeData(
        api=api,
        sleep=SleeptrackerSleepCoordinator(hass, entry, api, sleep_interval),
        sleep_device=DeviceInfo(
            identifiers={(DOMAIN, f"sleep_{entry.unique_id or entry.entry_id}")},
            name=f"Sleeptracker sleep ({entry.title})",
            manufacturer=MANUFACTURER,
            model="Sleeptracker-AI sleep data",
            **_link_to_first_bed(hass, entry, beds),
        ),
        beds=beds,
    )
    entry.runtime_data = runtime

    @callback
    def _import_statistics() -> None:
        if runtime.sleep.data:
            entry.async_create_background_task(
                hass,
                async_import_sleep_statistics(hass, entry, runtime.sleep.data),
                "sleeptracker statistics import",
            )

    entry.async_on_unload(runtime.sleep.async_add_listener(_import_statistics))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # The portal download is slow (one login plus a ~1 MB ZIP) and only feeds
    # the sleep sensors, so it runs after the bed controls are up rather than
    # holding up setup. Sleep sensors are unavailable until it finishes.
    entry.async_create_background_task(
        hass, runtime.sleep.async_refresh(), "sleeptracker first sleep download"
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: SleeptrackerConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
