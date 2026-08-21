"""End-to-end test over real UDP sockets against a simulated control."""

from __future__ import annotations

import socket
import threading
from typing import Iterator

import pytest

from acpro_thermostat import device as device_module
from acpro_thermostat.device import Transport
from acpro_thermostat.entities import EntityMap

from test_device import MAC, FakeControl


class ControlServer:
    """Runs :class:`FakeControl` behind a real UDP socket on the loopback."""

    def __init__(self, control: FakeControl) -> None:
        self.control = control
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._socket.bind(("127.0.0.1", 0))
        self._socket.settimeout(0.2)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)

    @property
    def port(self) -> int:
        return self._socket.getsockname()[1]

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2)
        self._socket.close()

    def _serve(self) -> None:
        while not self._stop.is_set():
            try:
                datagram, sender = self._socket.recvfrom(4096)
            except socket.timeout:
                continue
            except OSError:
                return
            reply = self.control.handle(datagram)
            if reply is not None:
                self._socket.sendto(reply, sender)


@pytest.fixture(name="server")
def server_fixture() -> Iterator[ControlServer]:
    control = FakeControl(
        version=2,
        supported={
            "Pow": 1,
            "Mod": 1,
            "SetTem": 22,
            "TemUn": 1,
            "TemRec": 1,
            "WdSpd": 0,
            "TemSen": 61,
            "StHt": 0,
        },
    )
    server = ControlServer(control)
    server.start()
    try:
        yield server
    finally:
        server.stop()


def test_discover_bind_probe_and_control_over_real_sockets(server: ControlServer) -> None:
    # A short timeout keeps the strict-control probe (which costs one
    # timeout per unsupported column) from dominating the test run.
    with Transport(timeout=0.3) as transport:
        found = device_module.discover(
            transport, targets=["127.0.0.1"], port=server.port, duration=0.6
        )
        assert [info.mac for info in found] == [MAC]
        assert found[0].encryption_version == 2

        device = device_module.bind(transport, found[0])
        properties = device.probe()

        assert properties == ["Pow", "Mod", "SetTem", "TemUn", "TemRec", "WdSpd", "TemSen", "StHt"]

        entity_map = EntityMap(device.info, properties)

        # The panel is in Fahrenheit, so a Fahrenheit setpoint must survive the
        # trip through the Celsius-plus-half-step columns and back.
        columns = entity_map.columns_for(
            f"{entity_map.command_topic}/temperature", "72", device.state
        )
        device.apply(columns)
        device.refresh()

        payload = entity_map.state_payload(device.state)
        assert payload["target_temperature"] == 72
        assert payload["temperature_unit"] == "F"
        assert payload["mode"] == "cool"

        device.apply(entity_map.columns_for(f"{entity_map.command_topic}/mode", "off", {}))
        device.refresh()

        assert entity_map.state_payload(device.state)["mode"] == "off"


def test_a_control_that_never_answers_is_reported() -> None:
    with Transport(timeout=0.2) as transport:
        # Nothing is listening on this port, so discovery comes back empty.
        assert device_module.discover(
            transport, targets=["127.0.0.1"], port=59999, duration=0.4
        ) == []
