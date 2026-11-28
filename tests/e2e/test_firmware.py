"""End-to-end tests of the real bridge firmware on the ESPHome host platform.

The firmware is built from the real packages; CAN runs over UDP and UART over
a pseudo terminal to the Python simulator. Run with `pytest -m e2e`; needs an
ESPHome installation (`ESPHOME` points to the executable).
"""

import asyncio
from collections.abc import AsyncGenerator, Generator
import json
import os
from pathlib import Path
import shutil
import subprocess
import tty
from typing import Any

from aioesphomeapi import APIClient, UserService
import pytest

from custom_components.daikin_heat_pump_control.bridge.client import (
    Firmware,
    async_probe,
)
from custom_components.daikin_heat_pump_control.const import Bus

from sim.heat_pump import HeatPump, SimCanFrame

pytestmark = pytest.mark.e2e

REPO = Path(__file__).resolve().parents[2]
ESPHOME = Path(os.environ.get("ESPHOME", "/tmp/opencode/esphome-venv/bin/esphome"))
BUILD_DIR = Path(os.environ.get("DHPC_E2E_BUILD", "/tmp/opencode/dhpc-e2e-build"))
UART_LINK = Path("/tmp/dhpc-e2e-uart")
API_PORT = 16053
CAN_PORT = 16054
API_KEY = "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8="
MAC = "02:00:00:da:1c:01"
CLIENT = "e2e-a"
OTHER = "e2e-b"


@pytest.fixture(scope="session")
def firmware() -> Path:
    """Build the host firmware (incremental) and return the program."""
    if not ESPHOME.exists():
        pytest.skip(f"ESPHome not found at {ESPHOME}")
    for folder in ("esphome", "tests/e2e"):
        target = BUILD_DIR / folder
        target.mkdir(parents=True, exist_ok=True)
        shutil.copytree(
            REPO / folder,
            target,
            dirs_exist_ok=True,
            ignore=shutil.ignore_patterns(".esphome", "__pycache__", "*.py[co]"),
        )
    workdir = BUILD_DIR / "tests" / "e2e"
    subprocess.run(
        [str(ESPHOME), "compile", "daikin-host-bridge.yaml"],
        cwd=workdir,
        check=True,
        capture_output=True,
    )
    program = workdir / ".esphome/build/daikin-host/.pioenvs/daikin-host/program"
    assert program.exists()
    return program


class CanEndpoint(asyncio.DatagramProtocol):
    """UDP side of the simulated CAN bus."""

    def __init__(self, heat_pump: HeatPump) -> None:
        """Initialize."""
        self.heat_pump = heat_pump
        self.transport: asyncio.DatagramTransport | None = None
        self.peer: Any = None
        self.received: list[SimCanFrame] = []
        self.event = asyncio.Event()

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        """Store the transport."""
        assert isinstance(transport, asyncio.DatagramTransport)
        self.transport = transport

    def datagram_received(self, data: bytes, addr: Any) -> None:
        """Answer frames sent by the bridge."""
        self.peer = addr
        text = data.decode()
        if "#" not in text:
            return
        can_id, _, payload = text.partition("#")
        frame = SimCanFrame(int(can_id, 16), bytes.fromhex(payload))
        self.received.append(frame)
        self.event.set()
        for answer in self.heat_pump.handle_can(frame):
            self.send(answer)

    def send(self, frame: SimCanFrame) -> None:
        """Put a frame on the bus towards the bridge."""
        assert self.transport is not None
        self.transport.sendto(
            f"{frame.can_id:03X}#{frame.data.hex().upper()}".encode(), self.peer
        )


class UartEndpoint:
    """Pseudo terminal side of the simulated indoor unit."""

    def __init__(self, heat_pump: HeatPump) -> None:
        """Open the pseudo terminal and link it."""
        self.heat_pump = heat_pump
        self.master, self.slave = os.openpty()
        # Keep the slave open so the master does not report EIO before the
        # firmware opens the port; raw mode avoids echo and line editing.
        tty.setraw(self.slave)
        self.slave_name = os.ttyname(self.slave)
        os.set_blocking(self.master, False)
        if UART_LINK.is_symlink() or UART_LINK.exists():
            UART_LINK.unlink()
        UART_LINK.symlink_to(self.slave_name)
        self.buffer = b""
        self.requests: list[bytes] = []

    def on_readable(self) -> None:
        """Answer complete requests."""
        try:
            self.buffer += os.read(self.master, 256)
        except BlockingIOError:
            return
        while len(self.buffer) >= 4 and self.buffer[0] == 0x03:
            request, self.buffer = self.buffer[:4], self.buffer[4:]
            self.requests.append(request)
            os.write(self.master, self.heat_pump.handle_uart(request))

    def close(self) -> None:
        """Close and unlink."""
        os.close(self.master)
        os.close(self.slave)
        UART_LINK.unlink(missing_ok=True)


@pytest.fixture
def heat_pump() -> HeatPump:
    """Return the simulated heat pump."""
    hp = HeatPump()
    hp.set_can(0x180, (0xFA, 0xC0, 0xFC), bytes((0x01, 0x2C)))
    hp.set_can(0x180, (0x28,), bytes((0x01, 0x22)))
    hp.uart_registers[0x61] = bytes(range(12))
    return hp


@pytest.fixture
async def node(
    firmware: Path, heat_pump: HeatPump, socket_enabled: None
) -> AsyncGenerator[tuple[CanEndpoint, UartEndpoint]]:
    """Start the simulator endpoints and the firmware."""
    loop = asyncio.get_running_loop()
    _, can = await loop.create_datagram_endpoint(
        lambda: CanEndpoint(heat_pump), local_addr=("127.0.0.1", CAN_PORT)
    )
    uart = UartEndpoint(heat_pump)
    loop.add_reader(uart.master, uart.on_readable)
    process = await asyncio.create_subprocess_exec(
        str(firmware), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
    )
    assert process.stdout is not None
    log: list[str] = []
    async with asyncio.timeout(20):
        while True:
            line = (await process.stdout.readline()).decode(errors="replace")
            log.append(line)
            if not line:
                pytest.fail("".join(log))
            if "setup() finished successfully" in line:
                break

    async def _drain() -> None:
        assert process.stdout is not None
        while await process.stdout.readline():
            pass

    drain = asyncio.ensure_future(_drain())
    try:
        yield can, uart
    finally:
        process.terminate()
        await process.wait()
        drain.cancel()
        loop.remove_reader(uart.master)
        uart.close()
        if can.transport is not None:
            can.transport.close()


async def _client() -> tuple[APIClient, dict[str, UserService]]:
    client = APIClient("127.0.0.1", API_PORT, None, noise_psk=API_KEY)
    await client.connect(login=True)
    _, services = await client.list_entities_services()
    return client, {s.name: s for s in services}


async def _call(api: APIClient, service: UserService, **data: Any) -> dict[str, Any]:
    response = await api.execute_service(service, data, return_response=True)
    assert response is not None
    assert response.success, response.error_message
    return json.loads(response.response_data)


async def test_probe_and_info(node: tuple[CanEndpoint, UartEndpoint]) -> None:
    """The integration recognises the firmware; info reports both buses."""
    identity = await async_probe("127.0.0.1", API_PORT, API_KEY, expected_mac=MAC)
    assert identity.firmware is Firmware.BRIDGE
    assert identity.buses == {Bus.CAN, Bus.UART}
    assert identity.project_name == "wrfz.daikin_can_uart_bridge"
    assert identity.info is not None
    assert identity.info.can is not None
    assert identity.info.can.buffer == 256
    assert identity.info.uart is not None
    assert identity.info.uart.buffer == 1024
    assert identity.info.bridge_version == "2.0.0"
    # Set by the component, not by the YAML.
    assert identity.project_version == "2.0.0"


async def test_can_exchange_and_quiet_time(
    node: tuple[CanEndpoint, UartEndpoint],
) -> None:
    """Frames are sent, answers buffered, and sends wait for 250 ms bus quiet."""
    can, _ = node
    client, services = await _client()
    try:
        exchange = services["daikin_can_exchange"]
        first = await _call(
            client,
            exchange,
            client=CLIENT,
            frames=["680#3100FAC0FC0000", "680#31002800000000", "bad"],
        )
        assert first["dropped"] == 1
        assert first["master"]
        async with asyncio.timeout(5):
            while len(can.received) < 2:
                can.event.clear()
                await can.event.wait()
        rx: list[list[Any]] = []
        tx: list[list[Any]] = list(first["tx"])
        async with asyncio.timeout(5):
            while len(rx) < 2:
                result = await _call(client, exchange, client=CLIENT, frames=[])
                rx += result["rx"]
                tx += result["tx"]
        assert [f[2] for f in rx] == ["D200FAC0FC012C", "D2002801220000"]
        assert [f[1] for f in rx] == [0x180, 0x180]
        assert [f[2] for f in tx] == ["3100FAC0FC0000", "31002800000000"]
        # Second frame only after 250 ms without traffic since the first answer.
        assert tx[1][0] - rx[0][0] >= 250
    finally:
        await client.disconnect()


async def test_can_buffer_overflow(node: tuple[CanEndpoint, UartEndpoint]) -> None:
    """Frames from other participants beyond the buffer size are counted."""
    can, _ = node
    client, services = await _client()
    try:
        exchange = services["daikin_can_exchange"]
        await _call(client, exchange, client=CLIENT, frames=["680#3100FAC0FC0000"])
        await _call(client, exchange, client=OTHER, frames=[])
        async with asyncio.timeout(5):
            while not can.received:
                can.event.clear()
                await can.event.wait()
        await _call(client, exchange, client=CLIENT, frames=[])
        for i in range(300):
            can.send(SimCanFrame(0x10A, bytes((0x30, 0, 0x28, 0, i & 0xFF, 0, 0))))
        # The other client reads along until the last frame arrived.
        last = "30002800" + f"{299 & 0xFF:02X}" + "0000"
        seen: list[str] = []
        async with asyncio.timeout(10):
            while not seen or seen[-1] != last:
                result = await _call(client, exchange, client=OTHER, frames=[])
                seen += [frame[2] for frame in result["rx"]]
        rx: list[list[Any]] = []
        more = True
        while more:
            result = await _call(client, exchange, client=CLIENT, frames=[])
            assert len(result["rx"]) <= 100
            rx += result["rx"]
            more = result["more"]
        assert result["overflows"] >= 300 - 256
        assert len(rx) == 256
        assert rx[-1][2] == last
    finally:
        await client.disconnect()


async def test_clients_and_master(node: tuple[CanEndpoint, UartEndpoint]) -> None:
    """The first client is the master; the other reads along and can take over."""
    can, _ = node
    client, services = await _client()
    try:
        exchange = services["daikin_can_exchange"]
        claim = services["daikin_bridge_claim"]
        first = await _call(client, exchange, client=CLIENT, frames=[])
        assert first["master"]
        other = await _call(
            client, exchange, client=OTHER, frames=["680#31002800000000"]
        )
        assert not other["master"]
        assert other["rejected"] == 1
        assert other["clients"] == 2
        await _call(client, exchange, client=CLIENT, frames=["680#3100FAC0FC0000"])
        rx: dict[str, list[str]] = {CLIENT: [], OTHER: []}
        async with asyncio.timeout(5):
            while len(rx[CLIENT]) < 1 or len(rx[OTHER]) < 1:
                for name in rx:
                    result = await _call(client, exchange, client=name, frames=[])
                    rx[name] += [frame[2] for frame in result["rx"]]
        assert rx[CLIENT] == rx[OTHER] == ["D200FAC0FC012C"]
        assert [frame.data.hex().upper() for frame in can.received] == [
            "3100FAC0FC0000"
        ]

        claimed = await _call(client, claim, client=OTHER)
        assert claimed == {"master": True, "clients": 2, "rejected": 1}
        result = await _call(
            client, exchange, client=CLIENT, frames=["680#3100FAC0FC0000"]
        )
        assert not result["master"]
        assert result["rejected"] == 1

        # Without calls of the master the remaining client becomes the master.
        async with asyncio.timeout(10):
            while not (await _call(client, exchange, client=CLIENT, frames=[]))[
                "master"
            ]:
                pass
        info = await _call(client, services["daikin_bridge_info"])
        assert info["clients"] == 1
        assert (await _call(client, exchange, client="", frames=[])) == {
            "error": "invalid_client"
        }
        for index in range(3):
            await _call(client, exchange, client=f"extra-{index}", frames=[])
        assert (await _call(client, exchange, client="extra-3", frames=[])) == {
            "error": "too_many_clients"
        }
    finally:
        await client.disconnect()


async def test_uart_exchange(node: tuple[CanEndpoint, UartEndpoint]) -> None:
    """A UART request is written and the answer collected with its timestamp."""
    _, uart = node
    client, services = await _client()
    try:
        exchange = services["daikin_uart_exchange"]
        await _call(client, exchange, client=CLIENT, data="")
        await _call(client, exchange, client=OTHER, data="")
        sent = await _call(client, exchange, client=CLIENT, data="0340615B")
        assert "tx_t" in sent
        pieces: dict[str, list[list[Any]]] = {CLIENT: [], OTHER: []}
        async with asyncio.timeout(5):
            while any(
                len("".join(piece[1] for piece in got)) < 32 for got in pieces.values()
            ):
                for name, got in pieces.items():
                    result = await _call(client, exchange, client=name, data="")
                    got += result["rx"]
        for got in pieces.values():
            assert "".join(piece[1] for piece in got) == (
                "40610E000102030405060708090A0B0E"
            )
            assert got[0][2] is True
            assert all(piece[2] is False for piece in got[1:])
            assert got[0][0] >= sent["tx_t"]
        refused = await _call(client, exchange, client=OTHER, data="0340615B")
        assert refused["rejected"] == 1
        assert uart.requests == [bytes.fromhex("0340615B")]
    finally:
        await client.disconnect()


SEND_EVERY_10S = "interval:\n  - interval: 10s\n    then:\n      - {}\n"
PROJECT = '  name: daikin-host\n  project:\n    name: x.y\n    version: "9.9.9"\n'
ON_FRAME = (
    "    can_id: 0x680\n    on_frame:\n      - can_id: 0x180\n"
    "        then:\n          - logger.log: frame\n"
)


@pytest.mark.parametrize(
    ("replace", "extra", "valid"),
    [
        (None, SEND_EVERY_10S.format("canbus.send: [0x31]"), False),
        (None, SEND_EVERY_10S.format("uart.write: [0x03]"), False),
        (("    can_id: 0x680\n", ON_FRAME), "", True),
        (
            ("  name: daikin-host\n", PROJECT),
            "",
            False,
        ),
    ],
)
def test_no_other_sender(
    firmware: Path, replace: tuple[str, str] | None, extra: str, valid: bool
) -> None:
    """The configuration check rejects other senders on the bridge buses."""
    workdir = BUILD_DIR / "tests" / "e2e"
    text = (workdir / "daikin-host-bridge.yaml").read_text()
    if replace is not None:
        assert replace[0] in text
        text = text.replace(*replace)
    config = workdir / "daikin-host-check.yaml"
    config.write_text(text + extra)
    result = subprocess.run(
        [str(ESPHOME), "config", config.name],
        cwd=workdir,
        check=False,
        capture_output=True,
        text=True,
    )
    output = result.stdout + result.stderr
    assert (result.returncode == 0) is valid, output
    if not valid:
        assert (
            "nothing else may send on it" in output
            or "sets 'esphome: project:'" in output
        )


@pytest.fixture(autouse=True)
def _cleanup_link() -> Generator[None]:
    yield
    UART_LINK.unlink(missing_ok=True)
