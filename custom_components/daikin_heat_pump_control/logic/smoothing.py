"""Smoothing of noisy computed values.

The smoothed value follows the raw value with a PID step at most every
`period` seconds. The P error and the derivative are low-pass filtered and
the integral is limited, so that a single outlier moves the result only a
little. The result is rounded to 0.01 and fed back into the next step.
"""

from dataclasses import dataclass
import math
from typing import Final

SMOOTHING_PERIOD: Final = 10.0
GAIN_P: Final = 0.2
GAIN_I: Final = 0.05
GAIN_D: Final = 0.05
MAX_INTEGRAL: Final = 0.2
FILTER_P: Final = 0.2
FILTER_D: Final = 0.1


def round_half_away(value: float, decimals: int = 2) -> float:
    """Round like C's round(): halves away from zero."""
    factor = float(10**decimals)
    return math.copysign(math.floor(abs(value) * factor + 0.5), value) / factor


@dataclass(slots=True)
class _Pid:
    filtered_p: float = 0.0
    filtered_d: float = 0.0
    integral: float = 0.0
    previous_error: float = 0.0

    def step(self, setpoint: float, current: float, dt: float) -> float:
        error = setpoint - current
        self.filtered_p = FILTER_P * error + (1 - FILTER_P) * self.filtered_p
        self.integral = max(
            -MAX_INTEGRAL, min(MAX_INTEGRAL, self.integral + error * dt)
        )
        derivative = (error - self.previous_error) / dt
        self.filtered_d = FILTER_D * derivative + (1 - FILTER_D) * self.filtered_d
        self.previous_error = error
        return (
            GAIN_P * self.filtered_p + GAIN_I * self.integral + GAIN_D * self.filtered_d
        )


class Smoother:
    """Follow a raw value slowly."""

    def __init__(self, period: float = SMOOTHING_PERIOD) -> None:
        """Initialize the smoother; `period` is the minimum time between steps in s."""
        self._period = period
        self.reset()

    def reset(self) -> None:
        """Start again without history."""
        self._pid = _Pid()
        self._last_step: float = 0.0
        self.raw: float | None = None
        self.value: float | None = None

    def set_raw(self, raw: float | None) -> None:
        """Set the latest raw value."""
        self.raw = raw

    def update(self, now: float) -> bool:
        """Run a step if due; return True if the smoothed value was updated.

        `now` is a monotonic time in s; the first step happens once `now`
        exceeds the period.
        """
        raw = self.raw
        if raw is None or not math.isfinite(raw):
            return False
        dt = now - self._last_step
        if dt <= self._period:
            return False
        current = raw if self.value is None else self.value
        current += self._pid.step(raw, current, dt)
        self._last_step = now
        self.value = round_half_away(current)
        return True
