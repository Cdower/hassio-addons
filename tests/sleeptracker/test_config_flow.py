"""Config and options flow tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sleeptracker.api import (
    SleeptrackerAuthError,
    SleeptrackerConnectionError,
)
from custom_components.sleeptracker.const import DOMAIN

from .conftest import EMAIL, FakeApi

API = "custom_components.sleeptracker.config_flow.SleeptrackerApi"
CREDS = {"email": f"  {EMAIL.upper()} ", "password": "pw"}  # pragma: allowlist secret


async def test_user_flow_creates_entry(hass: HomeAssistant) -> None:
    """Valid credentials create an entry keyed by the lower-cased email."""
    with (
        patch(API, return_value=FakeApi()),
        patch("custom_components.sleeptracker.async_setup_entry", return_value=True),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(result["flow_id"], CREDS)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].unique_id == EMAIL
    assert result["data"] == {"email": EMAIL.upper(), "password": "pw"}


@pytest.mark.parametrize(
    ("error", "key"),
    [
        (SleeptrackerAuthError("bad"), "invalid_auth"),
        (SleeptrackerConnectionError("down"), "cannot_connect"),
    ],
)
async def test_user_flow_errors(hass: HomeAssistant, error: Exception, key: str) -> None:
    """Login failures are shown on the form."""
    api = FakeApi()
    api.async_login = AsyncMock(side_effect=error)
    with patch(API, return_value=api):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(result["flow_id"], CREDS)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": key}


async def test_duplicate_account_aborts(hass: HomeAssistant, config_entry: MockConfigEntry) -> None:
    """The same account cannot be added twice."""
    config_entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], CREDS)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth_updates_password(hass: HomeAssistant, config_entry: MockConfigEntry) -> None:
    """Re-authentication stores the new password."""
    config_entry.add_to_hass(hass)
    with (
        patch(API, return_value=FakeApi()),
        patch("custom_components.sleeptracker.async_setup_entry", return_value=True),
    ):
        result = await config_entry.start_reauth_flow(hass)
        assert result["step_id"] == "reauth_confirm"
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"password": "new"}
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert config_entry.data["password"] == "new"  # pragma: allowlist secret


async def test_options_flow(
    hass: HomeAssistant, mock_api: FakeApi, config_entry: MockConfigEntry
) -> None:
    """Options are saved as integers and reload the entry."""
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert hass.states.async_entity_ids("light")

    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {"bed_controls": False, "status_interval": 30.0, "sleep_interval": 120.0},
    )
    await hass.async_block_till_done(wait_background_tasks=True)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert config_entry.options == {
        "bed_controls": False,
        "status_interval": 30,
        "sleep_interval": 120,
    }
    # The reload drops the bed's entities once bed controls are off.
    assert config_entry.state is config_entries.ConfigEntryState.LOADED
    assert all(
        hass.states.get(entity_id).state == "unavailable"
        for entity_id in hass.states.async_entity_ids("light")
    )
