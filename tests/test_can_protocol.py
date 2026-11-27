"""Tests for the CAN frame format and the value table (no Home Assistant)."""

import re

import pytest

from custom_components.daikin_heat_pump_control.bridge.protocol import CanFrame
from custom_components.daikin_heat_pump_control.can.protocol import (
    Register,
    addressed_id,
    frame_kind,
    parse_command,
    read_frame,
    register_of,
)
from custom_components.daikin_heat_pump_control.can.table import (
    CAN_VALUES,
    CAN_VALUES_BY_KEY,
    HOT_WATER_SETPOINTS,
    ROOM_SETPOINTS,
    Platform,
)

TRANSLATION_KEY = re.compile(r"^(?!.+[_-]{2})(?![_-])[a-z0-9-_]+(?<![_-])$")


def _answer(responder: int, data: str) -> CanFrame:
    return CanFrame(can_id=responder, data=bytes.fromhex(data))


def _decode(key: str, data: str) -> object:
    decoded = CAN_VALUES_BY_KEY[key].decode(bytes.fromhex(data))
    assert decoded is not None
    return decoded.state


def test_parse_command() -> None:
    """Commands are hex tokens; missing bytes are zero, other characters dropped."""
    assert parse_command("31 00 FA C1 05").hex() == "3100fac1050000"
    assert parse_command("31 00 1C").hex() == "31001c00000000"
    with pytest.raises(ValueError, match="Invalid command"):
        parse_command("31 00")
    with pytest.raises(ValueError, match="too short"):
        parse_command("31 00 FA C1")


def test_frame_fields() -> None:
    """Byte 0 holds the addressed node and the kind of frame."""
    data = bytes.fromhex("D200FAC0FC012C")
    assert addressed_id(data) == 0x680
    assert frame_kind(data) == 2
    assert register_of(data) == (0xFA, 0xC0, 0xFC)
    assert register_of(bytes.fromhex("31001C00000000")) == (0x1C,)
    assert read_frame(parse_command("31 00 1C")).encode() == "680#31001C00000000"


def test_register_accepts() -> None:
    """Answers of the responder and panel writes/answers carry the value."""
    register = Register(responder=0x180, address=(0xFA, 0x01, 0x12))
    assert str(register) == "180:FA 01 12"
    assert register.accepts(_answer(0x180, "D200FA01120300"))
    # The answer to a request of another bus participant is heard as well.
    assert register.accepts(_answer(0x180, "2200FA01120300"))
    assert register.accepts(_answer(0x10A, "3000FA01120500"))
    assert register.accepts(_answer(0x10A, "3200FA01120500"))
    # A read request of the panel carries no value.
    assert not register.accepts(_answer(0x10A, "3100FA01120000"))
    assert not register.accepts(_answer(0x300, "D200FA01120300"))
    assert not register.accepts(_answer(0x180, "D200FA01130300"))
    assert not register.accepts(_answer(0x180, "D200FA0112"))


def test_reference_frames() -> None:
    """Decoding of the reference examples."""
    assert _decode("tv", "D200FAC0FC012C") == 30.0
    assert _decode("temperature_outside", "D200FAC0FFFFCE") == -5.0
    assert _decode("max_target_flow_temp", "D2002801220000") == 29.0
    assert _decode("water_pressure", "D2001C07080000") == 1.8
    assert _decode("temperature_antifreeze", "D200FA0A00FF60") == "off"
    assert _decode("temperature_antifreeze", "D200FA0A00FFD8") == "minus_4"
    assert _decode("operating_mode", "D200FA01120500") == "summer"
    assert _decode("status_kompressor", "A2006101000000") is True
    assert _decode("1_dhw", "D200FA01440001") is True
    assert _decode("power_dhw", "D200FA0668012C") == 3.0
    assert _decode("heating_limit_day", "D200FA0116FE70") == "off"
    assert _decode("heating_limit_night", "D200FA0117005A") == "off"
    assert _decode("heating_limit_night", "D200FA011700C8") == "20"
    assert _decode("cooling_setpoint_adj", "D200FA1359FFFB") == -0.5


def test_special_decoders() -> None:
    """Heater stages are bits of byte 5; the sensor flag is byte 6 == 5."""
    assert _decode("electric_heater", "D200FA0A200100") == "off"
    assert _decode("electric_heater", "D200FA0A200900") == "3"
    assert _decode("electric_heater", "D200FA0A200D00") == "6"
    assert _decode("electric_heater", "D200FA0A200F00") == "9"
    assert _decode("external_temp_sensor", "D200FA09610005") is True
    assert _decode("external_temp_sensor", "D200FA09610001") is False


def test_range_no_value_and_unknown_codes() -> None:
    """Implausible values are dropped; markers and unknown codes are kept."""
    assert CAN_VALUES_BY_KEY["tv"].decode(bytes.fromhex("D200FAC0FC0000")) is None
    decoded = CAN_VALUES_BY_KEY["total_electrical_energy"].decode(
        bytes.fromhex("D200FAC2FA8000")
    )
    assert decoded is not None
    assert decoded.state is None
    assert decoded.raw == 0x8000
    assert _decode("error_code", "D200FA13882329") == "e9001"
    assert _decode("error_code", "D200FA13881F46") == "w8006"
    assert _decode("error_code", "D200FA1388270F") == "unknown"
    assert _decode("mode_of_operating", "D200FAC0F60009") is None


def test_select_takes_nearest_option() -> None:
    """An unlisted raw value of a select shows the closest option."""
    assert _decode("operating_mode", "D200FA01120D00") == "automatic_2"
    assert _decode("temperature_antifreeze", "D200FA0A00FFD5") == "minus_4"


def test_table() -> None:
    """Keys and registers are unique, options are valid translation keys."""
    keys = [value.key for value in CAN_VALUES]
    assert len(keys) == len(set(keys)) == 107
    registers = [(value.responder, value.register.address) for value in CAN_VALUES]
    assert len(registers) == len(set(registers))
    for value in CAN_VALUES:
        assert TRANSLATION_KEY.match(value.key), value.key
        for option in value.option_keys:
            assert TRANSLATION_KEY.match(option), (value.key, option)
        if value.platform is Platform.NUMBER:
            assert value.minimum is not None
            assert value.maximum is not None
            assert value.step is not None
        if value.platform in (Platform.SELECT, Platform.ENUM):
            assert value.options
    assert ROOM_SETPOINTS[:3] == (15.0, 16.0, 17.0)
    assert 19.5 in ROOM_SETPOINTS
    assert len(ROOM_SETPOINTS) == 16
    assert HOT_WATER_SETPOINTS == (
        35.0,
        40.0,
        45.0,
        46.0,
        47.0,
        48.0,
        49.0,
        50.0,
        51.0,
        52.0,
        53.0,
        54.0,
        55.0,
        60.0,
        65.0,
        70.0,
    )
