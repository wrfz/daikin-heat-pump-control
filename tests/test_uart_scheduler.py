"""Tests for the UART polling and the refrigerant circuit (no Home Assistant)."""

import pytest

from custom_components.daikin_heat_pump_control.logic.refrigerant import (
    NO_VALUES,
    CircuitValues,
    RefrigerantCircuit,
)
from custom_components.daikin_heat_pump_control.uart.protocol import (
    Frame,
    Protocol,
    request,
)
from custom_components.daikin_heat_pump_control.uart.scheduler import (
    FAILED_INTERVAL_MS,
    UartScheduler,
)


def _frame(register: int) -> Frame:
    return Frame(register=register, payload=b"", raw=b"")


def test_order_and_interval() -> None:
    """One request at a time; due 5 s after the answer; oldest sent first."""
    scheduler = UartScheduler(Protocol.I, [0x10, 0x20, 0x10])
    assert list(scheduler.registers) == [0x10, 0x20]
    assert scheduler.next_request(0) == request(Protocol.I, 0x10)
    assert scheduler.next_request(0) is None
    scheduler.handle_sent(5)
    scheduler.handle_sent(50)
    assert scheduler.open is not None
    assert scheduler.open.sent_at == 5
    assert not scheduler.handle_frame(40, _frame(0x10))
    assert scheduler.next_request(100) == request(Protocol.I, 0x20)
    scheduler.handle_frame(140, _frame(0x20))
    assert scheduler.next_request(5040) is None
    assert scheduler.next_request(5041) == request(Protocol.I, 0x10)
    # An answer of a register that is not polled closes nothing.
    assert not scheduler.handle_frame(5050, _frame(0x61))
    assert scheduler.open is not None


def test_failures() -> None:
    """Three failures make a register failed; it is asked every 10 minutes."""
    scheduler = UartScheduler(Protocol.S, [0x54])
    assert scheduler.handle_failure() is None
    assert scheduler.check_timeout(0) is None
    assert scheduler.next_request(0) == request(Protocol.S, 0x54)
    assert scheduler.check_timeout(2999) is None
    assert scheduler.check_timeout(3000) is None
    scheduler.next_request(3000)
    assert scheduler.handle_failure() is None
    scheduler.next_request(3100)
    assert scheduler.check_timeout(6100) == 0x54
    assert scheduler.is_failed(0x54)
    assert scheduler.all_failed
    assert not scheduler.is_failed(0x55)
    assert scheduler.next_request(6200) is None
    assert scheduler.next_request(3100 + FAILED_INTERVAL_MS) is not None
    assert scheduler.handle_frame(3200 + FAILED_INTERVAL_MS, _frame(0x54))
    assert not scheduler.is_failed(0x54)
    diagnostics = scheduler.diagnostics()
    assert diagnostics["registers"]["54"]["lost"] == 3
    assert diagnostics["open"] is None


def test_retry_and_reset() -> None:
    """Failed registers can be asked at once; a reset forgets the times."""
    scheduler = UartScheduler(Protocol.I, [0x61])
    for now in (0, 4000, 8000):
        scheduler.next_request(now)
        scheduler.check_timeout(now + 3000)
    assert scheduler.is_failed(0x61)
    assert scheduler.next_request(12000) is None
    scheduler.retry_failed()
    assert scheduler.next_request(12000) is not None
    assert scheduler.diagnostics()["open"] == {"register": "61", "sent_at": None}
    scheduler.reset()
    assert scheduler.open is None
    assert scheduler.registers[0x61].last_sent is None
    assert not UartScheduler(Protocol.I, []).all_failed


HEATING = {
    "inv_freq": 3480.0,
    "defrost_operation": False,
    "4_way_valve": "heating",
    "mode_of_operating": "heating",
    "outdoor_temp": 1.5,
    "temp_after_compr": 62.0,
    "exch_temp": -2.0,
    "heat_sink_temp": 7.0,
    "saturation_temp": 30.2,
    "t_liq": 29.7,
}
ALL = tuple(HEATING)


def test_circuit_values_per_new_frame() -> None:
    """Values come with the first new outdoor frame after the start."""
    circuit = RefrigerantCircuit(ALL)
    states = dict(HEATING)
    assert circuit.update_circuit(states) is None  # the frame from the start
    assert circuit.update_state(states) is None
    assert circuit.update_circuit(states) is None
    states["temp_after_compr"] = 62.5
    assert circuit.update_circuit(states) == CircuitValues(0.5, 32.3)
    states["t_liq"] = 29.0
    assert circuit.update_circuit(states) is None
    states["saturation_temp"] = None
    assert circuit.update_circuit(states) == CircuitValues(None, None)
    circuit.reset()
    assert circuit.update_circuit(dict(HEATING)) is None


@pytest.mark.parametrize(
    ("changes", "present"),
    [
        ({"inv_freq": 0.0}, ALL),
        ({"inv_freq": None}, ALL),
        ({"defrost_operation": True}, ALL),
        ({"4_way_valve": "cooling"}, ALL),
        ({"mode_of_operating": "cooling"}, tuple(k for k in ALL if k != "4_way_valve")),
    ],
)
def test_circuit_not_heating(
    changes: dict[str, object], present: tuple[str, ...]
) -> None:
    """Without heating with a running compressor there are no values."""
    circuit = RefrigerantCircuit(present)
    states = {**HEATING, **changes}
    assert circuit.update_state(states) == NO_VALUES
    assert circuit.update_circuit(states) == NO_VALUES


def test_circuit_without_state_values() -> None:
    """Without compressor, defrost and valve values only the mode counts."""
    circuit = RefrigerantCircuit(("mode_of_operating", "saturation_temp", "t_liq"))
    states = {**HEATING, "inv_freq": 0.0, "4_way_valve": "cooling"}
    assert circuit.update_state(states) is None


def test_circuit_values_known_after_the_start() -> None:
    """A value read for the first time after the start belongs to the old frame."""
    circuit = RefrigerantCircuit(ALL)
    states = {**HEATING, "saturation_temp": None}
    assert circuit.update_state(states) is None
    states["saturation_temp"] = 30.2
    assert circuit.update_circuit(states) is None
    states["saturation_temp"] = 30.5
    assert circuit.update_circuit(states) == CircuitValues(0.8, 31.5)
