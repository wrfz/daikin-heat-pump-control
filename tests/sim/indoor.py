"""Answers of simulated indoor units at the X10A connector.

Most frames are real answers: a Rotex HPSU with an R410A outdoor unit, an
HPSU with an Altherma 3 R E outdoor unit (ERGA06EAV3), and an S protocol unit
(RRLQ008BAV3). Helpers build further frames from payload fields.
"""

from .heat_pump import HeatPump, uart_checksum


def i_frame(register: int, payload: bytes) -> bytes:
    """Return an I answer: 40 <register> <length> <payload> <checksum>."""
    head = bytes((0x40, register, len(payload) + 2)) + payload
    return head + bytes((uart_checksum(head),))


def s_frame(register: int, payload: bytes = b"") -> bytes:
    """Return an S answer with the payload padded to the fixed length."""
    size = (6 if register in (0x50, 0x56) else 18) - 2
    head = bytes((register,)) + payload.ljust(size, b"\x00")
    return head + bytes((uart_checksum(head),))


def le16(value: float, divider: float = 10) -> bytes:
    """Return a signed little endian value in 1/divider."""
    return round(value * divider).to_bytes(2, "little", signed=True)


def u16_256(value: float) -> bytes:
    """Return an unsigned little endian value in 1/256 (S temperatures)."""
    return round(value * 256).to_bytes(2, "little")


def payload(size: int, fields: dict[int, bytes] | None = None) -> bytes:
    """Return `size` zero bytes with the fields set at their offsets."""
    data = bytearray(size)
    for offset, value in (fields or {}).items():
        data[offset : offset + len(value)] = value
    return bytes(data)


def with_bytes(frame: bytes, fields: dict[int, bytes]) -> bytes:
    """Return an I frame with payload bytes replaced."""
    data = bytearray(frame[3:-1])
    for offset, value in fields.items():
        data[offset : offset + len(value)] = value
    return i_frame(frame[1], bytes(data))


# Rotex HPSU with an R410A outdoor unit, heating with the compressor running.
HPSU_0X00 = bytes.fromhex("40 00 0E 04 01 00 01 01 01 00 02 01 01 04 39 68")
HPSU_0X10_STARTUP = bytes.fromhex(
    "40 10 12 01 20 00 00 00 00 70 03 00 00 00 00 00 00 00 00 09"
)
HPSU_0X20 = bytes.fromhex(
    "40 20 13 DD FF 00 00 53 02 00 00 BF FF 00 00 46 00 BF 00 00 98"
)
# Only 5 payload bytes: no voltage.
HPSU_0X21 = bytes.fromhex("40 21 07 3A 00 32 00 00 2B")
HPSU_0X30_HEATING = bytes.fromhex("40 30 0D 3A 50 00 D1 01 00 00 80 00 00 00 A6")
HPSU_0X30_DEFROST = bytes.fromhex("40 30 0D 2C 00 00 5E 01 00 00 00 00 00 00 F7")
HPSU_0X30_STANDSTILL = i_frame(0x30, bytes.fromhex("00 50 00 D1 01 00 00 80 00 00 00"))
HPSU_0X60_HEATING = bytes.fromhex(
    "40 60 12 80 00 18 00 40 3E 3C EA 01 4A 01 E0 86 05 03 00 57"
)
HPSU_0X60_HOT_WATER = bytes.fromhex(
    "40 60 12 80 00 48 00 40 3E 3C EA 01 E0 01 E0 C6 05 03 00 51"
)
HPSU_0X60_STANDBY = bytes.fromhex(
    "40 60 12 80 00 00 00 40 3E 3C FA 00 4A 01 20 84 05 03 00 22"
)


def hpsu_0x61(
    tv: float = 29.7, t_liq: float = 29.7, tr: float = 26.7, dhw: float = 48.0
) -> bytes:
    """Return 0x61 with flow, liquid line, return and hot water temperature."""
    return i_frame(
        0x61,
        payload(
            12,
            {
                2: le16(tv),
                4: le16(tv + 0.2),
                6: le16(t_liq),
                8: le16(tr),
                10: le16(dhw),
            },
        ),
    )


def hpsu_0x20(discharge: float = 59.5, pressure: float = 19.1) -> bytes:
    """Return the real 0x20 frame with another discharge temperature and pressure."""
    return with_bytes(HPSU_0X20, {4: le16(discharge), 14: le16(pressure)})


HPSU_0X10 = with_bytes(HPSU_0X10_STARTUP, {1: b"\x00"})

HPSU_FRAMES = (
    HPSU_0X00,
    HPSU_0X10,
    HPSU_0X20,
    HPSU_0X21,
    HPSU_0X30_HEATING,
    HPSU_0X60_HEATING,
    hpsu_0x61(),
)

# HPSU with ERGA06EAV3 (R32), heating with the compressor running.
ERGA_0X10 = bytes.fromhex("40 10 12 01 00 00 00 00 00 73 04 00 00 00 00 00 00 00 00 25")
ERGA_0X20 = bytes.fromhex(
    "40 20 13 0A 00 00 00 AE 01 00 00 E7 FF 00 00 00 00 00 00 01 EC"
)
ERGA_0X30 = bytes.fromhex("40 30 0D 16 47 00 03 01 00 00 00 00 00 00 21")
ERGA_0X60 = bytes.fromhex(
    "40 60 13 80 00 18 00 00 00 50 E0 01 2C 01 E0 02 03 A4 79 00 54"
)
ERGA_0X61 = bytes.fromhex("40 61 12 80 00 2A 01 2A 01 24 01 14 01 D8 01 04 00 06 00 59")
ERGA_0X62 = bytes.fromhex(
    "40 62 13 80 00 00 FA 00 78 00 00 01 94 00 00 31 00 00 B4 00 DE"
)

ERGA_FRAMES = (ERGA_0X10, ERGA_0X20, ERGA_0X30, ERGA_0X60, ERGA_0X61, ERGA_0X62)

# S protocol: circulation pump on, TR 26.5 °C, TV 29.5 °C, heating.
S_0X53 = s_frame(0x53, bytes((0x01,)))
S_0X54 = s_frame(0x54, payload(16, {2: u16_256(26.5), 4: u16_256(29.5)}))
S_0X55 = bytes.fromhex("55 01 00 00 00 00 10 00 00 00 00 00 00 00 00 00 00 99")

S_FRAMES = (S_0X53, S_0X54, S_0X55)


def load_indoor(heat_pump: HeatPump, frames: tuple[bytes, ...] = HPSU_FRAMES) -> None:
    """Let the heat pump answer with the given frames."""
    for frame in frames:
        heat_pump.set_uart_frame(frame)


def load_s(heat_pump: HeatPump) -> None:
    """Make the heat pump an S protocol unit."""
    heat_pump.uart_protocol = "S"
    heat_pump.uart_registers.clear()
    load_indoor(heat_pump, S_FRAMES)
