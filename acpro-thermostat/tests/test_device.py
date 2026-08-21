"""Tests for discovery, binding and column probing, against a simulated control."""

from __future__ import annotations

import json
import socket
from typing import Any

import pytest

from acpro_thermostat import device as device_module
from acpro_thermostat import protocol
from acpro_thermostat.device import AcProDevice, DeviceError, DeviceInfo

MAC = "502cc6aabbcc"
DEVICE_KEY = "St8Vw1Yz4Bc7Ted6"


class FakeControl:
    """A stand-in for the panel: answers the same datagrams over a fake socket."""

    def __init__(
        self,
        *,
        version: int = 1,
        supported: dict[str, int] | None = None,
        strict: bool = True,
    ) -> None:
        self.version = version
        self.supported = supported or {"Pow": 1, "Mod": 1, "SetTem": 22}
        # A strict control drops any request naming a column it does not have;
        # a lax one answers with the columns it knows and omits the rest.
        self.strict = strict
        self.bound = False
        self.requests: list[dict[str, Any]] = []

    def _cipher(self, envelope: dict[str, Any]) -> protocol.Cipher:
        if envelope.get("i") == 1 or not self.bound:
            return protocol.generic_cipher(self.version)
        return protocol.make_cipher(DEVICE_KEY, self.version)

    def handle(self, datagram: bytes) -> bytes | None:
        envelope = protocol.parse_envelope(datagram)
        if envelope.get("t") == "scan":
            return self._reply(protocol.generic_cipher(self.version), self._scan_pack())

        cipher = self._cipher(envelope)
        request = cipher.decrypt(envelope["pack"], envelope.get("tag"))
        self.requests.append(request)

        if request.get("t") == "bind":
            self.bound = True
            return self._reply(
                protocol.generic_cipher(self.version),
                {"t": "bindok", "mac": MAC, "key": DEVICE_KEY},
            )

        device_cipher = protocol.make_cipher(DEVICE_KEY, self.version)
        if request.get("t") == "status":
            return self._status(device_cipher, request["cols"])
        if request.get("t") == "cmd":
            return self._command(device_cipher, request)
        return None

    def _status(self, cipher: protocol.Cipher, columns: list[str]) -> bytes | None:
        unknown = [name for name in columns if name not in self.supported]
        if unknown and self.strict:
            return None
        known = [name for name in columns if name in self.supported]
        return self._reply(
            cipher,
            {"t": "dat", "mac": MAC, "cols": known, "dat": [self.supported[c] for c in known]},
        )

    def _command(self, cipher: protocol.Cipher, request: dict[str, Any]) -> bytes:
        accepted = [name for name in request["opt"] if name in self.supported]
        for name, value in zip(request["opt"], request["p"]):
            if name in self.supported:
                self.supported[name] = value
        return self._reply(
            cipher,
            {
                "t": "res",
                "mac": MAC,
                "opt": accepted,
                "val": [self.supported[name] for name in accepted],
            },
        )

    def _scan_pack(self) -> dict[str, Any]:
        return {
            "t": "dev",
            "mac": MAC,
            "name": "Hallway",
            "brand": "acpro",
            "model": "WK-010WD1",
            "ver": "V1.2.1",
        }

    @staticmethod
    def _reply(cipher: protocol.Cipher, pack: dict[str, Any]) -> bytes:
        encoded, tag = cipher.encrypt(pack)
        envelope: dict[str, Any] = {"t": "pack", "i": 1, "uid": 0, "cid": MAC, "pack": encoded}
        if tag is not None:
            envelope["tag"] = tag
        return json.dumps(envelope).encode()


class FakeTransport:
    """Implements the bits of :class:`Transport` the code under test uses."""

    def __init__(self, control: FakeControl, *, host: str = "192.168.1.50") -> None:
        self.control = control
        self.host = host
        self._inbox: list[tuple[bytes, tuple[str, int]]] = []

    def send(self, datagram: bytes, address: tuple[str, int]) -> None:
        reply = self.control.handle(datagram)
        if reply is not None:
            self._inbox.append((reply, (self.host, address[1])))

    def collect(self, _duration: float):
        while self._inbox:
            yield self._inbox.pop(0)

    def request(self, datagram: bytes, address: tuple[str, int], *, retries: int = 3):
        reply = self.control.handle(datagram)
        if reply is None:
            raise DeviceError(f"No usable reply from {address[0]}:{address[1]}")
        return protocol.parse_envelope(reply)

    def close(self) -> None:
        pass


@pytest.fixture(name="control")
def control_fixture() -> FakeControl:
    return FakeControl(
        supported={
            "Pow": 1,
            "Mod": 1,
            "SetTem": 22,
            "TemUn": 0,
            "TemRec": 0,
            "WdSpd": 0,
            "TemSen": 61,
            "Lig": 1,
        }
    )


def _bound(control: FakeControl) -> AcProDevice:
    transport = FakeTransport(control)
    info = device_module.discover(transport, targets=["255.255.255.255"])[0]
    return device_module.bind(transport, info)


@pytest.mark.parametrize("version", [1, 2])
def test_discovery_detects_the_encryption_scheme(version: int) -> None:
    control = FakeControl(version=version)

    found = device_module.discover(FakeTransport(control), targets=["255.255.255.255"])

    assert len(found) == 1
    assert found[0].mac == MAC
    assert found[0].name == "Hallway"
    assert found[0].model == "WK-010WD1"
    assert found[0].host == "192.168.1.50"
    assert found[0].encryption_version == version


def test_discovery_returns_nothing_when_no_control_answers() -> None:
    class Silent(FakeTransport):
        def send(self, datagram: bytes, address: tuple[str, int]) -> None:
            pass

    assert device_module.discover(Silent(FakeControl()), targets=["255.255.255.255"]) == []


def test_binding_yields_a_working_per_device_key(control: FakeControl) -> None:
    device = _bound(control)

    assert device.key == DEVICE_KEY
    assert device.refresh(["Pow"]) == {"Pow": 1}


def test_binding_failure_is_reported() -> None:
    class Refusing(FakeControl):
        def handle(self, datagram: bytes) -> bytes | None:
            envelope = protocol.parse_envelope(datagram)
            if envelope.get("t") == "scan":
                return super().handle(datagram)
            return self._reply(protocol.generic_cipher(self.version), {"t": "bindfail"})

    control = Refusing()
    transport = FakeTransport(control)
    info = device_module.discover(transport, targets=["255.255.255.255"])[0]

    with pytest.raises(DeviceError, match="refused binding"):
        device_module.bind(transport, info)


def test_probe_keeps_only_the_columns_the_control_answers(control: FakeControl) -> None:
    device = _bound(control)

    supported = device.probe()

    assert supported == ["Pow", "Mod", "SetTem", "TemUn", "TemRec", "WdSpd", "TemSen", "Lig"]
    assert "SwUpDn" not in supported
    assert "Health" not in supported


def test_probe_works_when_the_control_answers_partially() -> None:
    """Firmware that ignores unknown columns instead of dropping the request."""
    control = FakeControl(
        supported={"Pow": 1, "Mod": 1, "SetTem": 22, "TemSen": 61}, strict=False
    )
    device = _bound(control)

    assert device.probe() == ["Pow", "Mod", "SetTem", "TemSen"]


def test_probe_reports_a_control_missing_the_essentials() -> None:
    control = FakeControl(supported={"Lig": 1})
    device = _bound(control)

    with pytest.raises(DeviceError, match="required properties"):
        device.probe()


def test_probe_honours_the_ignore_list(control: FakeControl) -> None:
    device = _bound(control)

    assert "Lig" not in device.probe(ignore=["Lig"])


def test_probe_populates_the_initial_state(control: FakeControl) -> None:
    device = _bound(control)
    device.probe()

    assert device.state["SetTem"] == 22
    assert device.state["TemSen"] == 61


def test_apply_writes_and_folds_in_the_acknowledgement(control: FakeControl) -> None:
    device = _bound(control)
    device.probe()

    state = device.apply({"SetTem": 24, "Mod": 4})

    assert state["SetTem"] == 24
    assert state["Mod"] == 4
    assert control.supported["SetTem"] == 24


def test_apply_with_nothing_to_write_is_a_no_op(control: FakeControl) -> None:
    device = _bound(control)
    device.probe()
    before = len(control.requests)

    device.apply({})

    assert len(control.requests) == before


def test_refresh_with_no_probed_columns_stays_quiet(control: FakeControl) -> None:
    device = _bound(control)
    before = len(control.requests)

    assert device.refresh() == {}
    assert len(control.requests) == before


def test_zip_columns_drops_values_that_are_not_numbers() -> None:
    paired = device_module._zip_columns(
        ["Pow", "Mod", "SetTem", "Bogus"], [1, None, 22.0, "nope"]
    )

    assert paired == {"Pow": 1, "SetTem": 22}


def test_zip_columns_tolerates_a_short_reply() -> None:
    assert device_module._zip_columns(["Pow", "Mod"], [1]) == {"Pow": 1}


def test_zip_columns_ignores_a_malformed_reply() -> None:
    assert device_module._zip_columns("Pow", [1]) == {}
    assert device_module._zip_columns(["Pow"], None) == {}


def test_display_name_falls_back_to_the_mac() -> None:
    info = DeviceInfo(mac=MAC, host="192.168.1.50", port=7000)

    assert info.display_name == "AC Pro aabbcc"


def test_transport_request_gives_up_after_retries() -> None:
    class DeadTransport(device_module.Transport):
        def __init__(self) -> None:
            self.attempts = 0
            self._timeout = 0.01
            self._socket = self

        def sendto(self, *_args: Any) -> None:
            self.attempts += 1

        def recvfrom(self, _size: int) -> tuple[bytes, tuple[str, int]]:
            raise socket.timeout("no reply")

        def settimeout(self, _timeout: float) -> None:
            pass

    transport = DeadTransport()

    with pytest.raises(DeviceError, match="No usable reply"):
        transport.request(b"{}", ("192.168.1.50", 7000), retries=2)

    assert transport.attempts == 2


def test_probe_ignores_duplicates_from_extra_properties(control: FakeControl) -> None:
    """extra_properties may name a column the add-on already knows about."""
    device = _bound(control)

    supported = device.probe(("Pow", "Mod", "SetTem", "Pow", "Lig"))

    assert supported == ["Pow", "Mod", "SetTem", "Lig"]


def test_probe_uses_fewer_retries_than_a_normal_read(control: FakeControl) -> None:
    """A control silently drops requests it cannot answer, so retrying is waste."""
    seen: list[int] = []
    device = _bound(control)
    original = device.transport.request

    def record(datagram: bytes, address: tuple[str, int], *, retries: int = 3):
        seen.append(retries)
        return original(datagram, address, retries=retries)

    device.transport.request = record
    device.probe(("Pow", "Mod", "SetTem"))
    probe_retries = list(seen)
    seen.clear()
    device.refresh()

    assert probe_retries == [device_module.PROBE_RETRIES]
    assert seen == [device_module.DEFAULT_RETRIES]
