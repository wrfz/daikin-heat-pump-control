"""Simulated heat pump with RoCon controller (CAN) and indoor unit (UART).

The simulator only models what the bus partners answer. CAN registers are
keyed by the answering node and the register address; UART registers by their
register byte. Tests set values and inject faults directly.
"""

from collections.abc import Callable
from dataclasses import dataclass, field

CAN_OWN_ID = 0x680
CAN_PANEL_ID = 0x10A
CAN_LONG_REGISTER = 0xFA

KIND_WRITE = 0
KIND_READ = 1
KIND_ANSWER = 2

UART_NAK = bytes((0x15, 0xEA))


def can_target(byte0: int) -> int:
    """Return the CAN id addressed by byte 0 of a frame."""
    return (byte0 >> 4) * 0x80


def can_kind(byte0: int) -> int:
    """Return the kind (write, read, answer) encoded in byte 0."""
    return byte0 & 0x0F


def can_byte0(target: int, kind: int) -> int:
    """Return byte 0 for a frame to `target` of the given kind."""
    return ((target // 0x80) << 4) | kind


def can_register(data: bytes) -> tuple[int, ...]:
    """Return the register address of a frame (short or long)."""
    if data[2] == CAN_LONG_REGISTER:
        return (CAN_LONG_REGISTER, data[3], data[4])
    return (data[2],)


def uart_checksum(data: bytes) -> int:
    """Return the UART checksum: complement of the byte sum."""
    return (~sum(data)) & 0xFF


@dataclass(slots=True)
class SimCanFrame:
    """A CAN frame on the simulated bus."""

    can_id: int
    data: bytes


@dataclass(slots=True)
class HeatPump:
    """Register state of the simulated heat pump."""

    can_registers: dict[tuple[int, tuple[int, ...]], bytes] = field(
        default_factory=dict
    )
    can_silent: set[tuple[int, tuple[int, ...]]] = field(default_factory=set)
    # Registers that ignore writes.
    can_read_only: set[tuple[int, tuple[int, ...]]] = field(default_factory=set)
    uart_protocol: str = "I"
    uart_registers: dict[int, bytes] = field(default_factory=dict)
    uart_bad_checksum: set[int] = field(default_factory=set)
    # Registers that are not answered at all (unknown ones get a NAK).
    uart_silent: set[int] = field(default_factory=set)
    # Answer to a request in the other protocol; None: no answer.
    uart_foreign_reply: bytes | None = UART_NAK
    # Answer frames that replace the regular answer of a register once.
    uart_next_answer: dict[int, bytes] = field(default_factory=dict)
    uart_requests: list[int] = field(default_factory=list)
    can_writes: list[SimCanFrame] = field(default_factory=list)
    on_can_write: Callable[[int, tuple[int, ...], bytes], None] | None = None

    # ------------------------------------------------------------------ CAN

    def set_can(self, responder: int, register: tuple[int, ...], value: bytes) -> None:
        """Set the two data bytes of a register."""
        if len(value) != 2:
            raise ValueError("CAN register values have two bytes")
        self.can_registers[(responder, register)] = value

    def handle_can(self, frame: SimCanFrame) -> list[SimCanFrame]:
        """Answer a frame sent on the bus; return the frames sent in reply."""
        data = frame.data
        if len(data) < 7:
            return []
        target = can_target(data[0])
        kind = can_kind(data[0])
        register = can_register(data)
        key = (target, register)
        if kind == KIND_WRITE:
            value = data[5:7] if register[0] == CAN_LONG_REGISTER else data[3:5]
            if key in self.can_registers and key not in self.can_read_only:
                self.can_registers[key] = bytes(value)
                self.can_writes.append(frame)
                if self.on_can_write is not None:
                    self.on_can_write(target, register, bytes(value))
            return []
        if kind != KIND_READ or key not in self.can_registers or key in self.can_silent:
            return []
        value = self.can_registers[key]
        head = bytes((can_byte0(frame.can_id, KIND_ANSWER), 0x00))
        if register[0] == CAN_LONG_REGISTER:
            payload = head + bytes(register) + value
        else:
            payload = head + bytes(register) + value + b"\x00\x00"
        return [SimCanFrame(can_id=target, data=payload)]

    def panel_write(self, register: tuple[int, ...], value: bytes) -> SimCanFrame:
        """Return the frame the RoCon panel sends when a setting is changed."""
        head = bytes((can_byte0(0x180, KIND_WRITE), 0x00)) + bytes(register)
        if register[0] == CAN_LONG_REGISTER:
            data = head + value
        else:
            data = head + value + b"\x00\x00"
        self.can_registers[(0x180, register)] = value
        return SimCanFrame(can_id=CAN_PANEL_ID, data=data)

    # ----------------------------------------------------------------- UART

    def handle_uart(self, request: bytes) -> bytes:
        """Answer a complete UART request."""
        if self.uart_protocol == "I":
            if len(request) != 4 or request[:2] != b"\x03\x40":
                return self.uart_foreign_reply or b""
            register = request[2]
        else:
            if len(request) != 3 or request[0] != 0x02:
                return self.uart_foreign_reply or b""
            register = request[1]
        if uart_checksum(request[:-1]) != request[-1]:
            return UART_NAK
        self.uart_requests.append(register)
        if register in self.uart_silent:
            return b""
        if register in self.uart_next_answer:
            return self.uart_next_answer.pop(register)
        if register not in self.uart_registers:
            return UART_NAK
        payload = self.uart_registers[register]
        if self.uart_protocol == "I":
            frame = bytes((0x40, register, len(payload) + 2)) + payload
        else:
            frame = bytes((register,)) + payload
        checksum = uart_checksum(frame)
        if register in self.uart_bad_checksum:
            checksum ^= 0xFF
        return frame + bytes((checksum,))

    def set_uart_frame(self, frame: bytes) -> None:
        """Answer the register of a complete answer frame with its payload."""
        if self.uart_protocol == "I":
            self.uart_registers[frame[1]] = frame[3:-1]
        else:
            self.uart_registers[frame[0]] = frame[1:-1]
