"""Frames of the RoCon CAN protocol.

Every frame has seven data bytes. Byte 0 holds the addressed node in the high
nibble (times 0x80 gives its CAN id) and the kind of frame in the low nibble.
A register is either short (byte 2, data in bytes 3-4) or long (byte 2 is
0xFA, register in bytes 3-4, data in bytes 5-6). Answers carry the register
of the request, so a frame is assigned to a value by its sender and register.
"""

from dataclasses import dataclass
from enum import IntEnum
import re
from typing import Final, override

from ..bridge.protocol import CanFrame

OWN_ID: Final = 0x680
CONTROLLER_ID: Final = 0x180
PANEL_ID: Final = 0x10A
LONG_REGISTER: Final = 0xFA
FRAME_LENGTH: Final = 7

_HEX_BYTE = re.compile(r"[0-9A-Fa-f]{2}")


class Kind(IntEnum):
    """Kind of a frame, low nibble of byte 0."""

    WRITE = 0
    READ = 1
    ANSWER = 2


def frame_kind(data: bytes) -> int:
    """Return the kind encoded in byte 0."""
    return data[0] & 0x0F


def addressed_id(data: bytes) -> int:
    """Return the CAN id addressed by byte 0."""
    return (data[0] >> 4) * 0x80


def parse_command(text: str) -> bytes:
    """Return the seven bytes of a command written as hex byte tokens.

    Missing bytes are zero, so `31 00 FA C1 05` is a complete read request.
    """
    data = bytes(int(token, 16) for token in _HEX_BYTE.findall(text))
    if len(data) < 3 or len(data) > FRAME_LENGTH:
        raise ValueError(f"Invalid command {text!r}")
    if data[2] == LONG_REGISTER and len(data) < 5:
        raise ValueError(f"Long register command {text!r} is too short")
    return data.ljust(FRAME_LENGTH, b"\x00")


def register_of(data: bytes) -> tuple[int, ...]:
    """Return the register address of a frame: (0xFA, high, low) or (short,)."""
    if data[2] == LONG_REGISTER:
        return (LONG_REGISTER, data[3], data[4])
    return (data[2],)


@dataclass(frozen=True, slots=True, kw_only=True)
class Register:
    """A register of a bus node."""

    responder: int
    address: tuple[int, ...]

    @classmethod
    def from_command(cls, responder: int, command: bytes) -> Register:
        """Return the register read by a command."""
        return cls(responder=responder, address=register_of(command))

    def accepts(self, frame: CanFrame) -> bool:
        """Return True if a received frame carries a value of this register.

        Accepted are all frames of the responder with the register, whoever
        asked, and the write and answer frames of the RoCon control panel.
        """
        data = frame.data
        if len(data) < FRAME_LENGTH or register_of(data) != self.address:
            return False
        if frame.can_id == self.responder:
            return True
        return frame.can_id == PANEL_ID and frame_kind(data) in (
            Kind.WRITE,
            Kind.ANSWER,
        )

    @override
    def __str__(self) -> str:
        """Return the register for logs, e.g. `180:FA C0 FC`."""
        address = " ".join(f"{byte:02X}" for byte in self.address)
        return f"{self.responder:03X}:{address}"


def read_frame(command: bytes) -> CanFrame:
    """Return the frame that reads a register."""
    return CanFrame(can_id=OWN_ID, data=command)


def raw_value(data: bytes, offset: int, size: int) -> int:
    """Return the unsigned value at a data offset (one byte or big-endian word)."""
    if size == 2:
        return (data[offset] << 8) | data[offset + 1]
    return data[offset]


def signed16(value: int) -> int:
    """Interpret a 16-bit value as two's complement."""
    return value - 0x10000 if value & 0x8000 else value
