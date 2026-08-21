"""Discovery, binding and state exchange with the AC Pro communicating control."""

from __future__ import annotations

import logging
import socket
import time
from dataclasses import dataclass, field
from collections.abc import Iterable, Sequence
from typing import Any

from . import protocol
from .const import CANDIDATE_PROPERTIES, REQUIRED_PROPERTIES
from .protocol import Cipher, ProtocolError

_LOGGER = logging.getLogger(__name__)

#: How many times a request is retried before it is treated as lost.  UDP on a
#: busy Wi-Fi segment drops the occasional datagram and the control has no
#: retransmit of its own.
DEFAULT_RETRIES = 3

#: Retries used while probing.  A control that does not support a column stays
#: silent however often it is asked, so retrying only makes start-up slower.
PROBE_RETRIES = 1


class DeviceError(Exception):
    """Raised when the control cannot be reached or refuses a request."""


@dataclass(frozen=True)
class DeviceInfo:
    """Identity of a control as reported in its discovery response."""

    mac: str
    host: str
    port: int
    name: str = ""
    brand: str = ""
    model: str = ""
    firmware: str = ""
    encryption_version: int = 1

    @property
    def display_name(self) -> str:
        """A human-friendly name, falling back to the MAC when the control has none."""
        return self.name or f"AC Pro {self.mac[-6:]}"


class Transport:
    """A UDP socket that speaks request/response with one or more controls."""

    def __init__(self, *, timeout: float = 2.0, bind_host: str = "0.0.0.0") -> None:
        self._timeout = timeout
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self._socket.settimeout(timeout)
        self._socket.bind((bind_host, 0))

    def close(self) -> None:
        self._socket.close()

    def __enter__(self) -> Transport:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def send(self, datagram: bytes, address: tuple[str, int]) -> None:
        self._socket.sendto(datagram, address)

    def collect(self, duration: float) -> Iterable[tuple[bytes, tuple[str, int]]]:
        """Yield every datagram that arrives within ``duration`` seconds."""
        deadline = time.monotonic() + duration
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            self._socket.settimeout(remaining)
            try:
                yield self._socket.recvfrom(4096)
            except socket.timeout:
                return
            finally:
                self._socket.settimeout(self._timeout)

    def request(
        self,
        datagram: bytes,
        address: tuple[str, int],
        *,
        retries: int = DEFAULT_RETRIES,
    ) -> dict[str, Any]:
        """Send ``datagram`` and return the first well-formed envelope back."""
        last_error: Exception | None = None
        for attempt in range(1, retries + 1):
            try:
                self._socket.sendto(datagram, address)
                raw, _sender = self._socket.recvfrom(4096)
                return protocol.parse_envelope(raw)
            except (socket.timeout, OSError, ProtocolError) as err:
                last_error = err
                _LOGGER.debug(
                    "Request to %s:%s failed (attempt %s/%s): %s",
                    address[0],
                    address[1],
                    attempt,
                    retries,
                    err,
                )
        raise DeviceError(f"No usable reply from {address[0]}:{address[1]}: {last_error}")


def discover(
    transport: Transport,
    *,
    targets: Sequence[str],
    port: int = protocol.DEFAULT_PORT,
    duration: float = 3.0,
) -> list[DeviceInfo]:
    """Probe ``targets`` (broadcast or unicast addresses) and return what answers."""
    for target in targets:
        try:
            transport.send(protocol.SCAN_DATAGRAM, (target, port))
        except OSError as err:
            _LOGGER.warning("Could not send discovery probe to %s: %s", target, err)

    ciphers = {version: protocol.generic_cipher(version) for version in (1, 2)}
    found: dict[str, DeviceInfo] = {}

    for raw, sender in transport.collect(duration):
        try:
            envelope = protocol.parse_envelope(raw)
            pack, version = protocol.decrypt_any(envelope, ciphers)
        except ProtocolError as err:
            _LOGGER.debug("Ignoring undecodable reply from %s: %s", sender[0], err)
            continue

        mac = str(pack.get("mac") or envelope.get("cid") or "").strip()
        if not mac:
            _LOGGER.debug("Ignoring reply from %s with no MAC", sender[0])
            continue

        found[mac] = DeviceInfo(
            mac=mac,
            host=sender[0],
            port=sender[1],
            name=str(pack.get("name") or ""),
            brand=str(pack.get("brand") or ""),
            model=str(pack.get("model") or ""),
            firmware=str(pack.get("ver") or ""),
            encryption_version=version,
        )
        _LOGGER.debug("Discovered %s at %s (encryption v%s)", mac, sender[0], version)

    return sorted(found.values(), key=lambda info: info.mac)


@dataclass
class AcProDevice:
    """A bound control, and the last state read from it."""

    info: DeviceInfo
    cipher: Cipher
    transport: Transport
    key: str
    properties: list[str] = field(default_factory=list)
    state: dict[str, int] = field(default_factory=dict)

    @property
    def address(self) -> tuple[str, int]:
        return (self.info.host, self.info.port)

    def _exchange(
        self,
        payload: dict[str, Any],
        *,
        retries: int = DEFAULT_RETRIES,
    ) -> dict[str, Any]:
        datagram = protocol.build_datagram(self.cipher, payload, tcid=self.info.mac)
        envelope = self.transport.request(datagram, self.address, retries=retries)
        try:
            return self.cipher.decrypt(envelope.get("pack", ""), envelope.get("tag"))
        except ProtocolError as err:
            raise DeviceError(f"Could not decrypt reply from {self.info.mac}: {err}") from err

    def refresh(self, properties: Sequence[str] | None = None) -> dict[str, int]:
        """Read ``properties`` (default: everything probed) and update :attr:`state`."""
        wanted = list(properties if properties is not None else self.properties)
        if not wanted:
            return dict(self.state)

        pack = self._exchange({"cols": wanted, "mac": self.info.mac, "t": "status"})
        self.state.update(_zip_columns(pack.get("cols", wanted), pack.get("dat", [])))
        return dict(self.state)

    def apply(self, values: dict[str, int]) -> dict[str, int]:
        """Write ``values`` to the control and fold the acknowledgement into state."""
        if not values:
            return dict(self.state)

        columns = list(values)
        pack = self._exchange({"opt": columns, "p": [values[c] for c in columns], "t": "cmd"})

        acknowledged = pack.get("val", pack.get("p", []))
        self.state.update(_zip_columns(pack.get("opt", columns), acknowledged))
        # The control echoes only what it accepted; anything it silently
        # dropped is picked up by the next poll rather than assumed applied.
        return dict(self.state)

    def probe(
        self,
        candidates: Sequence[str] = CANDIDATE_PROPERTIES,
        *,
        ignore: Iterable[str] = (),
    ) -> list[str]:
        """Work out which columns this control actually answers to.

        Requesting an unknown column makes some firmware revisions drop the
        whole request, so a batch that fails is split and retried until the
        offending column is isolated.
        """
        ignored = set(ignore)
        # dict.fromkeys keeps the caller's order while dropping duplicates that
        # extra_properties may have reintroduced.
        wanted = [name for name in dict.fromkeys(candidates) if name not in ignored]
        supported = self._probe_batch(wanted)

        missing = [name for name in REQUIRED_PROPERTIES if name not in supported]
        if missing:
            raise DeviceError(
                f"Control {self.info.mac} did not report the required properties: "
                f"{', '.join(missing)}"
            )

        self.properties = [name for name in wanted if name in supported]
        _LOGGER.info(
            "Control %s supports %s of %s known properties: %s",
            self.info.mac,
            len(self.properties),
            len(wanted),
            ", ".join(self.properties),
        )
        return list(self.properties)

    def _probe_batch(self, names: Sequence[str]) -> set[str]:
        if not names:
            return set()
        try:
            pack = self._exchange(
                {"cols": list(names), "mac": self.info.mac, "t": "status"},
                retries=PROBE_RETRIES,
            )
        except DeviceError:
            if len(names) == 1:
                _LOGGER.debug("Control %s rejects property %s", self.info.mac, names[0])
                return set()
            middle = len(names) // 2
            return self._probe_batch(names[:middle]) | self._probe_batch(names[middle:])

        answered = _zip_columns(pack.get("cols", list(names)), pack.get("dat", []))
        self.state.update(answered)
        return set(answered)


def _zip_columns(columns: Any, values: Any) -> dict[str, int]:
    """Pair a ``cols``/``dat`` response, dropping anything that is not a number.

    Some firmware answers an unknown column with ``null`` instead of leaving it
    out, and a short ``dat`` list means the tail was not answered at all.
    """
    if not isinstance(columns, list) or not isinstance(values, list):
        return {}

    return {
        name: int(value)
        for name, value in zip(columns, values)
        if isinstance(name, str) and isinstance(value, (bool, int, float))
    }


def bind(transport: Transport, info: DeviceInfo) -> AcProDevice:
    """Perform the binding handshake and return a device using the issued key."""
    generic = protocol.generic_cipher(info.encryption_version)
    datagram = protocol.build_datagram(
        generic,
        {"mac": info.mac, "t": "bind", "uid": 0},
        tcid=info.mac,
        i=1,
    )
    envelope = transport.request(datagram, (info.host, info.port))

    try:
        pack = generic.decrypt(envelope.get("pack", ""), envelope.get("tag"))
    except ProtocolError as err:
        raise DeviceError(f"Could not decrypt binding reply from {info.mac}: {err}") from err

    if pack.get("t") != "bindok" or not pack.get("key"):
        raise DeviceError(f"Control {info.mac} refused binding: {pack}")

    key = str(pack["key"])
    _LOGGER.info("Bound to control %s at %s", info.mac, info.host)
    return AcProDevice(
        info=info,
        cipher=protocol.make_cipher(key, info.encryption_version),
        transport=transport,
        key=key,
    )


def attach(transport: Transport, info: DeviceInfo, key: str) -> AcProDevice:
    """Build a device from a key issued by an earlier binding."""
    return AcProDevice(
        info=info,
        cipher=protocol.make_cipher(key, info.encryption_version),
        transport=transport,
        key=key,
    )
