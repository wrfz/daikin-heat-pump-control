"""State of the CAN values and their distribution to the entities."""

from collections import defaultdict
from collections.abc import Iterable, Mapping
from datetime import datetime
import logging
from typing import Any, Final

from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.util import dt as dt_util

from .bridge.node import CanChannel
from .bridge.protocol import CanExchangeResult
from .can.scheduler import CanScheduler
from .can.table import (
    CAN_VALUES,
    CAN_VALUES_BY_KEY,
    SYSTEM_TIME_PARTS,
    Decoded,
    Group,
    Platform,
)
from .const import (
    CONF_GROUP_INTERVAL_PREFIX,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    TV_MAX_POLL_INTERVAL,
)
from .logic.derived import DERIVED, SMOOTHED, Derived, WindowMax, system_time
from .logic.smoothing import Smoother

_LOGGER = logging.getLogger(__name__)

TV: Final = "tv"
TV_MAX: Final = "tv_max"
SYSTEM_TIME: Final = "system_time"

type CanState = float | bool | str | datetime | None

# Computed entities that are disabled by default.
COMPUTED_DISABLED_BY_DEFAULT: Final = frozenset(
    {"thermal_power_raw", "temperature_spread_raw", SYSTEM_TIME}
)


def computed_keys() -> list[str]:
    """Return the keys of the computed entities."""
    keys = [derived.key for derived in DERIVED]
    keys.extend(SMOOTHED)
    keys.extend((TV_MAX, SYSTEM_TIME))
    return keys


def entity_defaults() -> dict[str, bool]:
    """Return the key of every CAN entity and whether it is enabled by default."""
    defaults = {
        value.key: value.enabled_default
        for value in CAN_VALUES
        if value.platform is not Platform.INTERNAL
    }
    defaults.update(
        {key: key not in COMPUTED_DISABLED_BY_DEFAULT for key in computed_keys()}
    )
    return defaults


def group_option(group: Group) -> str:
    """Return the option key of a group interval."""
    return f"{CONF_GROUP_INTERVAL_PREFIX}{group}"


def polling_intervals(options: Mapping[str, Any]) -> dict[str, float]:
    """Return the polling interval in s of every CAN value."""
    default = float(options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))
    intervals: dict[str, float] = {}
    for value in CAN_VALUES:
        group = options.get(group_option(value.group))
        if group is not None:
            intervals[value.key] = float(group)
        elif value.interval is not None:
            intervals[value.key] = value.interval
        else:
            intervals[value.key] = default
    return intervals


def needed_values(active: Iterable[str]) -> set[str]:
    """Return the table keys to poll for the given active entity keys."""
    active = set(active)
    needed = {key for key in active if key in CAN_VALUES_BY_KEY}
    for derived in DERIVED:
        if derived.key in active or derived.smoothed in active:
            needed.update(derived.inputs)
    if SYSTEM_TIME in active:
        needed.update(SYSTEM_TIME_PARTS)
    if TV_MAX in active:
        needed.add(TV)
    return needed


class CanCoordinator:
    """Poll the CAN values over a bridge channel and keep their states."""

    def __init__(
        self,
        hass: HomeAssistant,
        channel: CanChannel,
        *,
        active: Iterable[str],
        intervals: Mapping[str, float],
    ) -> None:
        """Initialize the coordinator for the given active entity keys."""
        self.hass = hass
        self.channel = channel
        active = set(active)
        needed = needed_values(active)
        poll_intervals = dict(intervals)
        self._tv_window: WindowMax | None = None
        self._tv_publish_ms = round(intervals[TV] * 1000)
        if TV_MAX in active:
            self._tv_window = WindowMax()
            poll_intervals[TV] = min(intervals[TV], TV_MAX_POLL_INTERVAL)
        self.scheduler = CanScheduler(
            (value for value in CAN_VALUES if value.key in needed), poll_intervals
        )
        self._derived: dict[str, list[Derived]] = defaultdict(list)
        for derived in DERIVED:
            if derived.key in active or derived.smoothed in active:
                for key in derived.inputs:
                    self._derived[key].append(derived)
        self._smoothers: dict[str, Smoother] = {
            key: Smoother() for key in SMOOTHED if key in active
        }
        self._system_time = SYSTEM_TIME in active
        self._states: dict[str, CanState] = {}
        self._raw: dict[str, int] = {}
        self._updated: dict[str, int] = {}
        self._listeners: dict[str, list[CALLBACK_TYPE]] = defaultdict(list)
        self._available = channel.available

    @property
    def available(self) -> bool:
        """Return True while the bus can be used."""
        return self.channel.available

    def state(self, key: str) -> CanState:
        """Return the current state of a value."""
        return self._states.get(key)

    def raw(self, key: str) -> int | None:
        """Return the last raw value of a table value."""
        return self._raw.get(key)

    @callback
    def async_start(self) -> CALLBACK_TYPE:
        """Follow the exchanges and the availability of the channel."""
        unsub_result = self.channel.async_add_listener(self._handle_result)
        unsub_node = self.channel.node.async_add_listener(self._handle_node)

        @callback
        def _stop() -> None:
            unsub_result()
            unsub_node()

        return _stop

    @callback
    def async_add_listener(self, key: str, listener: CALLBACK_TYPE) -> CALLBACK_TYPE:
        """Register a listener for changes of a value."""
        self._listeners[key].append(listener)

        @callback
        def _remove() -> None:
            self._listeners[key].remove(listener)

        return _remove

    @callback
    def _notify(self, keys: Iterable[str]) -> None:
        for key in keys:
            for listener in list(self._listeners.get(key, ())):
                listener()

    @callback
    def _handle_node(self) -> None:
        available = self.channel.available
        if available == self._available:
            return
        self._available = available
        if not available:
            self._reset()
        self._notify(list(self._listeners))

    def _reset(self) -> None:
        self.scheduler.reset()
        self._states.clear()
        self._raw.clear()
        self._updated.clear()
        for smoother in self._smoothers.values():
            smoother.reset()
        if self._tv_window is not None:
            self._tv_window.reset()

    @callback
    def _handle_result(self, result: CanExchangeResult) -> None:
        clock = self.channel.clock
        now = clock.extend(result.now)
        changed: set[str] = set()
        for item in result.sent:
            self.scheduler.handle_sent(clock.extend(item.timestamp), item.frame)
        for item in result.received:
            timestamp = clock.extend(item.timestamp)
            match = self.scheduler.handle_frame(timestamp, item.frame)
            if match is None:
                continue
            value, decoded = match
            if decoded is None:
                _LOGGER.debug(
                    "Implausible value for %s: %s", value.key, item.frame.encode()
                )
                continue
            self._apply(value.key, decoded, timestamp, changed)
        for key, smoother in self._smoothers.items():
            if smoother.update(now / 1000):
                self._set(key, smoother.value, changed)
        self._notify(changed)
        if self.channel.available and (frame := self.scheduler.next_request(now)):
            self.channel.async_send([frame])

    def _apply(
        self, key: str, decoded: Decoded, timestamp: int, changed: set[str]
    ) -> None:
        self._updated[key] = timestamp
        if self._raw.get(key) != decoded.raw:
            self._raw[key] = decoded.raw
            changed.add(key)
        state = decoded.state
        if key == TV and self._tv_window is not None and isinstance(state, float):
            maximum = self._tv_window.add(state, timestamp, self._tv_publish_ms)
            if maximum is None:
                return
            self._set(TV_MAX, maximum, changed)
        self._set(key, state, changed)
        if self._system_time and key in SYSTEM_TIME_PARTS:
            self._set(
                SYSTEM_TIME,
                system_time(self._states, dt_util.get_default_time_zone()),
                changed,
            )

    def _set(self, key: str, state: CanState, changed: set[str]) -> None:
        if key in self._states and self._states[key] == state:
            return
        self._states[key] = state
        changed.add(key)
        for derived in self._derived.get(key, ()):
            value = derived.compute(self._states)
            self._set(derived.key, value, changed)
            if derived.smoothed in self._smoothers:
                self._smoothers[derived.smoothed].set_raw(value)

    def diagnostics(self) -> dict[str, Any]:
        """Return the values and the scheduler state."""

        def _plain(state: CanState) -> Any:
            return state.isoformat() if isinstance(state, datetime) else state

        return {
            "available": self.available,
            "values": {
                key: {
                    "state": _plain(state),
                    "raw": f"{self._raw[key]:04X}" if key in self._raw else None,
                    "updated": self._updated.get(key),
                }
                for key, state in sorted(self._states.items())
            },
            "scheduler": self.scheduler.diagnostics(),
        }
