"""Tests for the error code checks and the defrost optimization (no Home Assistant)."""

import pytest

from custom_components.daikin_heat_pump_control.logic.defrost import DefrostOptimizer
from custom_components.daikin_heat_pump_control.logic.errors import (
    MINUTE_MS,
    Detector,
    ErrorDetection,
    ErrorSettings,
    Finding,
    min_spread,
)

HEATING = {
    "tv": 30.0,
    "tvbh": 30.0,
    "tr": 25.0,
    "flow_rate": 1200.0,
    "dhw_mixer_position": 0.0,
    "bypass_valve": 0.0,
    "mode_of_operating": "heating",
    "status_kompressor": True,
    "tdhw1": 50.0,
    "temperature_spread": 5.0,
}


@pytest.mark.parametrize(
    ("tv", "spread"), [(50, 4.0), (40, 3.0), (35, 2.5), (29, 1.2), (27, 0.3)]
)
def test_min_spread(tv: float, spread: float) -> None:
    """The fitted curve passes close to its reference points."""
    assert min_spread(tv) == pytest.approx(spread, abs=0.15)


def test_detector() -> None:
    """A fault is confirmed after the holding time; a good case resets it."""
    detector = Detector(1000)
    assert not detector.check(True, 0)
    assert detector.since == 0
    assert not detector.check(True, 1000)
    assert detector.check(True, 1001)
    assert not detector.check(False, 1100)
    assert detector.since is None
    assert not detector.check(True, 1200)
    assert detector.check(True, 2201)


def test_resting_detector() -> None:
    """After a good case the detection rests until it is woken."""
    detector = Detector(1000, rest_after_good=True)
    assert not detector.check(False, 0)
    assert not detector.check(True, 100)
    assert not detector.check(True, 5000)
    assert detector.since is None
    detector.wake()
    assert not detector.check(True, 5000)
    assert detector.check(True, 6001)


def _run(
    detection: ErrorDetection, values: dict[str, object], minutes: float
) -> Finding | None:
    """Evaluate every 30 s for a while; return the last result."""
    finding = None
    for step in range(round(minutes * 2) + 1):
        finding = detection.evaluate(values, step * MINUTE_MS // 2)
    return finding


def test_no_finding_in_normal_operation() -> None:
    """Plausible values give no finding."""
    assert _run(ErrorDetection(ErrorSettings()), HEATING, 30) is None


def test_hot_water_valve() -> None:
    """TVBH differs from TV with the mixer closed: the 3-way valve is defective."""
    values = {**HEATING, "tvbh": 31.0}
    detection = ErrorDetection(ErrorSettings())
    assert _run(detection, values, 10) is None
    assert detection.evaluate(values, 11 * MINUTE_MS) is Finding.DHW_VALVE_DEFECT
    # An offset correcting TV removes the finding.
    corrected = ErrorDetection(ErrorSettings(tv_offset=1.0))
    assert _run(corrected, values, 15) is None


def test_bypass_valve() -> None:
    """TVBH differs from TR with the bypass open: the bypass valve is defective."""
    values = {**HEATING, "bypass_valve": 100.0}
    detection = ErrorDetection(ErrorSettings())
    assert _run(detection, values, 11) is Finding.BYPASS_VALVE_DEFECT
    detection = ErrorDetection(ErrorSettings(max_spread_tvbh_tr=6.0))
    assert _run(detection, values, 15) is None


def test_first_finding_wins() -> None:
    """With two faults only the first check reports."""
    values = {**HEATING, "tvbh": 31.0, "bypass_valve": 100.0}
    detection = ErrorDetection(ErrorSettings())
    assert _run(detection, values, 11) is Finding.DHW_VALVE_DEFECT


def test_low_spread() -> None:
    """A spread below the minimum while the compressor runs is reported."""
    values = {**HEATING, "temperature_spread": 0.5}
    detection = ErrorDetection(ErrorSettings())
    assert _run(detection, values, 20) is None
    assert _run(detection, values, 21) is Finding.LOW_TEMPERATURE_SPREAD


def test_low_spread_rests_after_a_good_case() -> None:
    """After a good case the spread check waits for a change of the conditions."""
    detection = ErrorDetection(ErrorSettings())
    detection.evaluate(HEATING, 0)
    low = {**HEATING, "temperature_spread": 0.5}
    assert _run(detection, low, 30) is None
    detection.changed("tv")
    assert _run(detection, low, 30) is None
    detection.changed("status_kompressor")
    assert _run(detection, low, 21) is Finding.LOW_TEMPERATURE_SPREAD
    detection.changed("mode_of_operating")
    assert detection.evaluate(low, 0) is None


def test_spread_not_checked_without_compressor() -> None:
    """The spread is only checked in heating or hot water with the compressor on."""
    values = {**HEATING, "temperature_spread": 0.5, "status_kompressor": False}
    assert _run(ErrorDetection(ErrorSettings()), values, 30) is None
    values = {**HEATING, "temperature_spread": 0.5, "mode_of_operating": "cooling"}
    assert _run(ErrorDetection(ErrorSettings()), values, 30) is None


@pytest.mark.parametrize(
    "change",
    [{"flow_rate": 0.0}, {"status_kompressor": False}, {"dhw_mixer_position": 0.0}],
)
def test_missing_flow(change: dict[str, object]) -> None:
    """A cold tank in hot water mode without flow is reported after 5 minutes."""
    values = {
        **HEATING,
        "mode_of_operating": "hot_water",
        "tdhw1": 45.0,
        "dhw_mixer_position": 50.0,
        **change,
    }
    detection = ErrorDetection(ErrorSettings())
    assert _run(detection, values, 5) is None
    assert _run(detection, values, 6) is Finding.MISSING_FLOW


def test_unknown_values_give_no_finding() -> None:
    """Checks with unknown inputs find nothing."""
    assert _run(ErrorDetection(ErrorSettings()), {}, 30) is None


# --------------------------------------------------------------- defrost


@pytest.mark.parametrize("mode", ["heating", "lowering", "automatic_1", "automatic_2"])
def test_defrost_from_heating(mode: str) -> None:
    """Defrosting from heating switches to summer and back."""
    optimizer = DefrostOptimizer()
    assert optimizer.operating_state_changed("heating", "defrosting", mode) == "summer"
    assert optimizer.saved == mode
    assert optimizer.operating_state_changed("defrosting", "heating", "summer") == mode
    assert optimizer.saved == "standby"


def test_defrost_from_hot_water() -> None:
    """Defrosting during hot water goes back to the mode after the defrost."""
    optimizer = DefrostOptimizer()
    assert optimizer.operating_state_changed("hot_water", "defrosting", "heating") == (
        "summer"
    )
    assert (
        optimizer.operating_state_changed("defrosting", "hot_water", "summer")
        == "heating"
    )


def test_defrost_to_standby() -> None:
    """Defrost followed by standby restores the mode too."""
    optimizer = DefrostOptimizer()
    optimizer.operating_state_changed("heating", "defrosting", "automatic_1")
    assert (
        optimizer.operating_state_changed("defrosting", "standby", "summer")
        == "automatic_1"
    )


def test_defrost_not_touched() -> None:
    """Modes the user picked are left alone."""
    optimizer = DefrostOptimizer()
    # Summer chosen by the user: nothing to do on defrost.
    assert optimizer.operating_state_changed("heating", "defrosting", "summer") is None
    # Defrost -> hot water with nothing remembered.
    assert (
        optimizer.operating_state_changed("defrosting", "hot_water", "summer") is None
    )
    # Defrost -> heating in summer without remembered mode: standby, as before.
    assert (
        optimizer.operating_state_changed("defrosting", "heating", "summer")
        == "standby"
    )
    # No change while the mode is not summer.
    assert optimizer.operating_state_changed("defrosting", "heating", "heating") is None
    # Unknown previous state.
    assert optimizer.operating_state_changed(None, "defrosting", "heating") is None


def test_user_mode_change_forgets_saved_mode() -> None:
    """A non-heating mode chosen outside defrosting drops the remembered mode."""
    optimizer = DefrostOptimizer()
    optimizer.operating_state_changed("heating", "defrosting", "heating")
    optimizer.operating_mode_changed("summer", "defrosting")
    assert optimizer.saved == "heating"
    optimizer.operating_mode_changed("heating", "heating")
    assert optimizer.saved == "heating"
    optimizer.operating_mode_changed("standby", "heating")
    assert optimizer.saved == "standby"
