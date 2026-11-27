"""Tests of the simulator itself, so that the other tests can rely on it."""

from sim.bridge import CanBridge, UartBridge
from sim.heat_pump import (
    UART_NAK,
    HeatPump,
    SimCanFrame,
    can_byte0,
    can_kind,
    can_target,
    uart_checksum,
)


class Clock:
    """Manually advanced millisecond clock."""

    def __init__(self) -> None:
        """Start at 0."""
        self.now = 0

    def __call__(self) -> int:
        """Return the current time."""
        return self.now


def _heat_pump() -> HeatPump:
    hp = HeatPump()
    hp.set_can(0x180, (0xFA, 0xC0, 0xFC), bytes((0x01, 0x2C)))
    hp.set_can(0x180, (0x28,), bytes((0x01, 0x22)))
    hp.set_can(0x500, (0x61,), bytes((0x01, 0x00)))
    return hp


def test_byte0() -> None:
    """Byte 0 holds target and kind."""
    assert can_target(0x31) == 0x180
    assert can_target(0x61) == 0x300
    assert can_target(0xA1) == 0x500
    assert can_target(0xD2) == 0x680
    assert can_kind(0x30) == 0
    assert can_byte0(0x680, 2) == 0xD2


def test_uart_checksum() -> None:
    """Checksum values from the reference."""
    assert uart_checksum(bytes((0x03, 0x40, 0x10))) == 0xAC
    assert uart_checksum(bytes((0x03, 0x40, 0x61))) == 0x5B
    assert uart_checksum(bytes((0x03, 0x40, 0x20))) == 0x9C
    assert uart_checksum(b"") == 0xFF
    assert uart_checksum(bytes((0x02, 0x54))) == 0xA9


def test_can_read_short_long_and_other_responder() -> None:
    """Reads are answered by the addressed node."""
    hp = _heat_pump()
    [answer] = hp.handle_can(SimCanFrame(0x680, bytes.fromhex("3100FAC0FC0000")))
    assert answer == SimCanFrame(0x180, bytes.fromhex("D200FAC0FC012C"))
    [answer] = hp.handle_can(SimCanFrame(0x680, bytes.fromhex("31002800000000")))
    assert answer == SimCanFrame(0x180, bytes.fromhex("D2002801220000"))
    [answer] = hp.handle_can(SimCanFrame(0x680, bytes.fromhex("A1006100000000")))
    assert answer.can_id == 0x500
    assert hp.handle_can(SimCanFrame(0x680, bytes.fromhex("3100FA0000"))) == []
    assert hp.handle_can(SimCanFrame(0x680, bytes.fromhex("3100FA00000000"))) == []
    hp.can_silent.add((0x180, (0x28,)))
    assert hp.handle_can(SimCanFrame(0x680, bytes.fromhex("31002800000000"))) == []


def test_can_write_and_panel() -> None:
    """Writes change the register; the panel writes like a participant."""
    hp = _heat_pump()
    seen = []
    hp.on_can_write = lambda *args: seen.append(args)
    assert hp.handle_can(SimCanFrame(0x680, bytes.fromhex("30002801400000"))) == []
    assert hp.can_registers[(0x180, (0x28,))] == bytes((0x01, 0x40))
    assert seen == [(0x180, (0x28,), bytes((0x01, 0x40)))]
    hp.handle_can(SimCanFrame(0x680, bytes.fromhex("3000FAC0FC0102")))
    assert hp.can_registers[(0x180, (0xFA, 0xC0, 0xFC))] == bytes((0x01, 0x02))
    # Unknown registers are not created by writes.
    hp.handle_can(SimCanFrame(0x680, bytes.fromhex("30002901400000")))
    assert (0x180, (0x29,)) not in hp.can_registers
    frame = hp.panel_write((0x28,), bytes((0x01, 0x10)))
    assert frame == SimCanFrame(0x10A, bytes.fromhex("30002801100000"))
    long_frame = hp.panel_write((0xFA, 0x01, 0x12), bytes((0x05, 0x00)))
    assert long_frame.data == bytes.fromhex("3000FA01120500")


def test_can_bridge_quiet_rule() -> None:
    """A frame is sent only after 250 ms without bus traffic."""
    clock = Clock()
    bridge = CanBridge(_heat_pump(), clock)
    result = bridge.exchange(["680#3100FAC0FC0000"])
    assert result["tx"] == [[0, 0x680, "3100FAC0FC0000"]]
    assert result["rx"] == []
    clock.now = 100
    result = bridge.exchange(["680#31002800000000"])
    assert result["rx"] == [[15, 0x180, "D200FAC0FC012C"]]
    assert result["tx"] == []
    assert result["pending"] == 1
    clock.now = 300
    result = bridge.exchange([])
    # Last traffic was the answer at 15 ms: earliest send at 265 ms.
    assert result["tx"] == [[265, 0x680, "31002800000000"]]
    assert result["rx"] == [[280, 0x180, "D2002801220000"]]


def test_can_bridge_buffers() -> None:
    """Full buffers count overflows and dropped frames."""
    clock = Clock()
    bridge = CanBridge(_heat_pump(), clock, rx_capacity=2, tx_capacity=1)
    for i in range(3):
        bridge.inject(SimCanFrame(0x10A, bytes((0x31, 0, 0x28, 0, 0, 0, i))))
    result = bridge.exchange(["680#3100FAC0FC0000", "680#31002800000000"])
    assert result["dropped"] == 1
    assert result["overflows"] >= 1
    assert len(result["rx"]) == 2
    assert bridge.status()["overflows"] == result["overflows"]


def test_uart_protocol_i_and_s() -> None:
    """Requests are answered in both protocols, in chunks."""
    clock = Clock()
    hp = HeatPump()
    hp.uart_registers[0x61] = bytes(range(12))
    bridge = UartBridge(hp, clock)
    result = bridge.exchange("0340615B")
    assert result["tx_t"] == 0
    assert result["rx"] == ""
    clock.now = 45
    first = bridge.exchange("")
    assert first["rx_t"] == 40
    assert first["rx"] == "40610E00010203"
    clock.now = 100
    rest = bridge.exchange("")
    assert first["rx"] + rest["rx"] == "40610E000102030405060708090A0B0E"
    assert "rx_t" in rest

    hp.uart_protocol = "S"
    hp.uart_registers[0x54] = bytes(16)
    assert hp.handle_uart(bytes((0x02, 0x54, 0xA9))) == bytes((0x54,)) + bytes(
        16
    ) + bytes((uart_checksum(bytes((0x54,)) + bytes(16)),))
    assert hp.handle_uart(bytes((0x03, 0x40, 0x61, 0x5B))) == UART_NAK


def test_uart_faults() -> None:
    """NAK for unknown registers and bad requests; wrong checksum on demand."""
    hp = HeatPump()
    hp.uart_registers[0x10] = bytes(4)
    assert hp.handle_uart(bytes((0x03, 0x40, 0x20, 0x9C))) == UART_NAK
    assert hp.handle_uart(bytes((0x03, 0x40, 0x10, 0x00))) == UART_NAK
    assert hp.handle_uart(bytes((0x02, 0x10, 0x00, 0x00))) == UART_NAK
    good = hp.handle_uart(bytes((0x03, 0x40, 0x10, 0xAC)))
    hp.uart_bad_checksum.add(0x10)
    bad = hp.handle_uart(bytes((0x03, 0x40, 0x10, 0xAC)))
    assert good[:-1] == bad[:-1]
    assert good[-1] != bad[-1]
    hp.uart_protocol = "S"
    assert hp.handle_uart(bytes((0x03, 0x40, 0x10, 0xAC))) == UART_NAK
    bridge = UartBridge(hp, Clock(), capacity=4)
    bridge.exchange("0340109C" * 3)
    bridge.clock_ms = lambda: 1000
    result = bridge.exchange("")
    assert result["rx"] == UART_NAK.hex().upper() * 2
    assert result["overflows"] == 2
