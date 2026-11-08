"""Tests for the cloud client and the statistics import."""

from __future__ import annotations

import time

import pytest
from aiohttp import ClientSession
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
    AiohttpClientMockResponse,
)

from custom_components.sleeptracker.api import (
    API_BASE,
    AUTH_URL,
    PORTAL_BASE,
    SleeptrackerApi,
    SleeptrackerAuthError,
    SleeptrackerCommandError,
    SleeptrackerConnectionError,
    parse_sleep_zip,
)
from custom_components.sleeptracker.statistics import build_statistics

from .conftest import EMAIL, PROCESSOR_ID, SUMMARIES, load, sleep_zip

CONTROL_URL = f"{API_BASE}/processor/adjustableBaseControls"


def token_reply(token: str = "tok") -> dict:
    return {"token": token, "expirationTimeSecs": int(time.time()) + 3600, "username": EMAIL}


def make_api(hass: HomeAssistant) -> SleeptrackerApi:
    session: ClientSession = async_get_clientsession(hass)
    return SleeptrackerApi(session, EMAIL, "pw")


async def test_login_and_status(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    """Status ignores the INVALID_PRESET error the no-op command produces."""
    aioclient_mock.post(AUTH_URL, json=token_reply())
    aioclient_mock.post(CONTROL_URL, json=load("status"))
    api = make_api(hass)

    body = await api.async_get_status(PROCESSOR_ID)

    assert body["snapshots"][0]["head"]["motor"]["pulseCount"] == 6841
    _, _, sent, headers = aioclient_mock.mock_calls[-1]
    assert sent["bedControlCommand"] == 1
    assert sent["sleeptrackerProcessorID"] == PROCESSOR_ID
    assert sent["clientID"] == "sleeptracker-android-tsi"
    assert headers["Authorization"] == "Bearer tok"
    # The login used HTTP Basic with the account credentials.
    assert aioclient_mock.mock_calls[0][3]["Authorization"].startswith("Basic ")


async def test_command_error_raises(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A real command that reports an error raises, unlike status."""
    aioclient_mock.post(AUTH_URL, json=token_reply())
    aioclient_mock.post(CONTROL_URL, json=load("status"))
    with pytest.raises(SleeptrackerCommandError) as err:
        await make_api(hass).async_send_command(PROCESSOR_ID, 230)
    assert err.value.status_code == 28


async def test_relogin_after_expired_token(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A refused token triggers one fresh login and a retry."""
    api = make_api(hass)
    aioclient_mock.post(AUTH_URL, json=token_reply("old"))
    await api.async_login()

    aioclient_mock.clear_requests()
    aioclient_mock.post(AUTH_URL, json=token_reply("new"))
    calls = 0

    async def control(method, url, data):  # noqa: ANN001
        nonlocal calls
        calls += 1
        if calls == 1:
            return AiohttpClientMockResponse(method, url, status=419)
        return AiohttpClientMockResponse(method, url, json={"statusCode": 0, "body": {}})

    aioclient_mock.post(CONTROL_URL, side_effect=control)
    await api.async_send_command(PROCESSOR_ID, 230)
    assert calls == 2
    assert aioclient_mock.mock_calls[-1][3]["Authorization"] == "Bearer new"


async def test_bad_credentials(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    """A 401 from the auth server is an auth error."""
    aioclient_mock.post(AUTH_URL, status=401)
    with pytest.raises(SleeptrackerAuthError):
        await make_api(hass).async_login()


async def test_environment_keeps_valid_readings(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Only readings marked valid are returned."""
    aioclient_mock.post(AUTH_URL, json=token_reply())
    env = load("env")
    env["vocPpb"]["status"] = "invalid"
    aioclient_mock.post(f"{API_BASE}/processor/latestEnvironmentSensorData", json=env)
    readings = await make_api(hass).async_get_environment(PROCESSOR_ID)
    assert set(readings) == {"co2Ppm", "degreesCelsius", "humidityPercentage", "iaq"}


def test_parse_sleep_zip() -> None:
    """Summaries come back oldest first; in-progress nights are skipped."""
    summaries = parse_sleep_zip(sleep_zip(list(reversed(SUMMARIES))))
    assert [s["sleepSummaryDay"] for s in summaries] == ["20261105", "20261106", "20261107"]


def test_parse_sleep_zip_rejects_html() -> None:
    """A non-ZIP response (for example a login page) is a connection error."""
    with pytest.raises(SleeptrackerConnectionError):
        parse_sleep_zip(b"<html></html>")


def test_build_statistics() -> None:
    """Each metric becomes one row per night at the hour the night ended."""
    stats = {
        meta["statistic_id"]: (meta, rows)
        for meta, rows in build_statistics(SUMMARIES, "bed100001_side1", "Bedroom sleep")
    }

    meta, rows = stats["sleeptracker:bed100001_side1_sleep_score"]
    assert meta["source"] == "sleeptracker"
    assert meta["name"] == "Bedroom sleep sleep score"
    assert [r["mean"] for r in rows] == [71, 75, 80]
    assert rows[-1]["start"].isoformat() == "2026-11-07T17:00:00+00:00"

    _, rows = stats["sleeptracker:bed100001_side1_total_sleep"]
    assert rows[0]["mean"] == 7.0


async def test_portal_download(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    """The portal login carries its cookies and CSRF token into the download."""
    aioclient_mock.get(f"{PORTAL_BASE}/portal/", text="<html>", cookies={"csrf_token": "csrf1"})
    aioclient_mock.post(f"{PORTAL_BASE}/api/login", status=204, cookies={"session": "s1"})
    aioclient_mock.get(f"{PORTAL_BASE}/api/downloadAccountData", content=sleep_zip(SUMMARIES))

    summaries = await make_api(hass).async_get_sleep_summaries()

    assert len(summaries) == 3
    login = aioclient_mock.mock_calls[1]
    assert login[3]["X-CSRFToken"] == "csrf1"
    assert login[3]["Authorization"].startswith("Basic ")
    download = aioclient_mock.mock_calls[2]
    assert download[3]["X-CSRFToken"] == "csrf1"
    assert "session=s1" in download[3]["Cookie"]


async def test_portal_relogin_when_session_lapses(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A 401 on the download with stored cookies logs in again."""
    api = make_api(hass)
    api._portal_cookies = {"csrf_token": "stale", "session": "old"}
    downloads = 0

    async def download(method, url, data):  # noqa: ANN001
        nonlocal downloads
        downloads += 1
        if downloads == 1:
            return AiohttpClientMockResponse(method, url, status=401)
        return AiohttpClientMockResponse(method, url, response=sleep_zip(SUMMARIES))

    aioclient_mock.get(f"{PORTAL_BASE}/portal/", text="<html>", cookies={"csrf_token": "fresh"})
    aioclient_mock.post(f"{PORTAL_BASE}/api/login", status=204)
    aioclient_mock.get(f"{PORTAL_BASE}/api/downloadAccountData", side_effect=download)

    assert len(await api.async_get_sleep_summaries()) == 3
    assert downloads == 2
    assert aioclient_mock.mock_calls[-1][3]["X-CSRFToken"] == "fresh"


async def test_portal_bad_credentials(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A rejected portal login is an auth error."""
    aioclient_mock.get(f"{PORTAL_BASE}/portal/", text="<html>", cookies={"csrf_token": "c"})
    aioclient_mock.post(f"{PORTAL_BASE}/api/login", status=401)
    with pytest.raises(SleeptrackerAuthError):
        await make_api(hass).async_get_sleep_summaries()


async def test_payload_cannot_redirect_command(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Extra payload fields cannot change the processor or the command code."""
    aioclient_mock.post(AUTH_URL, json=token_reply())
    aioclient_mock.post(CONTROL_URL, json={"statusCode": 0, "body": {}})
    await make_api(hass).async_send_command(
        PROCESSOR_ID, 230, {"sleeptrackerProcessorID": 1, "bedControlCommand": 100, "x": 1}
    )
    sent = aioclient_mock.mock_calls[-1][2]
    assert (sent["sleeptrackerProcessorID"], sent["bedControlCommand"], sent["x"]) == (
        PROCESSOR_ID,
        230,
        1,
    )


async def test_login_419_is_auth_error(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A 419 from the auth server is reported as bad credentials, not leaked."""
    aioclient_mock.post(AUTH_URL, status=419)
    with pytest.raises(SleeptrackerAuthError):
        await make_api(hass).async_login()


async def test_refused_after_fresh_login_is_not_auth_error(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A request refused right after a successful login does not start reauth."""
    aioclient_mock.post(AUTH_URL, json=token_reply())
    aioclient_mock.post(CONTROL_URL, status=403)
    with pytest.raises(SleeptrackerConnectionError):
        await make_api(hass).async_send_command(PROCESSOR_ID, 230)
