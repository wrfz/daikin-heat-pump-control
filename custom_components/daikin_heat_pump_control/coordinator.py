"""State of the CAN values, their distribution to the entities and writing."""

import asyncio
from collections import defaultdict
from collections.abc import Iterable, Mapping
from datetime import datetime
import logging
import math
from typing import Any, Final

from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.event import async_track_time_change
from homeassistant.util import dt as dt_util

from .bridge.node import CanChannel
from .bridge.protocol import CanExchangeResult, CanFrame
from .can.scheduler import CanScheduler, Done, Job, Outcome
from .can.table import (
    CAN_VALUES,
    CAN_VALUES_BY_KEY,
    SYSTEM_TIME_PARTS,
    Decoded,
    Group,
    Platform,
    StateValue,
)
from .const import (
    CONF_GROUP_INTERVAL_PREFIX,
    CONF_MAX_SPREAD_TVBH_TR,
    CONF_MAX_SPREAD_TVBH_TV,
    CONF_SCAN_INTERVAL,
    CONF_TR_OFFSET,
    CONF_TV_OFFSET,
    CONF_TVBH_OFFSET,
    DEFAULT_MAX_SPREAD,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    TV_MAX_POLL_INTERVAL,
)
from .logic.defrost import ANTIFREEZE_OFF, DefrostOptimizer
from .logic.derived import DERIVED, SMOOTHED, Derived, WindowMax, system_time
from .logic.errors import INPUTS as ERROR_INPUTS, ErrorDetection, ErrorSettings, Finding
from .logic.smoothing import Smoother
from .storage import CanStorage

_LOGGER = logging.getLogger(__name__)

TV: Final = "tv"
TV_MAX: Final = "tv_max"
SYSTEM_TIME: Final = "system_time"
ERROR_CODE: Final = "error_code"
TEMPERATURE_SPREAD: Final = "temperature_spread"
OPERATING_STATE: Final = "mode_of_operating"
OPERATING_MODE: Final = "operating_mode"
ANTIFREEZE: Final = "temperature_antifreeze"
HOT_WATER_SETPOINT: Final = "target_hot_water_temperature_1"
OPTIMIZED_DEFROSTING: Final = "optimized_defrosting"
DHW_RUN: Final = "dhw_run"
WRITES_TODAY: Final = "writes_today"

DHW_RUN_TEMPERATURE: Final = 70.0
# Upper limit for a write including the wait in the queue.
WRITE_TIMEOUT: Final = 30.0

type CanState = float | bool | str | datetime | None

# Computed entities that are disabled by default.
COMPUTED_DISABLED_BY_DEFAULT: Final = frozenset(
    {"thermal_power_raw", "temperature_spread_raw", SYSTEM_TIME}
)

# Values the extra entities and the checks of the error code need.
EXTRA_INPUTS: Final[dict[str, tuple[str, ...]]] = {
    OPTIMIZED_DEFROSTING: (OPERATING_MODE, OPERATING_STATE, ANTIFREEZE),
    DHW_RUN: (HOT_WATER_SETPOINT,),
    ERROR_CODE: tuple(key for key in ERROR_INPUTS if key in CAN_VALUES_BY_KEY),
}


def computed_keys() -> list[str]:
    """Return the keys of the computed and extra entities."""
    keys = [derived.key for derived in DERIVED]
    keys.extend(SMOOTHED)
    keys.extend((TV_MAX, SYSTEM_TIME, OPTIMIZED_DEFROSTING, DHW_RUN, WRITES_TODAY))
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


def error_settings(options: Mapping[str, Any]) -> ErrorSettings:
    """Return the settings of the error code checks."""
    return ErrorSettings(
        tv_offset=float(options.get(CONF_TV_OFFSET, 0.0)),
        tvbh_offset=float(options.get(CONF_TVBH_OFFSET, 0.0)),
        tr_offset=float(options.get(CONF_TR_OFFSET, 0.0)),
        max_spread_tvbh_tv=float(
            options.get(CONF_MAX_SPREAD_TVBH_TV, DEFAULT_MAX_SPREAD)
        ),
        max_spread_tvbh_tr=float(
            options.get(CONF_MAX_SPREAD_TVBH_TR, DEFAULT_MAX_SPREAD)
        ),
    )


def expand_active(active: Iterable[str]) -> set[str]:
    """Add the computed values the logic needs to the active entity keys."""
    active = set(active)
    if ERROR_CODE in active:
        active.add(TEMPERATURE_SPREAD)
    return active


def needed_values(active: Iterable[str]) -> set[str]:
    """Return the table keys to poll for the given active entity keys."""
    active = expand_active(active)
    needed = {key for key in active if key in CAN_VALUES_BY_KEY}
    for derived in DERIVED:
        if derived.key in active or derived.smoothed in active:
            needed.update(derived.inputs)
    if SYSTEM_TIME in active:
        needed.update(SYSTEM_TIME_PARTS)
    if TV_MAX in active:
        needed.add(TV)
    for key, inputs in EXTRA_INPUTS.items():
        if key in active:
            needed.update(inputs)
    return needed


def _same(first: object, second: object) -> bool:
    if isinstance(first, float) and isinstance(second, float):
        return math.isclose(first, second, abs_tol=1e-6)
    return first == second


class CanCoordinator:
    """Poll the CAN values over a bridge channel, keep their states and write."""

    def __init__(
        self,
        hass: HomeAssistant,
        channel: CanChannel,
        *,
        active: Iterable[str],
        intervals: Mapping[str, float],
        storage: CanStorage,
        settings: ErrorSettings | None = None,
    ) -> None:
        """Initialize the coordinator for the given active entity keys."""
        self.hass = hass
        self.channel = channel
        self.storage = storage
        active = expand_active(active)
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
        self._errors = (
            ErrorDetection(settings or ErrorSettings())
            if ERROR_CODE in active
            else None
        )
        self.finding: Finding | None = None
        self._defrost = DefrostOptimizer() if OPTIMIZED_DEFROSTING in active else None
        self._states: dict[str, CanState] = {}
        self._raw: dict[str, int] = {}
        self._updated: dict[str, int] = {}
        self._listeners: dict[str, list[CALLBACK_TYPE]] = defaultdict(list)
        self._available = channel.available

    @property
    def available(self) -> bool:
        """Return True while the bus can be used."""
        return self.channel.available

    @property
    def optimized_defrosting(self) -> bool:
        """Return True while the defrost optimization is on."""
        return self.storage.optimized_defrosting

    def state(self, key: str) -> CanState:
        """Return the current state of a value."""
        return self._states.get(key)

    def raw(self, key: str) -> int | None:
        """Return the last raw value of a table value."""
        return self._raw.get(key)

    @callback
    def async_start(self) -> CALLBACK_TYPE:
        """Follow the exchanges, the availability of the channel and the day."""
        unsub_result = self.channel.async_add_listener(self._handle_result)
        unsub_node = self.channel.node.async_add_listener(self._handle_node)
        unsub_midnight = async_track_time_change(
            self.hass, self._handle_midnight, hour=0, minute=0, second=0
        )

        @callback
        def _stop() -> None:
            unsub_result()
            unsub_node()
            unsub_midnight()

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
    def _handle_midnight(self, _now: datetime) -> None:
        self._notify((WRITES_TODAY,))

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
        self.finding = None
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
            key = self.scheduler.handle_sent(clock.extend(item.timestamp), item.frame)
            if key is not None:
                self.storage.record_write(key)
                changed.add(WRITES_TODAY)
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
        if self.channel.available and (frames := self.scheduler.next_request(now)):
            self.channel.async_send(frames)

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
        if key == ERROR_CODE and self._errors is not None:
            self._check_errors(timestamp, changed)

    def _set(self, key: str, state: CanState, changed: set[str]) -> None:
        previous = self._states.get(key)
        if key in self._states and previous == state:
            return
        self._states[key] = state
        changed.add(key)
        for derived in self._derived.get(key, ()):
            value = derived.compute(self._states)
            self._set(derived.key, value, changed)
            if derived.smoothed in self._smoothers:
                self._smoothers[derived.smoothed].set_raw(value)
        if self._errors is not None:
            self._errors.changed(key)
        if self._defrost is not None:
            self._defrost_on_change(key, previous, state)

    # --------------------------------------------------------- error code

    def _check_errors(self, timestamp: int, changed: set[str]) -> None:
        assert self._errors is not None
        finding = self._errors.evaluate(self._states, timestamp)
        if finding == self.finding:
            return
        if finding is not None:
            _LOGGER.warning("Heat pump check found a fault: %s", finding)
        else:
            _LOGGER.info("Heat pump check no longer finds %s", self.finding)
        self.finding = finding
        changed.add(ERROR_CODE)

    # ------------------------------------------------- optimized defrosting

    def _defrost_on_change(self, key: str, previous: CanState, state: CanState) -> None:
        defrost = self._defrost
        assert defrost is not None
        operating_state = self._states.get(OPERATING_STATE)
        mode = self._states.get(OPERATING_MODE)
        if key == OPERATING_MODE:
            defrost.operating_mode_changed(_text(state), _text(operating_state))
        elif key == ANTIFREEZE:
            if (
                state is not None
                and state != ANTIFREEZE_OFF
                and self.optimized_defrosting
            ):
                _LOGGER.info(
                    "Optimized defrosting turned off: antifreeze temperature set to %s",
                    state,
                )
                self._set_optimized_defrosting(False)
        elif key == OPERATING_STATE and self.optimized_defrosting:
            new_mode = defrost.operating_state_changed(
                _text(previous), _text(state), _text(mode)
            )
            if new_mode is not None:
                _LOGGER.info(
                    "Optimized defrosting: operating state %s -> %s, mode %s -> %s",
                    previous,
                    state,
                    mode,
                    new_mode,
                )
                self._write_in_background(OPERATING_MODE, new_mode)

    def _set_optimized_defrosting(self, on: bool) -> None:
        self.storage.set_optimized_defrosting(on)
        self._notify((OPTIMIZED_DEFROSTING,))

    async def async_set_optimized_defrosting(self, on: bool) -> None:
        """Turn the defrost optimization on or off.

        Turning it on sets the antifreeze temperature to off, which the
        optimization needs.
        """
        self._set_optimized_defrosting(on)
        if on:
            await self.async_write(ANTIFREEZE, ANTIFREEZE_OFF)

    # ------------------------------------------------------------- writing

    def _queue_write(self, key: str, state: StateValue, done: Done) -> Job:
        value = CAN_VALUES_BY_KEY[key]
        job = self.scheduler.request_write(key, value.encode(state), done)
        self.channel.async_request_exchange()
        return job

    def _write_in_background(self, key: str, state: StateValue) -> None:
        """Write a value for the logic without waiting for the result."""

        async def _write() -> None:
            try:
                await self.async_write(key, state)
            except HomeAssistantError as err:
                _LOGGER.warning("Writing %s = %s failed: %s", key, state, err)

        self.channel.node.entry.async_create_background_task(
            self.hass, _write(), f"{DOMAIN} write {key}", eager_start=False
        )

    def _check_writable(self, key: str) -> None:
        if not self.available:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="bus_unavailable"
            )
        if key not in self.scheduler.keys:  # pragma: no cover
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="value_not_polled",
                translation_placeholders={"key": key},
            )

    async def async_write(
        self, key: str, state: StateValue, *, force: bool = False
    ) -> None:
        """Write a setting and wait until the heat pump reports the new value.

        Nothing is written if the setting already has the value (after
        rounding to what the setting can store), unless `force` is set.
        """
        value = CAN_VALUES_BY_KEY[key]
        try:
            wanted = value.normalize(state)
            value.encode(wanted)
        except (TypeError, ValueError) as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="invalid_value",
                translation_placeholders={"key": key, "value": str(state)},
            ) from err
        self._check_writable(key)
        if not force and _same(self._states.get(key), wanted):
            return
        future: asyncio.Future[Outcome] = self.hass.loop.create_future()

        def _done(outcome: Outcome) -> None:
            if not future.done():
                future.set_result(outcome)

        job = self._queue_write(key, wanted, _done)
        try:
            async with asyncio.timeout(WRITE_TIMEOUT):
                outcome = await future
        except TimeoutError:
            job.cancel()
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="write_not_confirmed",
                translation_placeholders={"key": key},
            ) from None
        if not outcome.sent:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="write_not_sent",
                translation_placeholders={"key": key},
            )
        if outcome.answer is None:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="write_not_confirmed",
                translation_placeholders={"key": key},
            )
        actual = outcome.decoded.state if outcome.decoded is not None else None
        if not _same(actual, wanted):
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="write_rejected",
                translation_placeholders={
                    "key": key,
                    "value": str(wanted),
                    "actual": str(actual),
                },
            )

    async def async_run_hot_water(self) -> None:
        """Start a hot water load: hot water setpoint 1 to 70 °C and back."""
        self._check_writable(HOT_WATER_SETPOINT)
        current = self._states.get(HOT_WATER_SETPOINT)
        if not isinstance(current, float):
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="value_unknown",
                translation_placeholders={"key": HOT_WATER_SETPOINT},
            )
        _LOGGER.info(
            "Hot water run: setpoint %s -> %s °C", current, DHW_RUN_TEMPERATURE
        )
        try:
            await self.async_write(HOT_WATER_SETPOINT, DHW_RUN_TEMPERATURE)
        except HomeAssistantError:
            # The setpoint may have been taken even without read-back.
            await self._async_restore(current, force=True)
            raise
        await self._async_restore(current, force=False)

    async def _async_restore(self, setpoint: float, *, force: bool) -> None:
        try:
            await self.async_write(HOT_WATER_SETPOINT, setpoint, force=force)
        except HomeAssistantError as err:
            _LOGGER.error(
                "Hot water run: setting the setpoint back to %s °C failed: %s",
                setpoint,
                err,
            )
            if not force:
                raise

    async def async_send_raw(self, data: bytes) -> CanFrame | None:
        """Send a raw frame; return the answer to a read request, if any."""
        if not self.available:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="bus_unavailable"
            )
        future: asyncio.Future[Outcome] = self.hass.loop.create_future()

        def _done(outcome: Outcome) -> None:
            if not future.done():
                future.set_result(outcome)

        job = self.scheduler.request_raw(data, _done)
        self.channel.async_request_exchange()
        try:
            async with asyncio.timeout(WRITE_TIMEOUT):
                outcome = await future
        except TimeoutError:
            job.cancel()
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="raw_not_sent"
            ) from None
        if not outcome.sent:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="raw_not_sent"
            )
        return outcome.answer

    # ---------------------------------------------------------- diagnostics

    def diagnostics(self) -> dict[str, Any]:
        """Return the values, the logic and the scheduler state."""

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
            "finding": self.finding,
            "defrost_saved_mode": self._defrost.saved
            if self._defrost is not None
            else None,
            "storage": self.storage.diagnostics(),
            "scheduler": self.scheduler.diagnostics(),
        }


def _text(state: CanState) -> str | None:
    return state if isinstance(state, str) else None
