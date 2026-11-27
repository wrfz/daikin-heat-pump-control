"""Data format of the bridge actions.

The bridge firmware answers its actions with a JSON document in the action
response. Timestamps are milliseconds since the start of the ESP as an unsigned
32-bit counter that wraps around after about 49 days.
"""

from dataclasses import dataclass, field
import json
from typing import Any

from ..const import Bus

TIMESTAMP_MODULO = 1 << 32
CAN_MAX_ID = 0x7FF
CAN_MAX_DATA = 8


class BridgeProtocolError(ValueError):
    """Raised when a bridge response does not have the expected format."""


class BridgeClientError(BridgeProtocolError):
    """Raised when the bridge does not serve this client."""

    def __init__(self, code: str) -> None:
        """Initialize with the error code of the bridge."""
        super().__init__(f"Bridge refused the client: {code}")
        self.code = code


@dataclass(frozen=True, slots=True, kw_only=True)
class CanFrame:
    """A classic CAN frame with an 11-bit identifier."""

    can_id: int
    data: bytes

    def __post_init__(self) -> None:
        """Validate identifier and length."""
        if not 0 <= self.can_id <= CAN_MAX_ID:
            raise BridgeProtocolError(f"Invalid CAN id {self.can_id:#x}")
        if len(self.data) > CAN_MAX_DATA:
            raise BridgeProtocolError(f"CAN frame too long: {len(self.data)} bytes")

    def encode(self) -> str:
        """Return the frame in the `<id hex>#<data hex>` notation."""
        return f"{self.can_id:03X}#{self.data.hex().upper()}"

    @classmethod
    def decode(cls, text: str) -> CanFrame:
        """Parse the `<id hex>#<data hex>` notation."""
        can_id, sep, data = text.partition("#")
        if not sep:
            raise BridgeProtocolError(f"Invalid CAN frame {text!r}")
        try:
            return cls(can_id=int(can_id, 16), data=bytes.fromhex(data))
        except ValueError as err:
            raise BridgeProtocolError(f"Invalid CAN frame {text!r}") from err


@dataclass(frozen=True, slots=True, kw_only=True)
class TimedCanFrame:
    """A CAN frame with the ESP timestamp of its reception or transmission."""

    timestamp: int
    frame: CanFrame


@dataclass(frozen=True, slots=True, kw_only=True)
class ClientStatus:
    """What the bridge reports about the calling client."""

    master: bool = True
    clients: int = 1
    rejected: int = 0


@dataclass(frozen=True, slots=True, kw_only=True)
class CanExchangeResult:
    """Answer of `daikin_can_exchange`."""

    now: int
    received: tuple[TimedCanFrame, ...]
    sent: tuple[TimedCanFrame, ...]
    pending: int
    overflows: int
    dropped: int
    more: bool = False
    client: ClientStatus = field(default_factory=ClientStatus)


@dataclass(frozen=True, slots=True, kw_only=True)
class UartPiece:
    """Received UART bytes; `fresh` bytes start the answer to a new request."""

    timestamp: int
    data: bytes
    fresh: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class UartExchangeResult:
    """Answer of `daikin_uart_exchange`."""

    now: int
    pieces: tuple[UartPiece, ...]
    sent_at: int | None
    overflows: int
    more: bool = False
    client: ClientStatus = field(default_factory=ClientStatus)


@dataclass(frozen=True, slots=True, kw_only=True)
class CanStatus:
    """CAN controller status reported by the bridge."""

    buffer: int
    state: str
    tx_errors: int | None
    rx_errors: int | None
    arbitration_lost: int | None
    bus_off: int | None


@dataclass(frozen=True, slots=True, kw_only=True)
class UartStatus:
    """UART buffer status reported by the bridge."""

    buffer: int


@dataclass(frozen=True, slots=True, kw_only=True)
class BridgeInfo:
    """Answer of `daikin_bridge_info`."""

    bridge_version: str
    esphome_version: str
    buses: frozenset[Bus]
    uptime: int
    heap_free: int | None
    heap_max_block: int | None
    reset_reason: str | None
    wifi_rssi: int | None
    wifi_ssid: str | None
    wifi_ip: str | None
    clients: int | None = None
    can: CanStatus | None = None
    uart: UartStatus | None = None
    raw: dict[str, Any] = field(default_factory=dict, compare=False)


def _load(data: bytes) -> dict[str, Any]:
    try:
        value = json.loads(data)
    except ValueError as err:
        raise BridgeProtocolError("Response is not valid JSON") from err
    if not isinstance(value, dict):
        raise BridgeProtocolError("Response is not a JSON object")
    if isinstance(error := value.get("error"), str):
        raise BridgeClientError(error)
    return value


def _client(obj: dict[str, Any]) -> ClientStatus:
    return ClientStatus(
        master=obj.get("master") is True,
        clients=_opt_int(obj, "clients") or 0,
        rejected=_opt_int(obj, "rejected") or 0,
    )


def _int(obj: dict[str, Any], key: str) -> int:
    value = obj.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise BridgeProtocolError(f"Field {key!r} is missing or not an integer")
    return value


def _opt_int(obj: dict[str, Any], key: str) -> int | None:
    value = obj.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise BridgeProtocolError(f"Field {key!r} is not an integer")
    return value


def _opt_str(obj: dict[str, Any], key: str) -> str | None:
    value = obj.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise BridgeProtocolError(f"Field {key!r} is not a string")
    return value


def _obj(obj: dict[str, Any], key: str) -> dict[str, Any] | None:
    value = obj.get(key)
    if value is None:
        return None
    if not isinstance(value, dict):
        raise BridgeProtocolError(f"Field {key!r} is not an object")
    return value


def _timed_frames(obj: dict[str, Any], key: str) -> tuple[TimedCanFrame, ...]:
    items = obj.get(key, [])
    if not isinstance(items, list):
        raise BridgeProtocolError(f"Field {key!r} is not a list")
    frames: list[TimedCanFrame] = []
    for item in items:
        if (
            not isinstance(item, list)
            or len(item) != 3
            or not isinstance(item[0], int)
            or not isinstance(item[1], int)
            or not isinstance(item[2], str)
        ):
            raise BridgeProtocolError(f"Invalid frame entry {item!r}")
        try:
            data = bytes.fromhex(item[2])
        except ValueError as err:
            raise BridgeProtocolError(f"Invalid frame data {item[2]!r}") from err
        frames.append(
            TimedCanFrame(timestamp=item[0], frame=CanFrame(can_id=item[1], data=data))
        )
    return tuple(frames)


def parse_can_exchange(data: bytes) -> CanExchangeResult:
    """Parse the response of `daikin_can_exchange`."""
    obj = _load(data)
    return CanExchangeResult(
        now=_int(obj, "now"),
        received=_timed_frames(obj, "rx"),
        sent=_timed_frames(obj, "tx"),
        pending=_opt_int(obj, "pending") or 0,
        overflows=_opt_int(obj, "overflows") or 0,
        dropped=_opt_int(obj, "dropped") or 0,
        more=obj.get("more") is True,
        client=_client(obj),
    )


def _uart_pieces(obj: dict[str, Any]) -> tuple[UartPiece, ...]:
    items = obj.get("rx", [])
    if not isinstance(items, list):
        raise BridgeProtocolError("Field 'rx' is not a list")
    pieces: list[UartPiece] = []
    for item in items:
        if (
            not isinstance(item, list)
            or len(item) != 3
            or isinstance(item[0], bool)
            or not isinstance(item[0], int)
            or not isinstance(item[1], str)
            or not isinstance(item[2], bool)
        ):
            raise BridgeProtocolError(f"Invalid UART entry {item!r}")
        try:
            data = bytes.fromhex(item[1])
        except ValueError as err:
            raise BridgeProtocolError(f"Invalid UART data {item[1]!r}") from err
        pieces.append(UartPiece(timestamp=item[0], data=data, fresh=item[2]))
    return tuple(pieces)


def parse_uart_exchange(data: bytes) -> UartExchangeResult:
    """Parse the response of `daikin_uart_exchange`."""
    obj = _load(data)
    return UartExchangeResult(
        now=_int(obj, "now"),
        pieces=_uart_pieces(obj),
        sent_at=_opt_int(obj, "tx_t"),
        overflows=_opt_int(obj, "overflows") or 0,
        more=obj.get("more") is True,
        client=_client(obj),
    )


def parse_claim(data: bytes) -> ClientStatus:
    """Parse the response of `daikin_bridge_claim`."""
    return _client(_load(data))


def parse_bridge_info(data: bytes) -> BridgeInfo:
    """Parse the response of `daikin_bridge_info`."""
    obj = _load(data)
    buses_raw = obj.get("buses", [])
    if not isinstance(buses_raw, list):
        raise BridgeProtocolError("Field 'buses' is not a list")
    buses = frozenset(Bus(bus) for bus in buses_raw if bus in tuple(Bus))
    wifi = _obj(obj, "wifi") or {}
    can_obj = _obj(obj, "can")
    uart_obj = _obj(obj, "uart")
    can = None
    if can_obj is not None:
        can = CanStatus(
            buffer=_opt_int(can_obj, "buffer") or 0,
            state=_opt_str(can_obj, "state") or "unknown",
            tx_errors=_opt_int(can_obj, "tx_errors"),
            rx_errors=_opt_int(can_obj, "rx_errors"),
            arbitration_lost=_opt_int(can_obj, "arbitration_lost"),
            bus_off=_opt_int(can_obj, "bus_off"),
        )
    uart = None
    if uart_obj is not None:
        uart = UartStatus(buffer=_opt_int(uart_obj, "buffer") or 0)
    return BridgeInfo(
        bridge_version=_opt_str(obj, "bridge") or "",
        esphome_version=_opt_str(obj, "esphome") or "",
        buses=buses,
        uptime=_opt_int(obj, "uptime") or 0,
        heap_free=_opt_int(obj, "heap_free"),
        heap_max_block=_opt_int(obj, "heap_max_block"),
        reset_reason=_opt_str(obj, "reset_reason"),
        wifi_rssi=_opt_int(wifi, "rssi"),
        wifi_ssid=_opt_str(wifi, "ssid"),
        wifi_ip=_opt_str(wifi, "ip"),
        clients=_opt_int(obj, "clients"),
        can=can,
        uart=uart,
        raw=obj,
    )


class EspClock:
    """Extend the wrapping 32-bit ESP timestamps to a monotonic counter.

    Timestamps must be fed roughly in order; a step back of more than half the
    counter range is taken as a wrap-around.
    """

    def __init__(self) -> None:
        """Initialize the clock."""
        self._epoch = 0
        self._last: int | None = None

    def reset(self) -> None:
        """Forget the history, e.g. after the ESP restarted."""
        self._epoch = 0
        self._last = None

    def extend(self, timestamp: int) -> int:
        """Return the extended value of a raw ESP timestamp in ms."""
        timestamp %= TIMESTAMP_MODULO
        if self._last is not None:
            delta = (timestamp - self._last) % TIMESTAMP_MODULO
            if delta < TIMESTAMP_MODULO // 2:
                if timestamp < self._last:
                    self._epoch += TIMESTAMP_MODULO
                self._last = timestamp
            else:
                # Older than the latest one; keep it in the current or previous epoch.
                epoch = (
                    self._epoch - TIMESTAMP_MODULO
                    if timestamp > self._last
                    else self._epoch
                )
                return epoch + timestamp
        else:
            self._last = timestamp
        return self._epoch + timestamp
