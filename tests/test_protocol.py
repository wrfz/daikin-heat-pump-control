"""Unit tests of the bridge data format (no Home Assistant)."""

import json

import pytest

from custom_components.daikin_heat_pump_control.bridge.client import normalize_mac
from custom_components.daikin_heat_pump_control.bridge.protocol import (
    BridgeProtocolError,
    CanFrame,
    EspClock,
    parse_bridge_info,
    parse_can_exchange,
    parse_uart_exchange,
)
from custom_components.daikin_heat_pump_control.const import Bus

import helpers  # noqa: F401  # sets up the import path


def _json(value: object) -> bytes:
    return json.dumps(value).encode()


def test_can_frame_roundtrip() -> None:
    """Frames are written and read in the `<id>#<data>` notation."""
    frame = CanFrame(can_id=0x680, data=bytes.fromhex("3100FAC0FC0000"))
    assert frame.encode() == "680#3100FAC0FC0000"
    assert CanFrame.decode("680#3100fac0fc0000") == frame
    assert CanFrame(can_id=0x10A, data=b"").encode() == "10A#"


@pytest.mark.parametrize(
    "text", ["680", "XYZ#00", "680#0", "800#00", "680#" + "00" * 9]
)
def test_can_frame_invalid(text: str) -> None:
    """Invalid frames are rejected."""
    with pytest.raises(BridgeProtocolError):
        CanFrame.decode(text)


def test_parse_can_exchange() -> None:
    """The CAN exchange answer is parsed."""
    result = parse_can_exchange(
        _json(
            {
                "now": 1000,
                "rx": [[990, 0x180, "D200FAC0FC012C"]],
                "tx": [[700, 0x680, "3100FAC0FC0000"]],
                "pending": 1,
                "overflows": 2,
                "dropped": 3,
                "more": True,
            }
        )
    )
    assert result.now == 1000
    assert result.received[0].timestamp == 990
    assert result.received[0].frame == CanFrame(
        can_id=0x180, data=bytes.fromhex("D200FAC0FC012C")
    )
    assert result.sent[0].frame.can_id == 0x680
    assert (result.pending, result.overflows, result.dropped) == (1, 2, 3)
    assert result.more
    minimal = parse_can_exchange(_json({"now": 5}))
    assert minimal.received == ()
    assert (minimal.pending, minimal.overflows, minimal.dropped) == (0, 0, 0)


@pytest.mark.parametrize(
    "data",
    [
        b"not json",
        _json([1, 2]),
        _json({}),
        _json({"now": "1"}),
        _json({"now": True}),
        _json({"now": 1, "rx": {}}),
        _json({"now": 1, "rx": [[1, 2]]}),
        _json({"now": 1, "rx": [[1, 0x180, "XY"]]}),
        _json({"now": 1, "pending": "x"}),
    ],
)
def test_parse_can_exchange_invalid(data: bytes) -> None:
    """Malformed answers raise BridgeProtocolError."""
    with pytest.raises(BridgeProtocolError):
        parse_can_exchange(data)


def test_parse_uart_exchange() -> None:
    """The UART exchange answer is parsed."""
    result = parse_uart_exchange(
        _json({"now": 50, "rx_t": 40, "rx": "4061", "tx_t": 10, "overflows": 1})
    )
    assert result.received == bytes((0x40, 0x61))
    assert result.received_at == 40
    assert result.sent_at == 10
    assert result.overflows == 1
    empty = parse_uart_exchange(_json({"now": 50, "rx": "", "rx_t": 1}))
    assert empty.received == b""
    assert empty.received_at is None
    with pytest.raises(BridgeProtocolError):
        parse_uart_exchange(_json({"now": 50, "rx": "4"}))
    with pytest.raises(BridgeProtocolError):
        parse_uart_exchange(_json({"now": 50, "rx": 4}))


def test_parse_bridge_info() -> None:
    """Bridge info is parsed; unknown buses are ignored."""
    info = parse_bridge_info(
        _json(
            {
                "bridge": "1.0.0",
                "esphome": "2026.11.0",
                "buses": ["can", "uart", "spi"],
                "uptime": 12,
                "heap_free": 1,
                "heap_max_block": 2,
                "reset_reason": "Software",
                "wifi": {"rssi": -50, "ssid": "x", "ip": "1.2.3.4"},
                "can": {"buffer": 256, "overflows": 0, "state": "bus_off"},
                "uart": {"buffer": 1024, "overflows": 4},
            }
        )
    )
    assert info.buses == frozenset({Bus.CAN, Bus.UART})
    assert info.can is not None
    assert info.can.state == "bus_off"
    assert info.can.tx_errors is None
    assert info.uart is not None
    assert info.uart.overflows == 4
    assert info.wifi_rssi == -50
    minimal = parse_bridge_info(_json({}))
    assert minimal.buses == frozenset()
    assert minimal.can is None
    assert minimal.wifi_ip is None
    for bad in ({"buses": "can"}, {"wifi": []}, {"bridge": 1}):
        with pytest.raises(BridgeProtocolError):
            parse_bridge_info(_json(bad))


def test_esp_clock_wraps() -> None:
    """Timestamps continue across the 32-bit wrap-around."""
    clock = EspClock()
    assert clock.extend(4_294_967_000) == 4_294_967_000
    assert clock.extend(100) == (1 << 32) + 100
    # A slightly older timestamp from before the wrap stays in the old epoch.
    assert clock.extend(4_294_967_100) == 4_294_967_100
    # A slightly older timestamp in the same epoch.
    assert clock.extend(50) == (1 << 32) + 50
    assert clock.extend(200) == (1 << 32) + 200
    clock.reset()
    assert clock.extend(5) == 5


@pytest.mark.parametrize(
    ("mac", "expected"),
    [
        ("AA:BB:CC:DD:EE:FF", "aa:bb:cc:dd:ee:ff"),
        ("aabbccddeeff", "aa:bb:cc:dd:ee:ff"),
        ("AA-BB-CC-DD-EE-FF", "aa:bb:cc:dd:ee:ff"),
        ("bad", "bad"),
    ],
)
def test_normalize_mac(mac: str, expected: str) -> None:
    """MAC addresses are normalized."""
    assert normalize_mac(mac) == expected
