"""Values computed from other values."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, tzinfo
from typing import Final

SPECIFIC_HEAT_WATER: Final = 4.19  # kJ/(kg K), 1 L of water taken as 1 kg


def thermal_power(tv: float, tr: float, flow_rate: float) -> float:
    """Return the thermal power in kW from flow/return in °C and flow in L/h."""
    return round((tv - tr) * SPECIFIC_HEAT_WATER * flow_rate / 3600.0, 3)


def difference(minuend: float, subtrahend: float) -> float:
    """Return the difference of two temperatures."""
    return round(minuend - subtrahend, 2)


@dataclass(frozen=True, slots=True, kw_only=True)
class Derived:
    """A value computed whenever one of its inputs changes."""

    key: str
    inputs: tuple[str, ...]
    function: Callable[..., float]
    smoothed: str | None = None

    def compute(self, values: Mapping[str, object]) -> float | None:
        """Return the value, or None while an input is unknown."""
        arguments: list[float] = []
        for key in self.inputs:
            value = values.get(key)
            if not isinstance(value, float | int) or isinstance(value, bool):
                return None
            arguments.append(float(value))
        return self.function(*arguments)


DERIVED: Final[tuple[Derived, ...]] = (
    Derived(
        key="thermal_power_raw",
        inputs=("tv", "tr", "flow_rate"),
        function=thermal_power,
        smoothed="thermal_power",
    ),
    Derived(
        key="temperature_spread_raw",
        inputs=("tv", "tr"),
        function=difference,
        smoothed="temperature_spread",
    ),
    Derived(key="tv_tvbh_delta", inputs=("tv", "tvbh"), function=difference),
    Derived(key="tvbh_tr_delta", inputs=("tvbh", "tr"), function=difference),
    Derived(
        key="vorlauf_soll_tv_delta",
        inputs=("target_supply_temperature", "tv"),
        function=difference,
    ),
)

SMOOTHED: Final[dict[str, Derived]] = {
    derived.smoothed: derived for derived in DERIVED if derived.smoothed is not None
}


def system_time(parts: Mapping[str, object], tz: tzinfo) -> datetime | None:
    """Return the clock of the controller from its date and time registers."""
    keys = (
        "system_date_year",
        "system_date_month",
        "system_date_day",
        "system_time_hour",
        "system_time_minute",
        "system_time_second",
    )
    numbers: list[int] = []
    for key in keys:
        value = parts.get(key)
        if not isinstance(value, float | int) or isinstance(value, bool):
            return None
        numbers.append(int(value))
    year, month, day, hour, minute, second = numbers
    try:
        return datetime(2000 + year, month, day, hour, minute, second, tzinfo=tz)
    except ValueError:
        return None


class WindowMax:
    """Highest value between two publications of a value read more often."""

    def __init__(self) -> None:
        """Initialize the window."""
        self.maximum: float | None = None
        self.last_publish: int | None = None

    def reset(self) -> None:
        """Forget the window."""
        self.maximum = None
        self.last_publish = None

    def add(self, value: float, now: int, interval: int) -> float | None:
        """Add a reading; return the window maximum when the value is to be published."""
        self.maximum = value if self.maximum is None else max(self.maximum, value)
        if self.last_publish is not None and now - self.last_publish < interval:
            return None
        maximum = self.maximum
        self.maximum = None
        self.last_publish = now
        return maximum
