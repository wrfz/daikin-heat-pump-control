"""Tests for writing CAN values and the queue of the scheduler (no Home Assistant)."""

import pytest

from custom_components.daikin_heat_pump_control.bridge.protocol import CanFrame
from custom_components.daikin_heat_pump_control.can.scheduler import (
    CanScheduler,
    Outcome,
)
from custom_components.daikin_heat_pump_control.can.table import (
    CAN_VALUES,
    CAN_VALUES_BY_KEY,
)
from custom_components.daikin_heat_pump_control.services import parse_raw_frame

TV_ANSWER = CanFrame(can_id=0x180, data=bytes.fromhex("D200FAC0FC012C"))


@pytest.mark.parametrize(
    ("key", "state", "frame"),
    [
        # Values and frames as the RoCon expects them.
        ("max_target_flow_temp", 29.0, "30002801220000"),
        ("temperature_antifreeze", "minus_4", "3000FA0A00FFD8"),
        ("temperature_antifreeze", "off", "3000FA0A00FF60"),
        ("heating_limit_day", "off", "3000FA0116FE70"),
        ("heating_limit_night", "off", "3000FA0117005A"),
        ("operating_mode", "summer", "3000FA01120500"),
        ("1_dhw", True, "3000FA01440001"),
        ("1_dhw", False, "3000FA01440000"),
        ("target_room1_temperature", 22.5, "30000500E10000"),
        ("heating_curve", 0.57, "3000FA010E0039"),
        ("power_dhw", 3.0, "3000FA0668012C"),
        ("electric_heater", "off", "3000FA0A200100"),
        ("electric_heater", "3", "3000FA0A200900"),
        ("electric_heater", "6", "3000FA0A200D00"),
        ("electric_heater", "9", "3000FA0A200F00"),
        ("cooling_setpoint_adj", -0.5, "3000FA1359FFFB"),
        ("flow_rate_hyst", 1.0, "3000FA068A000A"),
        ("circulation_pump_min", 50.0, "3000FA067F0032"),
        ("quiet", "night_only", "3000FA06960002"),
    ],
)
def test_encode(key: str, state: object, frame: str) -> None:
    """Settings are written in the read command with kind write."""
    value = CAN_VALUES_BY_KEY[key]
    assert value.encode(value.normalize(state)).hex().upper() == frame  # type: ignore[arg-type]


def test_encoded_value_decodes_to_itself() -> None:
    """Every option and limit of every setting survives encoding and decoding."""
    for value in CAN_VALUES:
        if not value.can_write:
            continue
        if value.options:
            states: list[object] = [key for _, key in value.options]
        elif value.minimum is not None:
            states = [value.minimum, value.maximum, *value.allowed]
        else:
            states = [True, False]
        for state in states:
            data = value.encode(value.normalize(state))  # type: ignore[arg-type]
            decoded = value.decode(data)
            assert decoded is not None, (value.key, state)
            assert decoded.state == state, (value.key, state, data.hex())


@pytest.mark.parametrize(
    ("key", "requested", "stored"),
    [
        ("target_room1_temperature", 22.3, 22.5),
        ("target_room1_temperature", 19.6, 19.5),
        ("target_room1_temperature", 30, 25.0),
        ("target_hot_water_temperature_1", 47.4, 47.0),
        ("target_hot_water_temperature_1", 57, 55.0),
        ("heating_curve", 0.554, 0.55),
        ("flow_temperature_day", 41.26, 41.3),
        ("flow_temperature_day", 10, 20.0),
        ("max_heating_temperature", 99, 85.0),
    ],
)
def test_normalize_numbers(key: str, requested: float, stored: float) -> None:
    """Numbers go to the nearest allowed value or the step grid within the limits."""
    assert CAN_VALUES_BY_KEY[key].normalize(requested) == stored


def test_invalid_states() -> None:
    """States a value cannot take are refused."""
    number = CAN_VALUES_BY_KEY["heating_curve"]
    select = CAN_VALUES_BY_KEY["operating_mode"]
    switch = CAN_VALUES_BY_KEY["1_dhw"]
    with pytest.raises(TypeError):
        number.normalize("1")
    with pytest.raises(TypeError):
        number.normalize(True)
    with pytest.raises(ValueError, match="no option"):
        select.normalize("party")
    with pytest.raises(ValueError, match="no option"):
        select.option_value("party")
    with pytest.raises(TypeError):
        switch.normalize(1)
    with pytest.raises(ValueError, match="not a setting"):
        CAN_VALUES_BY_KEY["tv"].normalize(1.0)
    with pytest.raises(ValueError, match="does not fit"):
        # Not normalized: a byte cannot hold it.
        CAN_VALUES_BY_KEY["delta_temp_ch"].encode(300.0)
    with pytest.raises(ValueError, match="Cannot encode"):
        CAN_VALUES_BY_KEY["delta_temp_ch"].encode(None)
    assert not CAN_VALUES_BY_KEY["heating_curve_adaptation"].can_write
    assert not CAN_VALUES_BY_KEY["tv"].can_write


def test_parse_raw_frame() -> None:
    """Raw frames are hex bytes, separated or not."""
    assert parse_raw_frame("31 00 FA C0 FC") == bytes.fromhex("3100FAC0FC")
    assert parse_raw_frame("0x31,0x00, 0x1c") == bytes.fromhex("31001C")
    assert parse_raw_frame("3100FAC0FC") == bytes.fromhex("3100FAC0FC")
    for text in ("", "3", "31 0", "0x", "zz", "31 00 FA C0 FC 00 00 00"):
        with pytest.raises(ValueError):
            parse_raw_frame(text)


# ------------------------------------------------------------- scheduler


def _scheduler() -> CanScheduler:
    keys = ("tv", "operating_mode")
    return CanScheduler(
        [CAN_VALUES_BY_KEY[key] for key in keys], dict.fromkeys(keys, 30.0)
    )


def _answer(key: str, data: str) -> CanFrame:
    command = CAN_VALUES_BY_KEY[key].command
    return CanFrame(
        can_id=0x180, data=bytes((0xD2, 0)) + command[2:5] + bytes.fromhex(data)
    )


def test_write_goes_first_and_is_confirmed_by_the_read_back() -> None:
    """A write is handed with its read and done with the read-back value."""
    scheduler = _scheduler()
    outcomes: list[Outcome] = []
    value = CAN_VALUES_BY_KEY["operating_mode"]
    data = value.encode("summer")
    scheduler.request_write("operating_mode", data, outcomes.append)
    frames = scheduler.next_request(0)
    assert [frame.data for frame in frames] == [data, value.command]
    assert scheduler.next_request(100) == []
    # Heard before the write is on the bus: no read-back yet.
    scheduler.handle_frame(150, _answer("operating_mode", "0300"))
    assert outcomes == []
    assert scheduler.handle_sent(300, frames[0]) == "operating_mode"
    assert scheduler.handle_sent(300, frames[0]) is None
    scheduler.handle_sent(600, frames[1])
    scheduler.handle_frame(620, _answer("operating_mode", "0500"))
    [outcome] = outcomes
    assert outcome.sent
    assert outcome.decoded is not None
    assert outcome.decoded.state == "summer"
    diagnostics = scheduler.diagnostics()
    assert diagnostics["writes"] == 1
    assert diagnostics["open_request"] is None
    assert scheduler.next_request(700)[0].data == CAN_VALUES_BY_KEY["tv"].command


def test_write_without_read_back(caplog: pytest.LogCaptureFixture) -> None:
    """A write without read-back is reported after the timeout."""
    scheduler = _scheduler()
    outcomes: list[Outcome] = []
    data = CAN_VALUES_BY_KEY["operating_mode"].encode("summer")
    scheduler.request_write("operating_mode", data, outcomes.append)
    frames = scheduler.next_request(0)
    assert scheduler.diagnostics()["open_request"]["key"] == "operating_mode"
    scheduler.handle_sent(250, frames[0])
    scheduler.handle_sent(500, frames[1])
    assert scheduler.next_request(3400) == []
    scheduler.next_request(3500)
    assert outcomes == [Outcome(sent=True)]
    assert "No read-back of the written CAN value operating_mode" in caplog.text
    assert scheduler.diagnostics()["write_failures"] == 1


def test_cancelled_jobs_are_skipped() -> None:
    """A cancelled job is not handed over and reports nothing."""
    scheduler = _scheduler()
    outcomes: list[Outcome] = []
    job = scheduler.request_raw(bytes.fromhex("3100FAC0FC"), outcomes.append)
    assert scheduler.diagnostics()["queued"] == ["raw"]
    job.cancel()
    assert scheduler.diagnostics()["queued"] == []
    assert scheduler.next_request(0)[0].data == CAN_VALUES_BY_KEY["tv"].command
    assert outcomes == []


def test_raw_read_gets_the_answer() -> None:
    """A raw read is done with the first answer of the register."""
    scheduler = _scheduler()
    outcomes: list[Outcome] = []
    scheduler.request_raw(bytes.fromhex("3100FAC0FC"), outcomes.append)
    [frame] = scheduler.next_request(0)
    assert frame == CanFrame(can_id=0x680, data=bytes.fromhex("3100FAC0FC"))
    assert scheduler.diagnostics()["open_request"]["key"] == "raw"
    assert scheduler.handle_sent(250, frame) is None
    # Own frames, reads and other registers are no answer.
    scheduler.handle_frame(260, frame)
    scheduler.handle_frame(
        260, CanFrame(can_id=0x10A, data=bytes.fromhex("3100FAC0FC"))
    )
    scheduler.handle_frame(260, _answer("operating_mode", "0300"))
    assert outcomes == []
    # The answer is also decoded for the polled value.
    match = scheduler.handle_frame(270, TV_ANSWER)
    assert match is not None
    assert outcomes == [Outcome(sent=True, answer=TV_ANSWER)]


def test_raw_read_without_answer() -> None:
    """A raw read without answer is reported after the timeout."""
    scheduler = _scheduler()
    outcomes: list[Outcome] = []
    scheduler.request_raw(bytes.fromhex("3100FA0000"), outcomes.append)
    [frame] = scheduler.next_request(0)
    scheduler.handle_sent(250, frame)
    scheduler.next_request(3300)
    assert outcomes == [Outcome(sent=True)]


@pytest.mark.parametrize(
    ("data", "counted"),
    [("3000FA01440001", "raw"), ("31", None), ("D200FAC0FC012C", None)],
)
def test_raw_frame_without_answer(data: str, counted: str | None) -> None:
    """Raw writes and frames without register are done once sent."""
    scheduler = _scheduler()
    outcomes: list[Outcome] = []
    scheduler.request_raw(bytes.fromhex(data), outcomes.append)
    [frame] = scheduler.next_request(0)
    assert scheduler.handle_sent(250, frame) == counted
    assert outcomes == [Outcome(sent=True)]
    assert scheduler.diagnostics()["raw_frames"] == 1


def test_unsent_raw_frame() -> None:
    """A raw frame the bridge never sent is reported as not sent."""
    scheduler = _scheduler()
    outcomes: list[Outcome] = []
    scheduler.request_raw(bytes.fromhex("3000FA01440001"), outcomes.append)
    scheduler.next_request(0)
    scheduler.next_request(3000)
    assert outcomes == [Outcome(sent=False)]


def test_reset_fails_open_and_queued_jobs(caplog: pytest.LogCaptureFixture) -> None:
    """Writes are dropped when the bus becomes unavailable."""
    scheduler = _scheduler()
    outcomes: list[Outcome] = []
    data = CAN_VALUES_BY_KEY["operating_mode"].encode("summer")
    scheduler.request_write("operating_mode", data, outcomes.append)
    scheduler.next_request(0)
    scheduler.request_raw(bytes.fromhex("3100FAC0FC"), outcomes.append)
    scheduler.request_raw(bytes.fromhex("31"), outcomes.append).cancel()
    scheduler.reset()
    assert outcomes == [Outcome(sent=False), Outcome(sent=False)]
    assert "Dropped 2 CAN write(s)" in caplog.text
    caplog.clear()
    scheduler.reset()
    assert "Dropped" not in caplog.text


def test_poll_answer_closes_the_poll_request() -> None:
    """The answer to a poll closes it; a stale sent report is ignored."""
    scheduler = _scheduler()
    [frame] = scheduler.next_request(0)
    scheduler.handle_frame(50, TV_ANSWER)
    assert scheduler.handle_sent(60, frame) is None
    assert (
        scheduler.next_request(60)[0].data
        == CAN_VALUES_BY_KEY["operating_mode"].command
    )
