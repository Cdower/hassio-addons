"""Async client for the Tempur-Pedic Sleeptracker-AI cloud.

The Sleeptracker G2 processor in the bed has no local API: its only open TCP
port is 5355, an LLMNR name-resolution responder, and its mDNS record
advertises port 0. Everything goes through the same cloud the Tempur
Sleeptracker app uses:

* ``auth.tsi.sleeptracker.com`` swaps the account email/password (HTTP Basic)
  for a bearer token.
* ``app.tsi.sleeptracker.com/actrack-client/v2/fpcsiot`` serves device info,
  room-environment readings, and ``adjustableBaseControls``, which relays
  commands to the bed frame and returns a status snapshot of each side.
* ``portal.tsi.sleeptracker.com`` is the account web portal. Its "download my
  data" endpoint is the only place nightly sleep summaries are available; it
  returns a ZIP with one JSON file per night.

The API is undocumented. Endpoint names, client IDs and command codes come from
the Android app as recorded by the smartbed-mqtt project and were confirmed
against a 2023 Ergo Smart base.
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import time
import zipfile
from base64 import b64encode
from typing import Any

import aiohttp

_LOGGER = logging.getLogger(__name__)

AUTH_URL = "https://auth.tsi.sleeptracker.com/v1/app/user/session"
API_BASE = "https://app.tsi.sleeptracker.com/actrack-client/v2/fpcsiot"
PORTAL_BASE = "https://portal.tsi.sleeptracker.com"

CLIENT_FIELDS = {"clientID": "sleeptracker-android-tsi", "clientVersion": "1.9.47"}

# Device types the app asks for when listing an account's hardware.
DEVICE_TYPES = [1, 2, 4, 6]

# The status command (1) is a no-op on the bed; the SmartCable answers it with
# an INVALID_PRESET error even though the snapshots in the body are valid.
STATUS_COMMAND = 1
STATUS_IGNORED_CODE = 28

REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=30)
PORTAL_TIMEOUT = aiohttp.ClientTimeout(total=180)

# Re-authenticate this many seconds before the token says it expires.
TOKEN_MARGIN_SECS = 60


class SleeptrackerError(Exception):
    """Base error for the Sleeptracker cloud."""


class SleeptrackerAuthError(SleeptrackerError):
    """The account credentials were rejected."""


class SleeptrackerConnectionError(SleeptrackerError):
    """The cloud could not be reached or answered with an HTTP error."""


class SleeptrackerCommandError(SleeptrackerError):
    """The cloud accepted the request but the bed reported an error."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(f"Sleeptracker error {status_code}: {message.strip()}")
        self.status_code = status_code
        self.message = message


def _basic(email: str, password: str) -> str:
    return "Basic " + b64encode(f"{email}:{password}".encode()).decode()


class SleeptrackerApi:
    """Client for the app API and the account portal."""

    def __init__(self, session: aiohttp.ClientSession, email: str, password: str) -> None:
        """Store the session and credentials."""
        self._session = session
        # The portal keeps its login and CSRF token in cookies. They are kept
        # per account here; the session should not store cookies itself (see
        # async_get_session in __init__.py), or two accounts would share a portal login.
        self._portal_cookies: dict[str, str] = {}
        self._email = email
        self._password = password
        self._token: str | None = None
        self._token_expires = 0.0
        self._auth_lock = asyncio.Lock()
        self._portal_lock = asyncio.Lock()
        self.username: str | None = None

    # ------------------------------------------------------------------ auth

    async def async_login(self, force: bool = False) -> None:
        """Fetch a bearer token, unless the current one is still good."""
        async with self._auth_lock:
            if not force and self._token and time.time() < self._token_expires:
                return
            data = await self._post_json(
                AUTH_URL,
                {**CLIENT_FIELDS, "id": "HA_getUserSession", "scope": "scope"},
                _basic(self._email, self._password),
                auth_request=True,
            )
            token = data.get("token")
            if not token:
                raise SleeptrackerAuthError(data.get("statusMessage") or "No token returned")
            self._token = f"Bearer {token}"
            expires = data.get("expirationTimeSecs") or 0
            # Guard against a relative lifetime or a missing value.
            if expires < time.time():
                expires = time.time() + 3600
            self._token_expires = expires - TOKEN_MARGIN_SECS
            self.username = data.get("username")

    async def _post_json(
        self, url: str, body: dict[str, Any], authorization: str, auth_request: bool = False
    ) -> dict[str, Any]:
        headers = {
            "accept": "*/*",
            "content-type": "application/json",
            "Authorization": authorization,
        }
        try:
            async with self._session.post(
                url, json=body, headers=headers, timeout=REQUEST_TIMEOUT
            ) as resp:
                if resp.status in (401, 403, 419) and auth_request:
                    raise SleeptrackerAuthError("Invalid email or password")
                if resp.status in (401, 403, 419):
                    raise _TokenExpired
                if resp.status >= 400:
                    text = await resp.text()
                    raise SleeptrackerConnectionError(f"HTTP {resp.status}: {text[:200]}")
                return await resp.json(content_type=None) or {}
        except (aiohttp.ClientError, TimeoutError) as err:
            raise SleeptrackerConnectionError(str(err) or type(err).__name__) from err

    async def _call(self, path: str, context: str, extra: dict[str, Any]) -> dict[str, Any]:
        """POST to the app API, logging in again once if the token was refused."""
        body = {**CLIENT_FIELDS, "id": f"HA_{context}", **extra}
        for attempt in range(2):
            await self.async_login(force=attempt > 0)
            assert self._token  # set by async_login  # nosec B101
            try:
                return await self._post_json(f"{API_BASE}/{path}", body, self._token)
            except _TokenExpired:
                if attempt:
                    # The login itself just succeeded, so the credentials are
                    # fine; the request is refused for another reason (for
                    # example a processor not on this account).
                    raise SleeptrackerConnectionError(
                        f"{path} refused after a fresh login"
                    ) from None
                _LOGGER.debug("Sleeptracker token refused; logging in again")
        raise AssertionError("unreachable")  # pragma: no cover

    @staticmethod
    def _check(data: dict[str, Any], ignore: tuple[int, ...] = ()) -> dict[str, Any]:
        code = data.get("statusCode", 0)
        if code not in (0, *ignore):
            raise SleeptrackerCommandError(code, str(data.get("statusMessage", "")))
        return data

    # ------------------------------------------------------------- app API

    async def async_get_devices(self) -> list[dict[str, Any]]:
        """Return the account's active Sleeptracker processors."""
        data = self._check(
            await self._call(
                "processor/getByType", "cloudIoTDevicesGetByType", {"types": DEVICE_TYPES}
            )
        )
        return [d for d in data.get("deviceList") or [] if d.get("active")]

    async def async_get_hello(self, processor_id: int) -> dict[str, Any]:
        """Return the processor's self-report: firmware, sensors, motor capabilities."""
        data = await self._call(
            "processor/command/hello",
            "cloudIoTProcessorSimpleHello",
            {"sleeptrackerProcessorID": processor_id},
        )
        hello = data.get("helloData")
        if not hello:
            raise SleeptrackerCommandError(
                data.get("statusCode", -1), str(data.get("statusMessage", "No helloData"))
            )
        return hello

    async def async_get_sensor_map(self, processor_id: int) -> list[dict[str, Any]]:
        """Return the sleep sensors (one per side) and which user owns each."""
        data = self._check(
            await self._call(
                "processor/getSensorMap",
                "cloudIoTDevicesGetSensorMap",
                {"sleeptrackerProcessorID": processor_id},
            )
        )
        return data.get("sensorMap") or []

    async def async_get_environment(self, processor_id: int) -> dict[str, Any]:
        """Return the latest room readings (temperature, humidity, CO2, VOC, IAQ)."""
        data = self._check(
            await self._call(
                "processor/latestEnvironmentSensorData",
                "environmentalData",
                {"sleeptrackerProcessorID": processor_id},
            )
        )
        return {
            key: value
            for key, value in data.items()
            if isinstance(value, dict) and value.get("status") == "valid"
        }

    async def async_send_command(
        self, processor_id: int, command: int, extra: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Send a bed-frame command and return the response body.

        The body carries ``snapshots`` (one per controller side) describing the
        frame after the command, which is also how status is read.
        """
        data = await self._call(
            "processor/adjustableBaseControls",
            "adjustableBaseControls",
            # Extra fields go first so they cannot redirect the command to
            # another processor or change the command code.
            {
                **(extra or {}),
                "sleeptrackerProcessorID": processor_id,
                "bedControlCommand": command,
            },
        )
        ignore = (STATUS_IGNORED_CODE,) if command == STATUS_COMMAND else ()
        self._check(data, ignore)
        return data.get("body") or {}

    async def async_get_status(self, processor_id: int) -> dict[str, Any]:
        """Return the bed-frame status body (snapshots, invariants, connection)."""
        return await self.async_send_command(processor_id, STATUS_COMMAND)

    async def async_get_snore_relief(self) -> dict[str, bool]:
        """Return the account's snore-relief settings."""
        data = self._check(await self._call("settings/getSnoreRelief", "getSnoreRelief", {}))
        return {
            "snoreReliefTilt": bool(data.get("snoreReliefTilt")),
            "snoreReliefVibration": bool(data.get("snoreReliefVibration")),
        }

    async def async_set_snore_relief(self, tilt: bool, vibration: bool) -> None:
        """Change the account's snore-relief settings."""
        self._check(
            await self._call(
                "settings/setSnoreRelief",
                "setSnoreRelief",
                {"snoreReliefTilt": tilt, "snoreReliefVibration": vibration},
            )
        )

    # -------------------------------------------------------------- portal

    def _portal_headers(self, **extra: str) -> dict[str, str]:
        headers = {"Referer": f"{PORTAL_BASE}/portal/", "Origin": PORTAL_BASE, **extra}
        if self._portal_cookies:
            headers["Cookie"] = "; ".join(f"{k}={v}" for k, v in self._portal_cookies.items())
        if csrf := self._portal_cookies.get("csrf_token"):
            headers["X-CSRFToken"] = csrf
        return headers

    def _keep_cookies(self, resp: aiohttp.ClientResponse) -> None:
        for name, morsel in resp.cookies.items():
            if morsel.value:
                self._portal_cookies[name] = morsel.value
            else:
                self._portal_cookies.pop(name, None)

    async def _portal_login(self) -> None:
        self._portal_cookies.clear()
        async with self._session.get(
            f"{PORTAL_BASE}/portal/", headers=self._portal_headers(), timeout=PORTAL_TIMEOUT
        ) as resp:
            if resp.status != 200:
                raise SleeptrackerConnectionError(f"Portal page returned HTTP {resp.status}")
            self._keep_cookies(resp)
            await resp.read()
        if "csrf_token" not in self._portal_cookies:
            raise SleeptrackerConnectionError("Portal did not set a CSRF cookie")
        async with self._session.post(
            f"{PORTAL_BASE}/api/login",
            json={},
            headers=self._portal_headers(Authorization=_basic(self._email, self._password)),
            timeout=PORTAL_TIMEOUT,
        ) as resp:
            if resp.status in (401, 403):
                raise SleeptrackerAuthError("Portal rejected the credentials")
            if resp.status != 204:
                raise SleeptrackerConnectionError(f"Portal login returned HTTP {resp.status}")
            self._keep_cookies(resp)

    async def _portal_download(self) -> bytes | None:
        """Return the ZIP, or None if the portal session has lapsed."""
        async with self._session.get(
            f"{PORTAL_BASE}/api/downloadAccountData",
            headers=self._portal_headers(),
            timeout=PORTAL_TIMEOUT,
        ) as resp:
            if resp.status in (401, 403):
                return None
            if resp.status != 200:
                raise SleeptrackerConnectionError(f"Data download returned HTTP {resp.status}")
            self._keep_cookies(resp)
            return await resp.read()

    async def async_download_sleep_data(self) -> bytes:
        """Download the account's data ZIP; parse it with parse_sleep_zip.

        Parsing is CPU-bound (a year of nights is about 1 MB of JSON), so
        callers in an event loop should run it in an executor.
        """
        async with self._portal_lock:
            try:
                payload = await self._portal_download() if self._portal_cookies else None
                if payload is None:
                    await self._portal_login()
                    payload = await self._portal_download()
                if payload is None:
                    raise SleeptrackerConnectionError("Portal download refused after login")
            except (aiohttp.ClientError, TimeoutError) as err:
                raise SleeptrackerConnectionError(str(err) or type(err).__name__) from err
        return payload

    async def async_get_sleep_summaries(self) -> list[dict[str, Any]]:
        """Download and parse every nightly sleep summary, oldest first."""
        return parse_sleep_zip(await self.async_download_sleep_data())


class _TokenExpired(Exception):
    """Internal signal: the bearer token was refused."""


def parse_sleep_zip(payload: bytes) -> list[dict[str, Any]]:
    """Return the ``sleepSummary`` objects in a portal data ZIP, oldest first.

    Nights without an end time (a recording still in progress) are skipped.
    """
    summaries: list[dict[str, Any]] = []
    try:
        archive = zipfile.ZipFile(io.BytesIO(payload))
    except zipfile.BadZipFile as err:
        raise SleeptrackerConnectionError("Data download was not a ZIP file") from err
    with archive:
        for name in archive.namelist():
            if "Sleep_Summary_" not in name or not name.endswith(".json"):
                continue
            try:
                raw = json.loads(archive.read(name))
            except (ValueError, KeyError):
                _LOGGER.warning("Skipping unreadable sleep summary %s", name)
                continue
            summary = raw.get("sleepSummary", raw) if isinstance(raw, dict) else None
            if isinstance(summary, dict) and summary.get("endTimeUtcSecs"):
                summaries.append(summary)
    summaries.sort(key=lambda s: s["endTimeUtcSecs"])
    return summaries
