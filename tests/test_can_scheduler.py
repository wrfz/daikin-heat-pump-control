"""Tests for the polling scheduler (no Home Assistant)."""

import pytest

from custom_components.daikin_heat_pump_control.bridge.protocol import CanFrame
from custom_components.daikin_heat_pump_control.can.scheduler import CanScheduler
from custom_components.daikin_heat_pump_control.can.table import CAN_VALUES_BY_KEY

KEYS = ("tv", "tr", "operating_mode")
ANSWERS = {
    "tv": "D200FAC0FC012C",
    "tr": "D200FAC10000FA",
    "operating_mode": "D200FA01120300",
}


def _scheduler(**intervals: float) -> CanScheduler:
    values = [CAN_VALUES_BY_KEY[key] for key in KEYS]
    return CanScheduler(values, {key: intervals.get(key, 30.0) for key in KEYS})


def _answer(key: str) -> CanFrame:
    return CanFrame(can_id=0x180, data=bytes.fromhex(ANSWERS[key]))


def _key_of(frames: list[CanFrame]) -> str:
    [frame] = frames
    for key in KEYS:
        if CAN_VALUES_BY_KEY[key].command == frame.data:
            return key
    raise AssertionError(frame)


def test_one_request_at_a_time_in_table_order() -> None:
    """Never asked values come first; only one request is open."""
    scheduler = _scheduler()
    first = scheduler.next_request(0)
    assert _key_of(first) == "tv"
    assert scheduler.next_request(100) == []
    match = scheduler.handle_frame(300, _answer("tv"))
    assert match is not None
    value, decoded = match
    assert value.key == "tv"
    assert decoded is not None
    assert decoded.state == 30.0
    assert _key_of(scheduler.next_request(300)) == "tr"
    scheduler.handle_frame(600, _answer("tr"))
    assert _key_of(scheduler.next_request(600)) == "operating_mode"
    scheduler.handle_frame(900, _answer("operating_mode"))
    assert scheduler.next_request(900) == []
    assert scheduler.requests == 3


def test_most_overdue_first() -> None:
    """When several values are due, the one waiting longest goes first."""
    scheduler = _scheduler(operating_mode=5.0)
    for time, key in ((0, "tv"), (300, "tr"), (600, "operating_mode")):
        scheduler.next_request(time)
        scheduler.handle_frame(time + 50, _answer(key))
    assert scheduler.next_request(5000) == []
    assert _key_of(scheduler.next_request(5700)) == "operating_mode"
    scheduler.handle_frame(5750, _answer("operating_mode"))
    # operating_mode is overdue by 20 s, tv by 0.95 s and tr by 0.65 s.
    assert _key_of(scheduler.next_request(31000)) == "operating_mode"
    scheduler.handle_frame(31050, _answer("operating_mode"))
    assert _key_of(scheduler.next_request(31050)) == "tv"


def test_heard_answers_postpone_the_request() -> None:
    """A value heard on the bus is not asked for before its interval."""
    scheduler = _scheduler()
    scheduler.handle_frame(0, _answer("tv"))
    assert _key_of(scheduler.next_request(10)) == "tr"


def test_timeout_counts_from_transmission(caplog: pytest.LogCaptureFixture) -> None:
    """A request is lost 3 s after it was sent and asked again after its interval."""
    scheduler = _scheduler(tv=10.0)
    [frame] = scheduler.next_request(0)
    scheduler.handle_sent(500, CanFrame(can_id=0x680, data=bytes(7)))
    scheduler.handle_sent(1000, frame)
    scheduler.handle_sent(1200, frame)
    assert scheduler.next_request(3900) == []
    assert scheduler.diagnostics()["open_request"] == {
        "key": "tv",
        "handed_at": 0,
        "sent_at": 1000,
    }
    assert _key_of(scheduler.next_request(4000)) == "tr"
    assert "No answer from the heat pump for tv (180:FA C0 FC)" in caplog.text
    scheduler.handle_frame(4100, _answer("tr"))
    assert _key_of(scheduler.next_request(4100)) == "operating_mode"
    scheduler.handle_frame(4200, _answer("operating_mode"))
    # tv was asked at 0: due again after its interval of 10 s.
    assert scheduler.next_request(9000) == []
    assert _key_of(scheduler.next_request(10100)) == "tv"
    caplog.clear()
    assert scheduler.next_request(13000) == []
    scheduler.next_request(13200)
    assert "No answer" not in caplog.text
    scheduler.handle_frame(23300, _answer("tv"))
    assert "CAN value tv answers again" in caplog.text
    assert scheduler.diagnostics()["values"]["tv"]["lost"] == 2


def test_unsent_request_times_out_after_handover() -> None:
    """A request the bridge never sent is given up 3 s after the handover."""
    scheduler = _scheduler()
    scheduler.next_request(0)
    assert _key_of(scheduler.next_request(3000)) == "tr"


def test_unhandled_and_short_frames() -> None:
    """Frames of other registers or too short are not assigned."""
    scheduler = _scheduler()
    assert scheduler.handle_frame(0, CanFrame(can_id=0x180, data=bytes(3))) is None
    other = CanFrame(can_id=0x180, data=bytes.fromhex("D200FA01130300"))
    assert scheduler.handle_frame(0, other) is None
    wrong_sender = CanFrame(can_id=0x300, data=bytes.fromhex(ANSWERS["tv"]))
    assert scheduler.handle_frame(0, wrong_sender) is None
    assert scheduler.unhandled == 2


def test_reset() -> None:
    """After a reset every value is due again."""
    scheduler = _scheduler()
    scheduler.next_request(0)
    scheduler.handle_frame(50, _answer("tv"))
    scheduler.next_request(100)
    scheduler.reset()
    assert scheduler.diagnostics()["open_request"] is None
    assert _key_of(scheduler.next_request(200)) == "tv"
    assert scheduler.keys == list(KEYS)
    assert scheduler.interval_ms("tv") == 30000
