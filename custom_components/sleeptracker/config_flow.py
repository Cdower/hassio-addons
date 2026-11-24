"""Config flow for Sleeptracker."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
    OptionsFlowWithReload,
)
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from . import async_get_session
from .api import SleeptrackerApi, SleeptrackerAuthError, SleeptrackerError
from .const import (
    CONF_BED_CONTROLS,
    CONF_SLEEP_INTERVAL,
    CONF_STATUS_INTERVAL,
    DEFAULT_SLEEP_INTERVAL,
    DEFAULT_STATUS_INTERVAL,
    DOMAIN,
    MIN_SLEEP_INTERVAL,
    MIN_STATUS_INTERVAL,
)

USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): TextSelector(
            TextSelectorConfig(type=TextSelectorType.EMAIL, autocomplete="username")
        ),
        vol.Required(CONF_PASSWORD): TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD, autocomplete="current-password")
        ),
    }
)


class SleeptrackerConfigFlow(ConfigFlow, domain=DOMAIN):
    """Log in with a Sleeptracker-AI (Tempur Sleeptracker app) account."""

    VERSION = 1

    async def _validate(self, email: str, password: str) -> dict[str, str]:
        """Return form errors; empty when the credentials work."""
        api = SleeptrackerApi(async_get_session(self.hass), email, password)
        try:
            await api.async_login()
            await api.async_get_devices()
        except SleeptrackerAuthError:
            return {"base": "invalid_auth"}
        except SleeptrackerError:
            return {"base": "cannot_connect"}
        return {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask for the account credentials."""
        errors: dict[str, str] = {}
        if user_input is not None:
            email = user_input[CONF_EMAIL].strip()
            await self.async_set_unique_id(email.lower())
            self._abort_if_unique_id_configured()
            errors = await self._validate(email, user_input[CONF_PASSWORD])
            if not errors:
                return self.async_create_entry(
                    title=email,
                    data={CONF_EMAIL: email, CONF_PASSWORD: user_input[CONF_PASSWORD]},
                )
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(USER_SCHEMA, user_input),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """Start re-authentication after the password stopped working."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the new password."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = await self._validate(entry.data[CONF_EMAIL], user_input[CONF_PASSWORD])
            if not errors:
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_PASSWORD: user_input[CONF_PASSWORD]}
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_PASSWORD): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    )
                }
            ),
            description_placeholders={"email": entry.data[CONF_EMAIL]},
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow."""
        return SleeptrackerOptionsFlow()


class SleeptrackerOptionsFlow(OptionsFlowWithReload):
    """Polling intervals and whether this account drives the bed frame."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Show the options form."""
        if user_input is not None:
            return self.async_create_entry(
                data={
                    CONF_BED_CONTROLS: user_input[CONF_BED_CONTROLS],
                    CONF_STATUS_INTERVAL: int(user_input[CONF_STATUS_INTERVAL]),
                    CONF_SLEEP_INTERVAL: int(user_input[CONF_SLEEP_INTERVAL]),
                }
            )
        options = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Required(CONF_BED_CONTROLS, default=options.get(CONF_BED_CONTROLS, True)): bool,
                vol.Required(
                    CONF_STATUS_INTERVAL,
                    default=options.get(CONF_STATUS_INTERVAL, DEFAULT_STATUS_INTERVAL),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=MIN_STATUS_INTERVAL,
                        max=3600,
                        step=1,
                        unit_of_measurement="s",
                        mode=NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(
                    CONF_SLEEP_INTERVAL,
                    default=options.get(CONF_SLEEP_INTERVAL, DEFAULT_SLEEP_INTERVAL),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=MIN_SLEEP_INTERVAL,
                        max=1440,
                        step=1,
                        unit_of_measurement="min",
                        mode=NumberSelectorMode.BOX,
                    )
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
