"""Findings added to the error code of the controller.

Four checks look for faults the controller does not report itself. They run
whenever the error code is read; the first check that has seen its fault for
longer than its holding time gives the finding, the later checks are not
evaluated then. Times are milliseconds of a monotonic clock.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
import math
from typing import Final

MINUTE_MS: Final = 60_000
MIN_FLOW: Final = 600.0  # L/h
DHW_LOADED: Final = 48.0  # °C

# Inputs of the checks.
INPUTS: Final = (
    "tv",
    "tvbh",
    "tr",
    "flow_rate",
    "dhw_mixer_position",
    "bypass_valve",
    "mode_of_operating",
    "status_kompressor",
    "tdhw1",
    "temperature_spread",
)
OPERATING_STATE: Final = "mode_of_operating"
COMPRESSOR: Final = "status_kompressor"


class Finding(StrEnum):
    """A fault found by the checks."""

    DHW_VALVE_DEFECT = "dhw_valve_defect"
    BYPASS_VALVE_DEFECT = "bypass_valve_defect"
    LOW_TEMPERATURE_SPREAD = "low_temperature_spread"
    MISSING_FLOW = "missing_flow"


@dataclass(frozen=True, slots=True, kw_only=True)
class ErrorSettings:
    """Sensor offsets and spread limits of the checks."""

    tv_offset: float = 0.0
    tvbh_offset: float = 0.0
    tr_offset: float = 0.0
    max_spread_tvbh_tv: float = 0.3
    max_spread_tvbh_tr: float = 0.3


def min_spread(tv: float) -> float:
    """Return the lowest plausible spread in heating at a flow temperature.

    Fitted to 50 °C -> 4.0 K, 40 °C -> 3.0 K, 35 °C -> 2.5 K, 29 °C -> 1.2 K
    and 27 °C -> 0.3 K.
    """
    return (
        -0.00004012 * tv**4
        + 0.006683 * tv**3
        - 0.4152 * tv**2
        + 11.5006 * tv
        - 117.7908
    )


class Detector:
    """Report a fault once it was seen for longer than the holding time."""

    def __init__(self, hold_ms: int, *, rest_after_good: bool = False) -> None:
        """Initialize; with `rest_after_good` a good case stops the detection."""
        self._hold_ms = hold_ms
        self._rest_after_good = rest_after_good
        self._since: int | None = None
        self._resting = False

    @property
    def since(self) -> int | None:
        """Return when the fault was first seen."""
        return self._since

    def check(self, fault: bool, now: int) -> bool:
        """Feed one observation; return True if the fault is confirmed."""
        if not fault:
            self._since = None
            self._resting = self._rest_after_good
            return False
        if self._since is None and not self._resting:
            self._since = now
        return self._since is not None and now - self._since > self._hold_ms

    def wake(self) -> None:
        """Start the detection again after a change of the conditions."""
        self._since = None
        self._resting = False


def _number(values: Mapping[str, object], key: str) -> float:
    """Return a value as number; NaN while unknown, so every comparison fails."""
    value = values.get(key)
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, int | float):
        return float(value)
    return math.nan


class ErrorDetection:
    """The four checks with their holding times."""

    def __init__(self, settings: ErrorSettings) -> None:
        """Initialize the checks."""
        self.settings = settings
        self.dhw_valve = Detector(10 * MINUTE_MS)
        self.bypass_valve = Detector(10 * MINUTE_MS)
        self.spread = Detector(20 * MINUTE_MS, rest_after_good=True)
        self.dhw_flow = Detector(5 * MINUTE_MS)

    def changed(self, key: str) -> None:
        """Take note of a change of an input."""
        if key in (OPERATING_STATE, COMPRESSOR):
            self.spread.wake()

    def evaluate(self, values: Mapping[str, object], now: int) -> Finding | None:
        """Run the checks with the current values; return the first finding."""
        settings = self.settings
        tv = _number(values, "tv")
        tv_corrected = tv + settings.tv_offset
        tvbh = _number(values, "tvbh") + settings.tvbh_offset
        tr = _number(values, "tr") + settings.tr_offset
        flow = _number(values, "flow_rate")
        mixer = _number(values, "dhw_mixer_position")
        state = values.get(OPERATING_STATE)
        compressor = values.get(COMPRESSOR) is True

        fault = (
            flow > MIN_FLOW
            and mixer == 0
            and abs(tvbh - tv_corrected) > settings.max_spread_tvbh_tv
        )
        if self.dhw_valve.check(fault, now):
            return Finding.DHW_VALVE_DEFECT

        fault = (
            flow > MIN_FLOW
            and _number(values, "bypass_valve") == 100
            and abs(tvbh - tr) > settings.max_spread_tvbh_tr
        )
        if self.bypass_valve.check(fault, now):
            return Finding.BYPASS_VALVE_DEFECT

        if state in ("hot_water", "heating") and compressor:
            fault = _number(values, "temperature_spread") < min_spread(tv)
            if self.spread.check(fault, now):
                return Finding.LOW_TEMPERATURE_SPREAD

        fault = (
            state == "hot_water"
            and _number(values, "tdhw1") < DHW_LOADED
            and (flow == 0 or mixer == 0 or not compressor)
        )
        if self.dhw_flow.check(fault, now):
            return Finding.MISSING_FLOW
        return None
