"""Values of the RoCon controller readable over CAN.

The table is data: register, position and scaling of each value, how it is
shown in Home Assistant (as plain strings, so that this module does not
depend on Home Assistant) and the polling group it belongs to.
"""

from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum
import math
from typing import Any, Final

from .protocol import CONTROLLER_ID, Kind, Register, parse_command, raw_value, signed16

# Units and classes, written as Home Assistant expects them.
CELSIUS: Final = "°C"
KELVIN: Final = "K"
BAR: Final = "bar"
PERCENT: Final = "%"
MINUTES: Final = "min"
HOURS: Final = "h"
KILOWATT: Final = "kW"
KILOWATT_HOUR: Final = "kWh"
LITERS_PER_HOUR: Final = "L/h"
LITERS_PER_MINUTE: Final = "L/min"

TEMPERATURE: Final = "temperature"
TEMPERATURE_DELTA: Final = "temperature_delta"
PRESSURE: Final = "pressure"
POWER: Final = "power"
ENERGY: Final = "energy"
DURATION: Final = "duration"
VOLUME_FLOW_RATE: Final = "volume_flow_rate"
RUNNING: Final = "running"

MEASUREMENT: Final = "measurement"
TOTAL_INCREASING: Final = "total_increasing"

CONFIG: Final = "config"
DIAGNOSTIC: Final = "diagnostic"

RESPONDER_300: Final = 0x300
RESPONDER_500: Final = 0x500


class Platform(StrEnum):
    """How a value is shown in Home Assistant."""

    SENSOR = "sensor"
    ENUM = "enum"
    BINARY_SENSOR = "binary_sensor"
    NUMBER = "number"
    SELECT = "select"
    SWITCH = "switch"
    INTERNAL = "internal"


class Group(StrEnum):
    """Polling group of a value."""

    MEASUREMENT = "measurement"
    STATE = "state"
    SETTING = "setting"
    COUNTER = "counter"


class Decoder(StrEnum):
    """How the value is taken from the data bytes."""

    VALUE = "value"
    HEATER_STAGES = "heater_stages"
    SENSOR_CONFIGURED = "sensor_configured"


type StateValue = float | bool | str | None


@dataclass(frozen=True, slots=True)
class Decoded:
    """A value decoded from a frame."""

    raw: int
    state: StateValue


@dataclass(frozen=True, slots=True, kw_only=True)
class CanValue:
    """A value of the RoCon controller."""

    key: str
    platform: Platform
    group: Group
    command: bytes
    responder: int = CONTROLLER_ID
    offset: int = 5
    size: int = 1
    divider: float = 1.0
    signed: bool = False
    valid_range: tuple[float, float] | None = None
    no_value: int | None = None
    decoder: Decoder = Decoder.VALUE
    # Options of selects and enum sensors: value -> option key.
    options: tuple[tuple[float, str], ...] = ()
    unknown_option: str | None = None
    # Numbers: limits and, if only some values are allowed, those values.
    minimum: float | None = None
    maximum: float | None = None
    step: float | None = None
    allowed: tuple[float, ...] = ()
    interval: float | None = None
    device_class: str | None = None
    unit: str | None = None
    state_class: str | None = None
    precision: int | None = None
    category: str | None = None
    enabled_default: bool = True
    # Settings are written unless this is False.
    writable: bool = True
    register: Register = field(init=False, compare=False)

    def __post_init__(self) -> None:
        """Derive the register from the command."""
        object.__setattr__(
            self, "register", Register.from_command(self.responder, self.command)
        )

    @property
    def option_keys(self) -> list[str]:
        """Return the option keys in table order."""
        keys = [key for _, key in self.options]
        if self.unknown_option is not None:
            keys.append(self.unknown_option)
        return keys

    def _number(self, data: bytes) -> tuple[int, float]:
        if self.decoder is Decoder.HEATER_STAGES:
            byte = data[self.offset]
            stages = sum(1 for bit in (0x08, 0x04, 0x02) if byte & bit)
            return byte, 3.0 * stages
        raw = raw_value(data, self.offset, self.size)
        value = signed16(raw) if self.signed and self.size == 2 else raw
        return raw, round(value / self.divider, 6)

    def decode(self, data: bytes) -> Decoded | None:
        """Decode the value of a frame; None if it is not plausible."""
        if self.decoder is Decoder.SENSOR_CONFIGURED:
            raw = data[self.offset]
            return Decoded(raw, raw == 0x05)
        raw, number = self._number(data)
        if self.no_value is not None and raw == self.no_value:
            return Decoded(raw, None)
        if self.valid_range is not None and not (
            self.valid_range[0] <= number <= self.valid_range[1]
        ):
            return None
        match self.platform:
            case Platform.BINARY_SENSOR | Platform.SWITCH:
                return Decoded(raw, raw > 0)
            case Platform.ENUM:
                for value, key in self.options:
                    if math.isclose(value, number):
                        return Decoded(raw, key)
                return Decoded(raw, self.unknown_option)
            case Platform.SELECT:
                return Decoded(raw, self.nearest_option(number))
            case _:
                return Decoded(raw, number)

    def nearest_option(self, number: float) -> str:
        """Return the option whose value is closest to a number."""
        return min(self.options, key=lambda item: abs(item[0] - number))[1]

    @property
    def can_write(self) -> bool:
        """Return True for settings that are written to the controller."""
        return self.writable and self.platform in (
            Platform.NUMBER,
            Platform.SELECT,
            Platform.SWITCH,
        )

    def normalize(self, state: StateValue) -> StateValue:
        """Return the state the controller would store for a requested state.

        Numbers are moved to the nearest allowed value, or to the step grid
        within the limits. Raises TypeError or ValueError for states the value
        cannot take.
        """
        match self.platform:
            case Platform.NUMBER:
                if isinstance(state, bool) or not isinstance(state, int | float):
                    raise TypeError(f"{self.key} needs a number, not {state!r}")
                return self._snap(float(state))
            case Platform.SELECT:
                if state not in {key for _, key in self.options}:
                    raise ValueError(f"{state!r} is no option of {self.key}")
                return state
            case Platform.SWITCH:
                if not isinstance(state, bool):
                    raise TypeError(f"{self.key} needs True or False, not {state!r}")
                return state
            case _:
                raise ValueError(f"{self.key} is not a setting")

    def _snap(self, number: float) -> float:
        if self.allowed:
            return min(self.allowed, key=lambda value: abs(value - number))
        assert self.minimum is not None
        assert self.maximum is not None
        assert self.step is not None
        number = max(self.minimum, min(self.maximum, number))
        steps = round((number - self.minimum) / self.step)
        return round(min(self.maximum, self.minimum + steps * self.step), 6)

    def option_value(self, option: str) -> float:
        """Return the value of an option."""
        for value, key in self.options:
            if key == option:
                return value
        raise ValueError(f"{option!r} is no option of {self.key}")

    def _raw_of(self, state: StateValue) -> int:
        match state:
            case bool():
                return int(state)
            case str():
                return round(self.option_value(state) * self.divider)
            case float() | int():
                return round(state * self.divider)
        raise ValueError(f"Cannot encode {state!r} for {self.key}")

    def encode(self, state: StateValue) -> bytes:
        """Return the data bytes of the frame that writes a normalized state.

        The frame is the read command with the kind set to write and the raw
        value at the data position; the other data bytes are zero.
        """
        data = bytearray(self.command)
        data[0] = (data[0] & 0xF0) | Kind.WRITE
        data[1] = 0x00
        if self.decoder is Decoder.HEATER_STAGES:
            assert isinstance(state, str)
            kilowatts = self.option_value(state)
            byte = 0x01
            for threshold, bit in ((3, 0x08), (6, 0x04), (9, 0x02)):
                if kilowatts >= threshold:
                    byte |= bit
            data[self.offset] = byte
            return bytes(data)
        raw = self._raw_of(state)
        limit = 1 << (8 * self.size)
        lowest, highest = (-(limit // 2), limit // 2) if self.signed else (0, limit)
        if not lowest <= raw < highest:
            raise ValueError(f"{state!r} does not fit into {self.key}")
        raw %= limit
        if self.size == 2:
            data[self.offset] = raw >> 8
            data[self.offset + 1] = raw & 0xFF
        else:
            data[self.offset] = raw
        return bytes(data)


# ----------------------------------------------------------------- helpers


def _measurement(
    key: str,
    command: str,
    *,
    unit: str = CELSIUS,
    device_class: str | None = TEMPERATURE,
    precision: int = 1,
    group: Group = Group.MEASUREMENT,
    **kwargs: Any,
) -> CanValue:
    return CanValue(
        key=key,
        platform=Platform.SENSOR,
        group=group,
        command=parse_command(command),
        unit=unit,
        device_class=device_class,
        state_class=MEASUREMENT,
        precision=precision,
        **kwargs,
    )


def _temperature(key: str, command: str, **kwargs: Any) -> CanValue:
    return _measurement(key, command, offset=5, size=2, divider=10.0, **kwargs)


def _counter(key: str, command: str, unit: str, device_class: str) -> CanValue:
    return CanValue(
        key=key,
        platform=Platform.SENSOR,
        group=Group.COUNTER,
        command=parse_command(command),
        size=2,
        unit=unit,
        device_class=device_class,
        state_class=TOTAL_INCREASING,
        precision=0,
    )


def _number(
    key: str,
    command: str,
    minimum: float,
    maximum: float,
    step: float,
    *,
    unit: str | None = CELSIUS,
    device_class: str | None = TEMPERATURE,
    precision: int | None = 1,
    offset: int = 5,
    size: int = 2,
    divider: float = 10.0,
    category: str | None = CONFIG,
    **kwargs: Any,
) -> CanValue:
    return CanValue(
        key=key,
        platform=Platform.NUMBER,
        group=Group.SETTING,
        command=parse_command(command),
        offset=offset,
        size=size,
        divider=divider,
        minimum=minimum,
        maximum=maximum,
        step=step,
        unit=unit,
        device_class=device_class,
        precision=precision,
        category=category,
        **kwargs,
    )


def _minutes(key: str, command: str, minimum: float, maximum: float) -> CanValue:
    return _number(
        key,
        command,
        minimum,
        maximum,
        1,
        unit=MINUTES,
        device_class=DURATION,
        precision=0,
        divider=1.0,
    )


def _delta(
    key: str,
    command: str,
    minimum: float,
    maximum: float,
    step: float,
    **kwargs: Any,
) -> CanValue:
    return _number(
        key,
        command,
        minimum,
        maximum,
        step,
        unit=KELVIN,
        device_class=TEMPERATURE_DELTA,
        **kwargs,
    )


def _select(
    key: str,
    command: str,
    options: Iterable[tuple[float, str]],
    *,
    offset: int = 6,
    size: int = 1,
    category: str | None = CONFIG,
    **kwargs: Any,
) -> CanValue:
    return CanValue(
        key=key,
        platform=Platform.SELECT,
        group=Group.SETTING,
        command=parse_command(command),
        offset=offset,
        size=size,
        options=tuple(options),
        category=category,
        **kwargs,
    )


def _switch(
    key: str, command: str, *, offset: int = 6, category: str | None = CONFIG
) -> CanValue:
    return CanValue(
        key=key,
        platform=Platform.SWITCH,
        group=Group.SETTING,
        command=parse_command(command),
        offset=offset,
        category=category,
    )


def _binary(key: str, command: str, *, offset: int = 6, **kwargs: Any) -> CanValue:
    return CanValue(
        key=key,
        platform=Platform.BINARY_SENSOR,
        group=Group.STATE,
        command=parse_command(command),
        offset=offset,
        **kwargs,
    )


def _date_part(key: str, command: str) -> CanValue:
    return CanValue(
        key=key,
        platform=Platform.INTERNAL,
        group=Group.COUNTER,
        command=parse_command(command),
    )


def _degrees(values: Iterable[int]) -> list[tuple[float, str]]:
    """Return select options for whole degrees, e.g. -4 -> `minus_4`."""
    return [
        (float(value), f"minus_{-value}" if value < 0 else str(value))
        for value in values
    ]


def _values(*ranges: tuple[float, float, float]) -> tuple[float, ...]:
    """Return the sorted values of several (start, stop, step) ranges."""
    values: set[float] = set()
    for start, stop, step in ranges:
        count = round((stop - start) / step)
        values.update(round(start + index * step, 2) for index in range(count + 1))
    return tuple(sorted(values))


ROOM_SETPOINTS: Final = _values((15, 25, 1), (19.5, 23.5, 0.5))
HOT_WATER_SETPOINTS: Final = _values((35, 70, 5), (45, 55, 1))

ERROR_CODES: Final = (
    0,
    *range(9001, 9040),
    *range(9041, 9045),
    75,
    76,
    81,
    88,
    91,
    128,
    129,
    198,
    200,
    8005,
    8100,
    9000,
)
WARNING_CODES: Final = (8006, 8007)


def _error_options() -> list[tuple[float, str]]:
    options: list[tuple[float, str]] = [
        (float(code), f"e{code}" if code else "no_error") for code in ERROR_CODES
    ]
    options.extend((float(code), f"w{code}") for code in WARNING_CODES)
    return options


# ------------------------------------------------------------------- table

CAN_VALUES: Final[tuple[CanValue, ...]] = (
    _switch("1_dhw", "31 00 FA 01 44", category=None),
    _delta("hp_hyst_tdhw", "31 00 FA 06 91", 2, 20, 0.1),
    _minutes("delay_time_for_backup_heating", "31 00 FA 06 92", 20, 95),
    _select(
        "outdoor_unit",
        "31 00 FA 06 9A",
        [(0, "none"), (1, "4"), (2, "6"), (3, "8"), (4, "11"), (5, "14"), (6, "16")],
    ),
    _select(
        "indoor_unit",
        "31 00 FA 06 99",
        [(0, "none"), (1, "304"), (2, "308"), (3, "508"), (4, "516")],
    ),
    _select(
        "building_insulation",
        "31 00 FA 01 0C",
        [(0, "off"), (2, "low"), (4, "normal"), (8, "good"), (12, "very_good")],
        offset=5,
    ),
    _number("antileg_temp", "31 00 FA 05 87", 60, 75, 1, precision=0),
    _select(
        "antileg_day",
        "31 00 FA 01 01",
        [
            (0, "off"),
            (1, "monday"),
            (2, "tuesday"),
            (3, "wednesday"),
            (4, "thursday"),
            (5, "friday"),
            (6, "saturday"),
            (7, "sunday"),
            (8, "daily"),
        ],
        offset=5,
    ),
    _minutes("circulation_interval_on", "31 00 FA 06 5E", 0, 15),
    _minutes("circulation_interval_off", "31 00 FA 06 5F", 0, 15),
    _switch("circulation_with_dhw_program", "31 00 FA 01 82"),
    _number("t_dhw_1_min", "31 00 FA 06 73", 20, 85, 1),
    _minutes("max_dhw_loading", "31 00 FA 01 80", 10, 240),
    _minutes("dhw_off_time", "31 00 FA 4E 3F", 0, 180),
    _delta("tdiff_dhw_ch", "31 00 FA 06 6D", 2, 15, 1, precision=0),
    _temperature("t_hs", "31 00 FA 01 D6", valid_range=(1, 90)),
    _temperature(
        "temperature_outside", "31 00 FA C0 FF", signed=True, valid_range=(-30, 90)
    ),
    _temperature("ta2", "31 00 FA C1 05", signed=True, valid_range=(-30, 90)),
    _temperature("tliq", "31 00 FA C1 03", signed=True, valid_range=(-30, 90)),
    _temperature(
        "t_ext",
        "61 00 FA 0A 0C",
        responder=RESPONDER_300,
        signed=True,
        valid_range=(-30, 90),
    ),
    _temperature(
        "t_room",
        "61 00 FA 00 11",
        responder=RESPONDER_300,
        signed=True,
        valid_range=(-30, 90),
        enabled_default=False,
    ),
    _temperature("tdhw1", "31 00 FA 00 0E", valid_range=(1, 90)),
    _temperature("tdhw2", "31 00 FA C1 06", valid_range=(1, 90)),
    _measurement(
        "water_pressure",
        "31 00 1C",
        unit=BAR,
        device_class=PRESSURE,
        precision=2,
        offset=3,
        size=2,
        divider=1000.0,
    ),
    _measurement(
        "circulation_pump",
        "31 00 FA C0 F7",
        unit=PERCENT,
        device_class=None,
        precision=0,
        offset=6,
        valid_range=(0, 100),
    ),
    _number(
        "circulation_pump_min",
        "31 00 FA 06 7F",
        40,
        100,
        1,
        unit=PERCENT,
        device_class=None,
        precision=0,
        offset=6,
        size=1,
        divider=1.0,
    ),
    _number(
        "circulation_pump_max",
        "31 00 FA 06 7E",
        60,
        100,
        1,
        unit=PERCENT,
        device_class=None,
        precision=0,
        offset=6,
        size=1,
        divider=1.0,
    ),
    _measurement(
        "bypass_valve",
        "31 00 FA C0 FB",
        unit=PERCENT,
        device_class=None,
        precision=0,
        size=2,
        valid_range=(0, 100),
    ),
    _measurement(
        "dhw_mixer_position",
        "31 00 FA 06 9B",
        unit=PERCENT,
        device_class=None,
        precision=0,
        size=2,
        valid_range=(0, 100),
    ),
    _measurement(
        "target_supply_temperature",
        "31 00 02",
        offset=3,
        size=2,
        divider=10.0,
        valid_range=(0, 90),
    ),
    _counter("ehs_for_ch", "31 00 FA 09 20", KILOWATT_HOUR, ENERGY),
    _counter("qch", "31 00 FA 06 A7", KILOWATT_HOUR, ENERGY),
    _counter("qboh", "31 00 FA 09 1C", KILOWATT_HOUR, ENERGY),
    _counter("qdhw", "31 00 FA 09 2C", KILOWATT_HOUR, ENERGY),
    _counter("total_energy_produced", "31 00 FA 09 30", KILOWATT_HOUR, ENERGY),
    _counter("energy_cooling", "31 00 FA 06 A6", KILOWATT_HOUR, ENERGY),
    CanValue(
        key="total_electrical_energy",
        platform=Platform.SENSOR,
        group=Group.COUNTER,
        command=parse_command("31 00 FA C2 FA"),
        size=2,
        # Older units do not measure it and always send 0x8000.
        no_value=0x8000,
        unit=KILOWATT_HOUR,
        device_class=ENERGY,
        state_class=TOTAL_INCREASING,
        precision=0,
    ),
    _counter("runtime_compressor", "31 00 FA 06 A5", HOURS, DURATION),
    _counter("runtime_pump", "31 00 FA 06 A4", HOURS, DURATION),
    _delta("delta_temp_ch", "31 00 FA 06 83", 2, 20, 1, precision=0, offset=6, size=1),
    _delta("delta_temp_dhw", "31 00 FA 06 84", 2, 20, 1, precision=0, offset=6, size=1),
    _select(
        "temperature_antifreeze",
        "31 00 FA 0A 00",
        # Raw 0xFF60 means off.
        [(-16.0, "off"), *_degrees(range(-15, 6))],
        offset=5,
        size=2,
        divider=10.0,
        signed=True,
    ),
    _temperature("tv", "31 00 FA C0 FC", valid_range=(1, 90)),
    _temperature("tvbh", "31 00 FA C0 FE", valid_range=(1, 90)),
    _temperature("tr", "31 00 FA C1 00", valid_range=(1, 90)),
    _measurement(
        "flow_rate",
        "31 00 FA 01 DA",
        unit=LITERS_PER_HOUR,
        device_class=VOLUME_FLOW_RATE,
        precision=0,
        size=2,
        valid_range=(0, 3000),
        interval=10.0,
    ),
    _measurement(
        "flow_rate_calc",
        "31 00 FA 06 9C",
        unit=LITERS_PER_MINUTE,
        device_class=VOLUME_FLOW_RATE,
        precision=1,
        size=2,
        divider=10.0,
    ),
    _number(
        "flow_rate_setpoint",
        "31 00 FA 06 89",
        8,
        25,
        1,
        unit=LITERS_PER_MINUTE,
        device_class=VOLUME_FLOW_RATE,
        precision=0,
        offset=6,
        size=1,
    ),
    _number(
        "flow_rate_min",
        "31 00 FA 06 88",
        12,
        25,
        1,
        unit=LITERS_PER_MINUTE,
        device_class=VOLUME_FLOW_RATE,
        precision=0,
        offset=6,
        size=1,
    ),
    _number(
        "flow_rate_hyst",
        "31 00 FA 06 8A",
        0,
        5,
        0.1,
        unit=LITERS_PER_MINUTE,
        device_class=VOLUME_FLOW_RATE,
        precision=1,
        offset=6,
        size=1,
    ),
    *(
        _number(
            f"target_room{index}_temperature",
            f"31 00 {4 + index:02X}",
            15,
            25,
            0.5,
            offset=3,
            allowed=ROOM_SETPOINTS,
            category=None,
        )
        for index in (1, 2, 3)
    ),
    _number("flow_temperature_day", "31 00 FA 01 29", 20, 90, 0.1),
    _number("flow_temperature_night", "31 00 FA 01 2A", 10, 90, 0.1),
    _select(
        "heating_limit_day",
        "31 00 FA 01 16",
        # Raw 0xFE70 means off.
        [(-40.0, "off"), *_degrees(range(10, 41))],
        offset=5,
        size=2,
        divider=10.0,
        signed=True,
    ),
    _select(
        "heating_limit_night",
        "31 00 FA 01 17",
        # Raw 0x005A means off.
        [(9.0, "off"), *_degrees(range(10, 41))],
        offset=5,
        size=2,
        divider=10.0,
        signed=True,
    ),
    _number(
        "heating_curve",
        "31 00 FA 01 0E",
        0,
        2.55,
        0.01,
        unit=None,
        device_class=None,
        precision=2,
        divider=100.0,
    ),
    _number("min_target_flow_temp", "31 00 FA 01 2B", 10, 90, 0.1),
    _number("max_target_flow_temp", "31 00 28", 20, 90, 0.1, offset=3),
    _number(
        "target_hot_water_temperature_1",
        "31 00 13",
        35,
        70,
        1,
        offset=3,
        allowed=HOT_WATER_SETPOINTS,
        category=None,
    ),
    _number(
        "target_hot_water_temperature_2",
        "31 00 FA 0A 06",
        35,
        70,
        1,
        allowed=HOT_WATER_SETPOINTS,
        category=None,
    ),
    _number(
        "target_hot_water_temperature_3",
        "31 00 FA 01 3E",
        35,
        70,
        1,
        allowed=HOT_WATER_SETPOINTS,
        category=None,
    ),
    CanValue(
        key="mode_of_operating",
        platform=Platform.ENUM,
        group=Group.STATE,
        command=parse_command("31 00 FA C0 F6"),
        offset=6,
        options=(
            (0, "standby"),
            (1, "heating"),
            (2, "cooling"),
            (3, "defrosting"),
            (4, "hot_water"),
        ),
    ),
    _select(
        "operating_mode",
        "31 00 FA 01 12",
        [
            (0x01, "standby"),
            (0x03, "heating"),
            (0x04, "lowering"),
            (0x05, "summer"),
            (0x11, "cooling"),
            (0x0B, "automatic_1"),
            (0x0C, "automatic_2"),
        ],
        offset=5,
        interval=5.0,
        category=None,
    ),
    _select(
        "quiet",
        "31 00 FA 06 96",
        [(0, "off"), (1, "on"), (2, "night_only")],
        category=None,
    ),
    CanValue(
        key="error_code",
        platform=Platform.ENUM,
        group=Group.STATE,
        command=parse_command("31 00 FA 13 88"),
        size=2,
        options=tuple(_error_options()),
        unknown_option="unknown",
    ),
    _binary(
        "status_kompressor",
        "A1 00 61",
        responder=RESPONDER_500,
        offset=3,
        device_class=RUNNING,
    ),
    _binary("status_kesselpumpe", "31 00 FA 0A 8C", device_class=RUNNING),
    _binary(
        "external_temp_sensor",
        "31 00 FA 09 61",
        decoder=Decoder.SENSOR_CONFIGURED,
        category=DIAGNOSTIC,
    ),
    _binary("energy_saving_mode", "31 00 FA 01 76"),
    _select("hk_function", "31 00 FA 01 41", [(0, "weather_dependent"), (1, "fixed")]),
    _select(
        "sg_mode",
        "31 00 FA 06 94",
        [(0, "off"), (1, "sg_mode_1"), (2, "sg_mode_2")],
        category=None,
    ),
    _switch("smart_grid", "31 00 FA 06 93"),
    _select(
        "function_ehs",
        "31 00 FA 06 D2",
        [
            (0, "no_additional_heat_generator"),
            (1, "optional_backup_heater"),
            (2, "wez_for_hot_water_and_heating"),
            (3, "wez1_for_hot_water_wez2_for_heating"),
        ],
    ),
    _switch("ch_support", "31 00 FA 06 6C"),
    *(
        _number(
            key,
            command,
            minimum,
            40,
            1,
            unit=KILOWATT,
            device_class=POWER,
            precision=0,
            divider=100.0,
        )
        for key, command, minimum in (
            ("power_dhw", "31 00 FA 06 68", 1),
            ("power_ehs_1", "31 00 FA 06 69", 1),
            ("power_ehs_2", "31 00 FA 06 6A", 1),
            ("power_biv", "31 00 FA 06 6B", 3),
        )
    ),
    _select(
        "electric_heater",
        "31 00 FA 0A 20",
        [(0, "off"), (3, "3"), (6, "6"), (9, "9")],
        offset=5,
        decoder=Decoder.HEATER_STAGES,
    ),
    CanValue(
        key="ext",
        platform=Platform.ENUM,
        group=Group.STATE,
        command=parse_command("31 00 FA C0 F8"),
        offset=6,
        options=((0, "none"), (3, "sgn"), (4, "sg1"), (5, "sg2"), (6, "sg3")),
    ),
    _number("max_heating_temperature", "31 00 FA 06 6E", 5, 85, 1),
    _binary(
        "bivalence_function",
        "A1 00 FA 06 D3",
        responder=RESPONDER_500,
        category=DIAGNOSTIC,
    ),
    _temperature(
        "bivalence_temperature",
        "A1 00 FA 06 D4",
        responder=RESPONDER_500,
        signed=True,
        group=Group.SETTING,
    ),
    _delta("supply_temperature_adjustment_heating", "31 00 FA 06 A0", 0, 50, 1),
    _delta("supply_temperature_adjustment_cooling", "31 00 FA 06 A1", 0, 50, 1),
    _switch("room_therm", "31 00 FA 06 78"),
    CanValue(
        key="heating_curve_adaptation",
        platform=Platform.SWITCH,
        group=Group.SETTING,
        command=parse_command("61 00 FA 01 15"),
        responder=RESPONDER_300,
        category=CONFIG,
        # Read only: which node takes writes of this register is not known yet.
        writable=False,
    ),
    _date_part("system_date_day", "31 00 FA 01 22"),
    _date_part("system_date_month", "31 00 FA 01 23"),
    _date_part("system_date_year", "31 00 FA 01 24"),
    _date_part("system_time_hour", "31 00 FA 01 25"),
    _date_part("system_time_minute", "31 00 FA 01 26"),
    _date_part("system_time_second", "31 00 FA 01 27"),
    *(
        _number(
            key,
            command,
            0.1,
            5.0,
            0.1,
            unit=BAR,
            device_class=PRESSURE,
            divider=1000.0,
        )
        for key, command in (
            ("set_pressure", "31 00 FA 07 25"),
            ("max_pressure_drop", "31 00 FA 07 26"),
            ("max_pressure", "31 00 FA 07 27"),
            ("min_pressure", "31 00 FA 07 28"),
        )
    ),
    _number("start_t_out_cooling", "31 00 FA 13 5B", 15, 45, 0.1),
    _number("max_t_out_cooling", "31 00 FA 13 5C", 20, 45, 0.1),
    _number("t_flow_cooling_start", "31 00 FA 13 5D", 5, 25, 0.1),
    _number("t_flow_cooling_max", "31 00 FA 13 5E", 5, 25, 0.1),
    _number("min_t_flow_cooling", "31 00 FA 13 63", 5, 25, 0.1),
    _number("t_flow_cooling", "31 00 FA 03 DD", 8, 30, 0.1),
    _select(
        "t_h_c_switch",
        "31 00 FA C1 C3",
        # Raw 0x005A means off.
        [(9.0, "off"), *_degrees(range(10, 41))],
        offset=5,
        size=2,
        divider=10.0,
        signed=True,
    ),
    _delta("cooling_setpoint_adj", "31 00 FA 13 59", -5, 5, 0.1, signed=True),
)

CAN_VALUES_BY_KEY: Final[dict[str, CanValue]] = {
    value.key: value for value in CAN_VALUES
}

SYSTEM_TIME_PARTS: Final = (
    "system_date_year",
    "system_date_month",
    "system_date_day",
    "system_time_hour",
    "system_time_minute",
    "system_time_second",
)
