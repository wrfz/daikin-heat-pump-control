"""Optimized defrosting.

While the outdoor unit defrosts, the controller takes heat from the heating
circuit. In operating mode "summer" the bypass valve is open, so less heat is
taken from the floor. The optimizer switches a heating-like mode to summer when
defrosting starts and back to the remembered mode when it ends. The
remembered mode is kept in memory only.
"""

from typing import Final

STANDBY: Final = "standby"
HEATING: Final = "heating"
DEFROSTING: Final = "defrosting"
HOT_WATER: Final = "hot_water"
SUMMER: Final = "summer"
HEATING_LIKE: Final = frozenset({"heating", "lowering", "automatic_1", "automatic_2"})

# Value of the antifreeze temperature the optimization needs.
ANTIFREEZE_OFF: Final = "off"


class DefrostOptimizer:
    """Decide the operating mode around a defrost cycle."""

    def __init__(self) -> None:
        """Initialize with nothing remembered."""
        self.saved = STANDBY

    def operating_state_changed(
        self, previous: str | None, current: str | None, mode: str | None
    ) -> str | None:
        """Handle a change of the operating state; return the mode to set."""
        heating_like = mode in HEATING_LIKE
        new_mode = mode
        if current == DEFROSTING and previous in (HEATING, HOT_WATER) and heating_like:
            new_mode = SUMMER
        elif (
            previous == DEFROSTING
            and mode == SUMMER
            and (
                current in (HEATING, STANDBY)
                or (current == HOT_WATER and self.saved in HEATING_LIKE)
            )
        ):
            new_mode = self.saved
            self.saved = STANDBY
        if new_mode == mode:
            return None
        if current == DEFROSTING and heating_like:
            self.saved = mode or STANDBY
        return new_mode

    def operating_mode_changed(self, mode: str | None, state: str | None) -> None:
        """Forget the remembered mode when the user picks a mode outside defrosting."""
        if mode not in HEATING_LIKE and state != DEFROSTING:
            self.saved = STANDBY
