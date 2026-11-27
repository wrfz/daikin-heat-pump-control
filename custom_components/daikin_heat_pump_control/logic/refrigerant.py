"""Subcooling and discharge superheat of the refrigerant circuit.

The values are only meaningful while heating with the compressor running:
then the pressure sensor of the outdoor unit is on the high pressure side.
The indoor unit repeats the outdoor unit frame between two updates, so a
value is computed once per new outdoor unit frame; after a start or a
defrost the first new frame counts. Values that become known for the first
time after the start (another register read later) belong to the frame from
before the start.
"""

from collections.abc import Collection, Mapping
from dataclasses import dataclass
from typing import Final

COMPRESSOR: Final = "inv_freq"
DEFROST: Final = "defrost_operation"
FOUR_WAY_VALVE: Final = "4_way_valve"
MODE: Final = "mode_of_operating"
SATURATION: Final = "saturation_temp"
LIQUID: Final = "t_liq"
DISCHARGE: Final = "temp_after_compr"
SUBCOOLING: Final = "subcooling"
SUPERHEAT: Final = "discharge_superheat"

# Values of one outdoor unit frame; a change of any of them is a new frame.
FINGERPRINT: Final = (
    "outdoor_temp",
    DISCHARGE,
    "exch_temp",
    "heat_sink_temp",
    SATURATION,
)
STATE_INPUTS: Final = (COMPRESSOR, DEFROST, FOUR_WAY_VALVE, MODE)
INPUTS: Final = (*STATE_INPUTS, *FINGERPRINT, LIQUID)
# Updating one of these runs the state check, the others the computation.
STATE_TRIGGERS: Final = frozenset({COMPRESSOR, DEFROST, FOUR_WAY_VALVE})
CIRCUIT_TRIGGERS: Final = frozenset(FINGERPRINT)


@dataclass(frozen=True, slots=True)
class CircuitValues:
    """Subcooling and discharge superheat in K (None: no value)."""

    subcooling: float | None
    superheat: float | None


NO_VALUES: Final = CircuitValues(None, None)


def _number(states: Mapping[str, object], key: str) -> float | None:
    value = states.get(key)
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _difference(first: float | None, second: float | None) -> float | None:
    if first is None or second is None:
        return None
    return round(first - second, 2)


class RefrigerantCircuit:
    """Compute subcooling and superheat from the outdoor unit values."""

    def __init__(self, present: Collection[str]) -> None:
        """Initialize for the values the unit has (`present`)."""
        self._present = frozenset(present)
        self._heating = False
        self._settling = False
        self._fingerprint: tuple[object, ...] | None = None

    def reset(self) -> None:
        """Forget the state, e.g. after the connection was lost."""
        self._heating = False
        self._settling = False
        self._fingerprint = None

    def _is_heating(self, states: Mapping[str, object]) -> bool:
        if COMPRESSOR in self._present:
            speed = _number(states, COMPRESSOR)
            if speed is None or speed <= 0:
                return False
        if DEFROST in self._present and states.get(DEFROST) is True:
            return False
        if FOUR_WAY_VALVE in self._present:
            return states.get(FOUR_WAY_VALVE) == "heating"
        return states.get(MODE) != "cooling"

    def _current(self, states: Mapping[str, object]) -> tuple[object, ...]:
        return tuple(states.get(key) for key in FINGERPRINT)

    def update_state(self, states: Mapping[str, object]) -> CircuitValues | None:
        """Check whether the circuit heats; return NO_VALUES when it does not.

        Returns None when the values stay as they are.
        """
        heating = self._is_heating(states)
        if heating and not self._heating:
            # The frame at the start still shows the values from before.
            self._fingerprint = self._current(states)
            self._settling = True
        self._heating = heating
        return None if heating else NO_VALUES

    def update_circuit(self, states: Mapping[str, object]) -> CircuitValues | None:
        """Compute the values for a new outdoor unit frame.

        Returns None when the values stay as they are.
        """
        if (result := self.update_state(states)) is not None:
            return result
        fingerprint = self._current(states)
        previous = self._fingerprint
        if fingerprint == previous:
            return None
        self._fingerprint = fingerprint
        if (
            self._settling
            and previous is not None
            and all(
                old is None or old == new
                for old, new in zip(previous, fingerprint, strict=True)
            )
        ):
            return None
        self._settling = False
        saturation = _number(states, SATURATION)
        return CircuitValues(
            subcooling=_difference(saturation, _number(states, LIQUID)),
            superheat=_difference(_number(states, DISCHARGE), saturation),
        )
