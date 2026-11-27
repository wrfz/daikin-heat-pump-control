"""Saturation temperature of the refrigerant from the measured pressure."""

from bisect import bisect_left
from enum import StrEnum
from typing import Final

from . import saturation_tables

# The pressure sensor of the outdoor unit measures gauge pressure.
AMBIENT_PRESSURE: Final = 1.01325  # bar


class Refrigerant(StrEnum):
    """Refrigerant of an outdoor unit."""

    R32 = "R32"
    R410A = "R410A"


_TABLES: Final[dict[Refrigerant, tuple[float, ...]]] = {
    Refrigerant.R32: saturation_tables.R32,
    Refrigerant.R410A: saturation_tables.R410A,
}


def saturation_temperature(
    refrigerant: Refrigerant, pressure_bar_g: float, decimals: int | None = 1
) -> float | None:
    """Return the saturation temperature in °C for a gauge pressure in bar.

    The bubble point pressure table is interpolated linearly; outside the table
    (-65 to +71 °C) there is no value. The result is rounded to `decimals`
    (0.1 K by default, not rounded with None).
    """
    table = _TABLES[refrigerant]
    pressure = pressure_bar_g + AMBIENT_PRESSURE
    if not table[0] <= pressure <= table[-1]:
        return None
    index = max(bisect_left(table, pressure), 1)
    low, high = table[index - 1], table[index]
    position = index - 1 + (pressure - low) / (high - low)
    temperature = (
        saturation_tables.FIRST_TEMPERATURE
        + position * saturation_tables.TEMPERATURE_STEP
    )
    return temperature if decimals is None else round(temperature, decimals)
