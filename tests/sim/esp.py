"""Simulated ESP node speaking the ESPHome native API.

The server implements the server side of the native API (plaintext and
Noise_NNpsk0_25519_ChaChaPoly_SHA256) so that the integration connects with
the real aioesphomeapi client. It offers the bridge actions, the manifest
action of the previous firmware, or nothing at all.
"""

import asyncio
import base64
from collections.abc import Callable
import contextlib
from dataclasses import dataclass, field
import json
import logging
import time
from typing import Any

from aioesphomeapi import api_pb2
from aioesphomeapi.core import MESSAGE_TYPE_TO_PROTO
from google.protobuf import message
from noise.connection import NoiseConnection

from .bridge import CanBridge, UartBridge
from .heat_pump import HeatPump

_LOGGER = logging.getLogger(__name__)

PROTO_TO_TYPE = {proto: msg_type for msg_type, proto in MESSAGE_TYPE_TO_PROTO.items()}
NOISE_PROLOGUE = b"NoiseAPIInit\x00\x00"
NOISE_NAME = b"Noise_NNpsk0_25519_ChaChaPoly_SHA256"

ARG_STRING = 3
ARG_INT = 1
ARG_STRING_ARRAY = 7
SUPPORTS_RESPONSE_OPTIONAL = 1

FIRMWARE_BRIDGE = "bridge"
FIRMWARE_LEGACY_CAN = "legacy_can"
FIRMWARE_LEGACY_UART = "legacy_uart"
FIRMWARE_OTHER = "other"


def make_noise_psk(seed: int = 1) -> str:
    """Return a valid base64 API key."""
    return base64.b64encode(bytes((seed + i) % 256 for i in range(32))).decode()


def _varint(value: int) -> bytes:
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def _read_varint(buffer: bytes, pos: int) -> tuple[int, int] | None:
    result = shift = 0
    while pos < len(buffer):
        byte = buffer[pos]
        pos += 1
        result |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return result, pos
        shift += 7
    return None


@dataclass(slots=True)
class _Action:
    key: int
    name: str
    args: list[tuple[str, int]]
    handler: Callable[[dict[str, Any]], dict[str, Any]]


@dataclass(slots=True)
class Stats:
    """Counters of the simulated node."""

    connections: int = 0
    actions: dict[str, int] = field(default_factory=dict)


class _Connection:
    def __init__(
        self,
        esp: SimulatedEsp,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        self.esp = esp
        self.reader = reader
        self.writer = writer
        self.noise: NoiseConnection | None = None
        self.buffer = b""

    async def run(self) -> None:
        try:
            if self.esp.noise_psk is not None:
                if not await self._noise_handshake():
                    return
            while True:
                packet = await self._read_packet()
                if packet is None:
                    return
                msg_type, payload = packet
                if not await self._handle(msg_type, payload):
                    return
        except ConnectionError, asyncio.IncompleteReadError:
            return
        finally:
            self.writer.close()
            self.esp._connections.discard(self)

    # ------------------------------------------------------------ framing

    async def _read_exact(self, size: int) -> bytes:
        return await self.reader.readexactly(size)

    async def _read_noise_frame(self) -> bytes:
        header = await self._read_exact(3)
        if header[0] != 0x01:
            raise ConnectionError("bad noise preamble")
        return await self._read_exact((header[1] << 8) | header[2])

    def _write_noise_frame(self, payload: bytes) -> None:
        self.writer.write(
            bytes((0x01, len(payload) >> 8, len(payload) & 0xFF)) + payload
        )

    async def _noise_handshake(self) -> bool:
        hello = await self._read_noise_frame()
        if hello:
            return False
        proto = NoiseConnection.from_name(NOISE_NAME)
        proto.set_as_responder()
        proto.set_psks(base64.b64decode(self.esp.noise_psk or ""))
        proto.set_prologue(NOISE_PROLOGUE)
        proto.start_handshake()
        mac = self.esp.mac.replace(":", "").encode()
        self._write_noise_frame(
            b"\x01" + self.esp.name.encode() + b"\x00" + mac + b"\x00"
        )
        handshake = await self._read_noise_frame()
        try:
            proto.read_message(handshake[1:])
        except Exception:  # noqa: BLE001 - any failure means a wrong key
            self._write_noise_frame(b"\x01Handshake MAC failure")
            await self.writer.drain()
            return False
        self._write_noise_frame(b"\x00" + proto.write_message())
        await self.writer.drain()
        self.noise = proto
        return True

    async def _read_packet(self) -> tuple[int, bytes] | None:
        if self.noise is not None:
            frame = await self._read_noise_frame()
            data = self.noise.decrypt(frame)
            return (data[0] << 8) | data[1], data[4:]
        preamble = await self._read_exact(1)
        if preamble != b"\x00":
            return None
        length = await self._read_plain_varint()
        msg_type = await self._read_plain_varint()
        return msg_type, await self._read_exact(length) if length else b""

    async def _read_plain_varint(self) -> int:
        data = b""
        while True:
            data += await self._read_exact(1)
            if (parsed := _read_varint(data, 0)) is not None:
                return parsed[0]

    def send(self, msg: message.Message) -> None:
        msg_type = PROTO_TO_TYPE[type(msg)]
        data = msg.SerializeToString()
        if self.noise is not None:
            frame = bytes(
                (msg_type >> 8, msg_type & 0xFF, len(data) >> 8, len(data) & 0xFF)
            )
            self._write_noise_frame(self.noise.encrypt(frame + data))
        else:
            self.writer.write(b"\x00" + _varint(len(data)) + _varint(msg_type) + data)

    # ----------------------------------------------------------- messages

    async def _handle(self, msg_type: int, payload: bytes) -> bool:
        proto = MESSAGE_TYPE_TO_PROTO.get(msg_type)
        if proto is None:
            return True
        msg = proto()
        msg.ParseFromString(payload)
        esp = self.esp
        if isinstance(msg, api_pb2.HelloRequest):
            self.send(
                api_pb2.HelloResponse(
                    api_version_major=1,
                    api_version_minor=14,
                    server_info=f"{esp.name} (esphome v{esp.esphome_version})",
                    name=esp.name,
                )
            )
        elif isinstance(msg, api_pb2.DeviceInfoRequest):
            self.send(
                api_pb2.DeviceInfoResponse(
                    name=esp.name,
                    friendly_name=esp.friendly_name,
                    mac_address=esp.mac.upper(),
                    esphome_version=esp.esphome_version,
                    project_name=esp.project_name,
                    project_version=esp.project_version,
                    api_encryption_supported=esp.noise_psk is not None,
                    model="esp32-s3-devkitc-1",
                    manufacturer="Espressif",
                )
            )
        elif isinstance(msg, api_pb2.ListEntitiesRequest):
            for action in esp.actions.values():
                self.send(
                    api_pb2.ListEntitiesServicesResponse(
                        name=action.name,
                        key=action.key,
                        supports_response=SUPPORTS_RESPONSE_OPTIONAL,
                        args=[
                            api_pb2.ListEntitiesServicesArgument(
                                name=name, type=arg_type
                            )
                            for name, arg_type in action.args
                        ],
                    )
                )
            self.send(api_pb2.ListEntitiesDoneResponse())
        elif isinstance(msg, api_pb2.PingRequest):
            self.send(api_pb2.PingResponse())
        elif isinstance(msg, api_pb2.DisconnectRequest):
            self.send(api_pb2.DisconnectResponse())
            await self.writer.drain()
            return False
        elif isinstance(msg, api_pb2.ExecuteServiceRequest):
            self._execute(msg)
        await self.writer.drain()
        return True

    def _execute(self, msg: api_pb2.ExecuteServiceRequest) -> None:
        esp = self.esp
        action = next((a for a in esp.actions.values() if a.key == msg.key), None)
        if action is None:
            return
        args: dict[str, Any] = {}
        for (name, arg_type), arg in zip(action.args, msg.args, strict=False):
            if arg_type == ARG_STRING_ARRAY:
                args[name] = list(arg.string_array)
            elif arg_type == ARG_STRING:
                args[name] = arg.string_
            else:
                args[name] = arg.int_
        esp.stats.actions[action.name] = esp.stats.actions.get(action.name, 0) + 1
        if esp.action_hook is not None and not esp.action_hook(action.name, args):
            return
        if action.name in esp.fail_actions:
            self.send(
                api_pb2.ExecuteServiceResponse(
                    call_id=msg.call_id, success=False, error_message="failed"
                )
            )
            return
        result = action.handler(args)
        if not msg.return_response:
            self.send(api_pb2.ExecuteServiceResponse(call_id=msg.call_id, success=True))
            return
        self.send(
            api_pb2.ExecuteServiceResponse(
                call_id=msg.call_id,
                success=True,
                response_data=json.dumps(result, separators=(",", ":")).encode(),
            )
        )


class SimulatedEsp:
    """An ESP node with the bridge firmware, the previous firmware or none."""

    def __init__(
        self,
        *,
        name: str,
        mac: str,
        noise_psk: str | None,
        firmware: str = FIRMWARE_BRIDGE,
        heat_pump: HeatPump | None = None,
        can: bool = False,
        uart: bool = False,
        clock: Callable[[], float] = time.monotonic,
        friendly_name: str = "",
        esphome_version: str = "2026.11.0",
        bridge_version: str = "1.0.0",
    ) -> None:
        """Initialize the node."""
        self.name = name
        self.mac = mac.lower()
        self.noise_psk = noise_psk
        self.friendly_name = friendly_name
        self.firmware = firmware
        self.esphome_version = esphome_version
        self.bridge_version = bridge_version
        self.heat_pump = heat_pump or HeatPump()
        self.clock = clock
        self._boot = clock()
        self.can = CanBridge(self.heat_pump, self.clock_ms) if can else None
        self.uart = UartBridge(self.heat_pump, self.clock_ms) if uart else None
        self.stats = Stats()
        self.action_hook: Callable[[str, dict[str, Any]], bool] | None = None
        self.info_overrides: dict[str, Any] = {}
        self.fail_actions: set[str] = set()
        self.host = "127.0.0.1"
        self.port = 0
        self._server: asyncio.Server | None = None
        self._connections: set[_Connection] = set()
        self._tasks: set[asyncio.Task[None]] = set()
        self.actions = self._build_actions()

    @property
    def project_name(self) -> str:
        """Return the ESPHome project name of the firmware."""
        if self.firmware != FIRMWARE_BRIDGE:
            return "" if self.firmware == FIRMWARE_OTHER else "wrfz.daikin_rotex"
        buses = "_".join(
            bus for bus, on in (("can", self.can), ("uart", self.uart)) if on
        )
        return f"wrfz.daikin_{buses}_bridge"

    @property
    def project_version(self) -> str:
        """Return the ESPHome project version of the firmware."""
        return self.bridge_version if self.firmware == FIRMWARE_BRIDGE else ""

    def clock_ms(self) -> int:
        """Return the milliseconds since the start of the node."""
        return round((self.clock() - self._boot) * 1000)

    def reboot(self) -> None:
        """Restart the uptime counter."""
        self._boot = self.clock()

    def _build_actions(self) -> dict[str, _Action]:
        actions: list[_Action] = []
        if self.firmware == FIRMWARE_BRIDGE:
            actions.append(
                _Action(0, "daikin_bridge_info", [], lambda _: self.bridge_info())
            )
            if self.can is not None:
                can = self.can
                actions.append(
                    _Action(
                        0,
                        "daikin_can_exchange",
                        [("frames", ARG_STRING_ARRAY)],
                        lambda args: can.exchange(args["frames"]),
                    )
                )
            if self.uart is not None:
                uart = self.uart
                actions.append(
                    _Action(
                        0,
                        "daikin_uart_exchange",
                        [("data", ARG_STRING)],
                        lambda args: uart.exchange(args["data"]),
                    )
                )
        elif self.firmware == FIRMWARE_LEGACY_CAN:
            actions.append(
                _Action(
                    0, "rotex_can_manifest", [("page", ARG_INT)], lambda _: {"id": "x"}
                )
            )
        elif self.firmware == FIRMWARE_LEGACY_UART:
            actions.append(
                _Action(
                    0, "rotex_uart_manifest", [("page", ARG_INT)], lambda _: {"id": "x"}
                )
            )
        for index, action in enumerate(actions):
            action.key = 1000 + index
        return {action.name: action for action in actions}

    def set_firmware(self, firmware: str) -> None:
        """Switch the firmware; takes effect for new connections."""
        self.firmware = firmware
        self.actions = self._build_actions()

    def bridge_info(self) -> dict[str, Any]:
        """Return the answer of `daikin_bridge_info`."""
        buses = [bus for bus, on in (("can", self.can), ("uart", self.uart)) if on]
        info: dict[str, Any] = {
            "bridge": self.bridge_version,
            "esphome": self.esphome_version,
            "buses": buses,
            "uptime": self.clock_ms() // 1000,
            "heap_free": 182000,
            "heap_max_block": 110000,
            "reset_reason": "Power on",
            "wifi": {"rssi": -61, "ssid": "home", "ip": "192.168.0.50"},
        }
        if self.can is not None:
            self.can.advance()
            info["can"] = self.can.status()
        if self.uart is not None:
            info["uart"] = self.uart.status()
        info.update(self.info_overrides)
        return info

    # ------------------------------------------------------------- server

    async def start(self, port: int | None = None) -> None:
        """Start listening."""
        self._server = await asyncio.start_server(
            self._accept, self.host, port if port is not None else self.port
        )
        self.port = self._server.sockets[0].getsockname()[1]

    async def _accept(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        self.stats.connections += 1
        connection = _Connection(self, reader, writer)
        self._connections.add(connection)
        await connection.run()

    async def drop_connections(self) -> None:
        """Close all client connections, as a reboot of the node would."""
        for connection in list(self._connections):
            connection.writer.close()
            with contextlib.suppress(ConnectionError):
                await connection.writer.wait_closed()
        self._connections.clear()

    async def stop(self) -> None:
        """Stop listening and close all connections."""
        if self._server is not None:
            self._server.close()
            await self.drop_connections()
            await self._server.wait_closed()
            self._server = None
        else:
            await self.drop_connections()

    @property
    def connection_count(self) -> int:
        """Return the number of open client connections."""
        return len(self._connections)


__all__ = [
    "FIRMWARE_BRIDGE",
    "FIRMWARE_LEGACY_CAN",
    "FIRMWARE_LEGACY_UART",
    "FIRMWARE_OTHER",
    "SimulatedEsp",
    "make_noise_psk",
]
