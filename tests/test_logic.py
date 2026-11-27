"""Tests for computed values and smoothing (no Home Assistant)."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from custom_components.daikin_heat_pump_control.logic.derived import (
    DERIVED,
    SMOOTHED,
    WindowMax,
    difference,
    system_time,
    thermal_power,
)
from custom_components.daikin_heat_pump_control.logic.smoothing import (
    Smoother,
    round_half_away,
)

BERLIN = ZoneInfo("Europe/Berlin")


def test_formulas() -> None:
    """Thermal power from spread and flow, differences on 0.01."""
    assert thermal_power(30.0, 25.0, 1200.0) == pytest.approx(6.983, abs=1e-3)
    assert thermal_power(25.0, 30.0, 0.0) == 0.0
    assert difference(30.1, 25.3) == 4.8


def test_derived_needs_all_inputs() -> None:
    """A computed value is unknown until every input is a number."""
    power = next(d for d in DERIVED if d.key == "thermal_power_raw")
    assert power.compute({"tv": 30.0, "tr": 25.0}) is None
    assert power.compute({"tv": 30.0, "tr": 25.0, "flow_rate": True}) is None
    assert power.compute({"tv": 30.0, "tr": 25.0, "flow_rate": 1200}) == 6.983
    assert set(SMOOTHED) == {"thermal_power", "temperature_spread"}


def test_system_time() -> None:
    """The controller clock as a local time; invalid dates give None."""
    parts = {
        "system_date_year": 26.0,
        "system_date_month": 11.0,
        "system_date_day": 27.0,
        "system_time_hour": 12.0,
        "system_time_minute": 30.0,
        "system_time_second": 45.0,
    }
    result = system_time(parts, BERLIN)
    assert result is not None
    assert result.astimezone(UTC) == datetime(2026, 11, 27, 11, 30, 45, tzinfo=UTC)
    assert system_time({**parts, "system_date_month": 13.0}, BERLIN) is None
    assert system_time({**parts, "system_time_second": None}, BERLIN) is None


def test_window_max() -> None:
    """The maximum of all readings since the previous publication."""
    window = WindowMax()
    assert window.add(30.0, 0, 30000) == 30.0
    assert window.add(35.0, 2000, 30000) is None
    assert window.add(31.0, 4000, 30000) is None
    assert window.add(31.0, 30000, 30000) == 35.0
    window.reset()
    assert window.add(20.0, 31000, 30000) == 20.0


def test_round_half_away() -> None:
    """Halves are rounded away from zero."""
    assert round_half_away(0.125) == 0.13
    assert round_half_away(-0.125) == -0.13
    assert round_half_away(2.344) == 2.34


def test_smoother_follows_slowly() -> None:
    """The first step takes the raw value, later steps move towards it."""
    smoother = Smoother()
    assert not smoother.update(20.0)
    smoother.set_raw(5.0)
    assert not smoother.update(10.0)
    assert smoother.update(10.5)
    assert smoother.value == 5.0
    assert not smoother.update(15.0)
    smoother.set_raw(7.0)
    values = []
    for step in range(1, 30):
        assert smoother.update(10.5 + step * 10.1)
        assert smoother.value is not None
        values.append(smoother.value)
    assert 5.0 < values[0] < 6.0
    assert values[:8] == sorted(values[:8])
    assert max(values) < 7.3
    assert values[-1] == pytest.approx(7.0, abs=0.05)
    assert all(round(v, 2) == v for v in values)


def test_smoother_reset_and_invalid_input() -> None:
    """Unknown raw values pause the smoothing; a reset starts again."""
    smoother = Smoother()
    smoother.set_raw(float("nan"))
    assert not smoother.update(20.0)
    smoother.set_raw(3.0)
    assert smoother.update(20.0)
    smoother.reset()
    assert smoother.value is None
    assert smoother.raw is None
