"""Values of the indoor unit readable over the serial connection.

The table is data: register, position and conversion of each value per
protocol, how it is shown in Home Assistant (as plain strings, so that this
module does not depend on Home Assistant), and the feature it belongs to. The
outdoor unit profiles tell which features a unit has.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final

from .protocol import Protocol
from .saturation import Refrigerant, saturation_temperature

# Units and classes, written as Home Assistant expects them.
CELSIUS: Final = "°C"
BAR: Final = "bar"
AMPERE: Final = "A"
VOLT: Final = "V"
RPM: Final = "rpm"
PULSES: Final = "pls"
LITERS_PER_HOUR: Final = "L/h"

TEMPERATURE: Final = "temperature"
PRESSURE: Final = "pressure"
CURRENT: Final = "current"
VOLTAGE: Final = "voltage"
VOLUME_FLOW_RATE: Final = "volume_flow_rate"
RUNNING: Final = "running"

MEASUREMENT: Final = "measurement"
DIAGNOSTIC: Final = "diagnostic"

# Flow rate: the indoor unit reports l/min with one decimal; shown in L/h
# like the flow rate of the RoCon controller (raw / 10 * 60).
FLOW_FACTOR: Final = 6.0


class Platform(StrEnum):
    """How a value is shown in Home Assistant."""

    SENSOR = "sensor"
    ENUM = "enum"
    BINARY_SENSOR = "binary_sensor"


class Converter(StrEnum):
    """How a value is taken from the payload."""

    NUMBER = "number"
    BIT = "bit"
    HIGH_NIBBLE = "high_nibble"
    TARGET_TEMPERATURE = "target_temperature"
    FAN_SPEED = "fan_speed"
    SATURATION = "saturation"


class Feature(StrEnum):
    """Group of values that an indoor/outdoor unit combination has or not."""

    EQUIPMENT = "equipment"  # 0x00
    OUTDOOR_STATE = "outdoor_state"  # 0x10
    OUTDOOR_TEMPERATURES = "outdoor_temperatures"  # 0x20 bytes 0-11
    HEAT_SINK = "heat_sink"  # 0x20 bytes 12-13
    PRESSURE_0X20 = "pressure_0x20"  # 0x20 bytes 14-15
    CURRENTS = "currents"  # 0x21 bytes 0-3
    VOLTAGE = "voltage"  # 0x21 bytes 4-5
    COMPRESSOR = "compressor"  # 0x30 bytes 0-4
    FOUR_WAY_VALVE = "four_way_valve"  # 0x30 byte 7
    INDOOR_STATE = "indoor_state"  # 0x60
    INDOOR_TEMPERATURES = "indoor_temperatures"  # 0x61
    WATER = "water"  # 0x62 bytes 8-10
    PRESSURE_0X62 = "pressure_0x62"  # 0x62 bytes 15-16 as refrigerant pressure
    DISCHARGE_PRESSURE = "discharge_pressure"  # 0x62 bytes 15-16
    S_VALUES = "s_values"  # S registers 0x53-0x55


class Status(StrEnum):
    """Whether a unit has a feature."""

    CONFIRMED = "confirmed"  # seen in real frames: entity enabled
    UNCONFIRMED = "unconfirmed"  # in the protocol, not seen: entity disabled
    ABSENT = "absent"  # not there: no entity


type StateValue = float | bool | str | None


@dataclass(frozen=True, slots=True, kw_only=True)
class Layout:
    """Position and conversion of a value in the payload of a register."""

    register: int
    offset: int
    feature: Feature
    size: int = 1
    signed: bool = False
    converter: Converter = Converter.NUMBER
    divider: float = 1.0
    factor: float = 1.0
    mask: int = 0
    options: tuple[tuple[int, str], ...] = ()

    def fits(self, payload: bytes) -> bool:
        """Return True if the payload holds the value."""
        return self.offset + self.size <= len(payload)


@dataclass(frozen=True, slots=True, kw_only=True)
class UartValue:
    """A value of the indoor unit."""

    key: str
    platform: Platform
    i: Layout | None = None
    s: Layout | None = None
    translation_key: str | None = None
    unknown_option: str | None = None
    device_class: str | None = None
    unit: str | None = None
    state_class: str | None = None
    precision: int | None = None
    category: str | None = None

    def layout(self, protocol: Protocol) -> Layout | None:
        """Return the layout of the value in a protocol."""
        return self.i if protocol is Protocol.I else self.s

    def option_keys(self, protocol: Protocol) -> list[str]:
        """Return the option keys of an enum in a protocol."""
        layout = self.layout(protocol)
        keys = list(dict.fromkeys(key for _, key in layout.options)) if layout else []
        if self.unknown_option is not None and self.unknown_option not in keys:
            keys.append(self.unknown_option)
        return keys


@dataclass(frozen=True, slots=True, kw_only=True)
class OutdoorUnit:
    """What an outdoor unit (with its indoor unit) offers over the serial port."""

    model: str
    refrigerant: Refrigerant
    fan_factor: float
    features: Mapping[Feature, Status] = field(default_factory=dict)

    def status(self, feature: Feature) -> Status:
        """Return whether the unit has a feature."""
        return self.features.get(feature, Status.ABSENT)


# ----------------------------------------------------------- conversion


def _raw(payload: bytes, layout: Layout) -> int:
    if layout.size == 2:
        return int.from_bytes(
            payload[layout.offset : layout.offset + 2], "little", signed=layout.signed
        )
    return payload[layout.offset]


def decode(
    value: UartValue, layout: Layout, payload: bytes, unit: OutdoorUnit
) -> StateValue:
    """Return the state of a value from the payload of its register.

    The caller checks that the payload is long enough.
    """
    raw = _raw(payload, layout)
    match layout.converter:
        case Converter.BIT:
            raw = 1 if raw & layout.mask else 0
        case Converter.HIGH_NIBBLE:
            raw >>= 4
        case Converter.TARGET_TEMPERATURE:
            # 0x8000 stands for 0 °C; otherwise 1/256 K, cut to 0.1 K.
            if raw == 0x8000:
                return 0.0
            signed = raw - 0x10000 if raw & 0x8000 else raw
            return int(signed / 2.56) / 10
        case Converter.FAN_SPEED:
            return float(raw * unit.fan_factor)
        case Converter.SATURATION:
            signed = raw - 0x10000 if raw & 0x8000 else raw
            return saturation_temperature(unit.refrigerant, signed / 10)
        case Converter.NUMBER:
            pass
    match value.platform:
        case Platform.BINARY_SENSOR:
            return raw > 0
        case Platform.ENUM:
            for number, key in layout.options:
                if number == raw:
                    return key
            return value.unknown_option
    return round(raw * layout.factor / layout.divider, 6)


# ----------------------------------------------------------------- table


def _i(
    register: int,
    offset: int,
    feature: Feature,
    *,
    size: int = 1,
    converter: Converter = Converter.NUMBER,
    factor: float = 1.0,
    mask: int = 0,
    options: tuple[tuple[int, str], ...] = (),
) -> Layout:
    return Layout(
        register=register,
        offset=offset,
        feature=feature,
        size=size,
        converter=converter,
        factor=factor,
        mask=mask,
        options=options,
    )


def _s16(register: int, offset: int, feature: Feature, divider: float = 10.0) -> Layout:
    return Layout(
        register=register,
        offset=offset,
        feature=feature,
        size=2,
        signed=True,
        divider=divider,
    )


def _s_temperature(register: int, offset: int) -> Layout:
    """Temperature of the S protocol: unsigned 16 bit in 1/256 K."""
    return Layout(
        register=register,
        offset=offset,
        feature=Feature.S_VALUES,
        size=2,
        divider=256.0,
    )


def _bit(register: int, offset: int, mask: int, feature: Feature) -> Layout:
    return Layout(
        register=register,
        offset=offset,
        feature=feature,
        converter=Converter.BIT,
        mask=mask,
    )


def _count(key: str, offset: int) -> UartValue:
    return UartValue(
        key=key,
        platform=Platform.SENSOR,
        i=_i(0x00, offset, Feature.EQUIPMENT),
        state_class=MEASUREMENT,
        precision=0,
        category=DIAGNOSTIC,
    )


def _temperature(key: str, i: Layout | None, s: Layout | None = None) -> UartValue:
    return UartValue(
        key=key,
        platform=Platform.SENSOR,
        i=i,
        s=s,
        device_class=TEMPERATURE,
        unit=CELSIUS,
        state_class=MEASUREMENT,
        precision=1,
    )


def _binary(
    key: str,
    i: Layout | None,
    s: Layout | None = None,
    device_class: str | None = None,
) -> UartValue:
    return UartValue(
        key=key, platform=Platform.BINARY_SENSOR, i=i, s=s, device_class=device_class
    )


def _pressure(key: str, layout: Layout) -> UartValue:
    return UartValue(
        key=key,
        platform=Platform.SENSOR,
        i=layout,
        device_class=PRESSURE,
        unit=BAR,
        state_class=MEASUREMENT,
        precision=1,
    )


def _saturation(register: int, offset: int, feature: Feature) -> UartValue:
    return _temperature(
        "saturation_temp",
        Layout(
            register=register,
            offset=offset,
            feature=feature,
            size=2,
            signed=True,
            converter=Converter.SATURATION,
        ),
    )


def _target_temperature(key: str, offset: int) -> UartValue:
    return _temperature(
        key,
        Layout(
            register=0x10,
            offset=offset,
            feature=Feature.OUTDOOR_STATE,
            size=2,
            converter=Converter.TARGET_TEMPERATURE,
        ),
    )


_MODES_I: Final = (
    (0, "standby"),
    (1, "heating"),
    (2, "cooling"),
    (3, "unknown"),
    (4, "hot_water"),
    (5, "heating_hot_water"),
    (6, "cooling_hot_water"),
)
_MODES_S: Final = (
    (0x00, "fan_only"),
    (0x01, "heating"),
    (0x02, "cooling"),
    (0x03, "auto"),
    (0x04, "ventilation"),
    (0x05, "auto_cool"),
    (0x06, "auto_heat"),
    (0x07, "dry"),
    (0x08, "aux"),
    (0x09, "cooling_storage"),
    (0x0A, "heating_storage"),
    (0x0B, "stored_thermal_cooling_1"),
    (0x0C, "stored_thermal_cooling_2"),
    (0x0D, "stored_thermal_cooling_3"),
    (0x0E, "stored_thermal_cooling_4"),
    (0x0F, "stored_thermal_heating_1"),
    (0x10, "stored_thermal_heating_2"),
    (0x11, "stored_thermal_heating_3"),
    (0x12, "stored_thermal_heating_4"),
)

UART_VALUES: Final[tuple[UartValue, ...]] = (
    # 0x00: equipment of the outdoor unit
    _count("outdoor_inv_compressors", 1),
    _count("outdoor_std_compressors", 2),
    _count("outdoor_fans", 3),
    _count("outdoor_expansion_valves", 4),
    _count("outdoor_4_way_valves", 5),
    _count("outdoor_crankcase_heaters", 6),
    _count("outdoor_solenoid_valves", 7),
    _count("indoor_units_max", 8),
    _count("indoor_units_connected", 9),
    # 0x10: state of the outdoor unit
    _binary("press_eq", _bit(0x10, 1, 0x04, Feature.OUTDOOR_STATE)),
    _binary(
        "defrost_operation",
        _bit(0x10, 1, 0x10, Feature.OUTDOOR_STATE),
        device_class=RUNNING,
    ),
    _binary("startup_control", _bit(0x10, 1, 0x20, Feature.OUTDOOR_STATE)),
    _target_temperature("tgt_evap_temp", 6),
    _target_temperature("tgt_cond_temp", 8),
    # 0x20: temperatures and pressure of the outdoor unit
    _temperature("outdoor_temp", _s16(0x20, 0, Feature.OUTDOOR_TEMPERATURES)),
    _temperature("temp_after_compr", _s16(0x20, 4, Feature.OUTDOOR_TEMPERATURES)),
    _temperature("exch_temp", _s16(0x20, 8, Feature.OUTDOOR_TEMPERATURES)),
    _temperature("heat_sink_temp", _s16(0x20, 12, Feature.HEAT_SINK)),
    _pressure("refrigerant_pressure", _s16(0x20, 14, Feature.PRESSURE_0X20)),
    _saturation(0x20, 14, Feature.PRESSURE_0X20),
    # 0x21: inverter
    UartValue(
        key="inv_prim_current",
        platform=Platform.SENSOR,
        i=_s16(0x21, 0, Feature.CURRENTS),
        device_class=CURRENT,
        unit=AMPERE,
        state_class=MEASUREMENT,
        precision=1,
    ),
    UartValue(
        key="inv_sec_current",
        platform=Platform.SENSOR,
        i=_s16(0x21, 2, Feature.CURRENTS),
        device_class=CURRENT,
        unit=AMPERE,
        state_class=MEASUREMENT,
        precision=1,
    ),
    UartValue(
        key="voltage",
        platform=Platform.SENSOR,
        i=_s16(0x21, 4, Feature.VOLTAGE, divider=1.0),
        device_class=VOLTAGE,
        unit=VOLT,
        state_class=MEASUREMENT,
        precision=0,
    ),
    # 0x30: compressor, fan, expansion valve, 4-way valve
    UartValue(
        key="inv_freq",
        platform=Platform.SENSOR,
        i=_i(0x30, 0, Feature.COMPRESSOR, factor=60.0),
        unit=RPM,
        state_class=MEASUREMENT,
        precision=0,
    ),
    UartValue(
        key="fan_speed",
        platform=Platform.SENSOR,
        i=_i(0x30, 1, Feature.COMPRESSOR, converter=Converter.FAN_SPEED),
        unit=RPM,
        state_class=MEASUREMENT,
        precision=0,
    ),
    UartValue(
        key="exv",
        platform=Platform.SENSOR,
        i=_i(0x30, 3, Feature.COMPRESSOR, size=2),
        unit=PULSES,
        state_class=MEASUREMENT,
        precision=0,
    ),
    UartValue(
        key="4_way_valve",
        platform=Platform.ENUM,
        # The valve is in the cooling position while defrosting as well.
        i=_i(
            0x30,
            7,
            Feature.FOUR_WAY_VALVE,
            converter=Converter.BIT,
            mask=0x80,
            options=((1, "heating"), (0, "cooling")),
        ),
    ),
    # 0x60: state of the indoor unit
    UartValue(
        key="mode_of_operating",
        platform=Platform.ENUM,
        translation_key="uart_mode_of_operating",
        i=_i(
            0x60,
            2,
            Feature.INDOOR_STATE,
            converter=Converter.HIGH_NIBBLE,
            options=_MODES_I,
        ),
        s=Layout(register=0x55, offset=0, feature=Feature.S_VALUES, options=_MODES_S),
        unknown_option="unknown",
    ),
    _binary("thermostat", _bit(0x60, 2, 0x08, Feature.INDOOR_STATE)),
    _temperature("dhw_setpoint", _s16(0x60, 7, Feature.INDOOR_STATE)),
    _temperature("supply_setpoint", _s16(0x60, 9, Feature.INDOOR_STATE)),
    _binary("flow_switch", _bit(0x60, 11, 0x80, Feature.INDOOR_STATE)),
    _binary(
        "water_pump",
        _bit(0x60, 12, 0x02, Feature.INDOOR_STATE),
        device_class=RUNNING,
    ),
    UartValue(
        key="3_way_valve",
        platform=Platform.ENUM,
        i=_i(
            0x60,
            12,
            Feature.INDOOR_STATE,
            converter=Converter.BIT,
            mask=0x40,
            options=((0, "heating"), (1, "hot_water")),
        ),
    ),
    _binary("buh1", _bit(0x60, 12, 0x10, Feature.INDOOR_STATE), device_class=RUNNING),
    _binary("buh2", _bit(0x60, 12, 0x08, Feature.INDOOR_STATE), device_class=RUNNING),
    _binary(
        "buh_bsh", _bit(0x60, 12, 0x20, Feature.INDOOR_STATE), device_class=RUNNING
    ),
    # 0x61: water temperatures and liquid line
    _temperature(
        "tv",
        _s16(0x61, 2, Feature.INDOOR_TEMPERATURES),
        _s_temperature(0x54, 4),
    ),
    _temperature("tv_bh", _s16(0x61, 4, Feature.INDOOR_TEMPERATURES)),
    _temperature(
        "t_liq",
        _s16(0x61, 6, Feature.INDOOR_TEMPERATURES),
        _s_temperature(0x54, 0),
    ),
    _temperature(
        "tr",
        _s16(0x61, 8, Feature.INDOOR_TEMPERATURES),
        _s_temperature(0x54, 2),
    ),
    _temperature(
        "dhw_temp",
        _s16(0x61, 10, Feature.INDOOR_TEMPERATURES),
        _s_temperature(0x54, 8),
    ),
    # 0x62: water circuit and refrigerant pressure
    _binary(
        "circulation_pump",
        _bit(0x62, 8, 0x04, Feature.WATER),
        Layout(register=0x53, offset=0, feature=Feature.S_VALUES),
        device_class=RUNNING,
    ),
    _binary(
        "dhw_priority", None, Layout(register=0x53, offset=5, feature=Feature.S_VALUES)
    ),
    UartValue(
        key="flow_rate",
        platform=Platform.SENSOR,
        i=Layout(
            register=0x62,
            offset=9,
            feature=Feature.WATER,
            size=2,
            signed=True,
            factor=FLOW_FACTOR,
        ),
        device_class=VOLUME_FLOW_RATE,
        unit=LITERS_PER_HOUR,
        state_class=MEASUREMENT,
        precision=0,
    ),
    _pressure("refrigerant_pressure", _s16(0x62, 15, Feature.PRESSURE_0X62)),
    _saturation(0x62, 15, Feature.PRESSURE_0X62),
    _pressure("discharge_pressure", _s16(0x62, 15, Feature.DISCHARGE_PRESSURE)),
)


# --------------------------------------------------------------- profiles

_INDOOR: Final = {
    Feature.INDOOR_STATE: Status.CONFIRMED,
    Feature.INDOOR_TEMPERATURES: Status.CONFIRMED,
    Feature.S_VALUES: Status.CONFIRMED,
}

_UNCONFIRMED_OUTDOOR: Final = dict.fromkeys(
    (
        Feature.EQUIPMENT,
        Feature.OUTDOOR_STATE,
        Feature.OUTDOOR_TEMPERATURES,
        Feature.HEAT_SINK,
        Feature.PRESSURE_0X20,
        Feature.CURRENTS,
        Feature.VOLTAGE,
        Feature.COMPRESSOR,
        Feature.FOUR_WAY_VALVE,
        Feature.WATER,
        Feature.DISCHARGE_PRESSURE,
    ),
    Status.UNCONFIRMED,
)

# RRLQ...CAV3 on a Rotex HPSU: all outdoor registers seen in real frames;
# 0x21 was only seen without the voltage, 0x62 not at all.
_CAV3: Final = {
    **_INDOOR,
    **_UNCONFIRMED_OUTDOOR,
    Feature.EQUIPMENT: Status.CONFIRMED,
    Feature.OUTDOOR_STATE: Status.CONFIRMED,
    Feature.OUTDOOR_TEMPERATURES: Status.CONFIRMED,
    Feature.HEAT_SINK: Status.CONFIRMED,
    Feature.PRESSURE_0X20: Status.CONFIRMED,
    Feature.CURRENTS: Status.CONFIRMED,
    Feature.COMPRESSOR: Status.CONFIRMED,
    Feature.FOUR_WAY_VALVE: Status.CONFIRMED,
}

# An HPSU Compact with RRLQ006CAV3 does not answer 0x62.
_CAV3_WITHOUT_0X62: Final = {
    **_CAV3,
    Feature.WATER: Status.ABSENT,
    Feature.DISCHARGE_PRESSURE: Status.ABSENT,
}

# Same registers as the CAV3 units, not seen in real frames.
_UNCONFIRMED: Final = {**_INDOOR, **_UNCONFIRMED_OUTDOOR}

# Altherma 3 R E series (ERGA...EAV3): real frames of 0x10, 0x20, 0x30,
# 0x60-0x62. The refrigerant pressure is in 0x62; 0x20 has no pressure and
# no heat sink temperature, 0x30 no 4-way valve.
_ERGA_E: Final = {
    **_INDOOR,
    Feature.EQUIPMENT: Status.UNCONFIRMED,
    Feature.OUTDOOR_STATE: Status.CONFIRMED,
    Feature.OUTDOOR_TEMPERATURES: Status.CONFIRMED,
    Feature.CURRENTS: Status.UNCONFIRMED,
    Feature.VOLTAGE: Status.UNCONFIRMED,
    Feature.COMPRESSOR: Status.CONFIRMED,
    Feature.WATER: Status.CONFIRMED,
    Feature.PRESSURE_0X62: Status.CONFIRMED,
}


def _unit(
    model: str,
    features: Mapping[Feature, Status],
    *,
    refrigerant: Refrigerant = Refrigerant.R410A,
    fan_factor: float = 10.0,
) -> OutdoorUnit:
    return OutdoorUnit(
        model=model, refrigerant=refrigerant, fan_factor=fan_factor, features=features
    )


OUTDOOR_UNIT_PROFILES: Final[dict[str, OutdoorUnit]] = {
    unit.model: unit
    for unit in (
        _unit("RRLQ004CAV3", _CAV3),
        _unit("RRLQ006CAV3", _CAV3_WITHOUT_0X62),
        _unit("RRLQ008CAV3", _CAV3),
        _unit("RRLQ011CAW1", _UNCONFIRMED, fan_factor=100.0),
        _unit("ERLQ016CAW1", _UNCONFIRMED, fan_factor=100.0),
        _unit("ERGA04EAV3", _ERGA_E, refrigerant=Refrigerant.R32),
        _unit("ERGA06EAV3", _ERGA_E, refrigerant=Refrigerant.R32),
        _unit(
            "ERGA08DAV3", _UNCONFIRMED, refrigerant=Refrigerant.R32, fan_factor=100.0
        ),
        _unit("ERGA08EAV3", _ERGA_E, refrigerant=Refrigerant.R32),
        _unit("ERGA08EAV3H", _ERGA_E, refrigerant=Refrigerant.R32),
        _unit(
            "RRGA08DAV3", _UNCONFIRMED, refrigerant=Refrigerant.R32, fan_factor=100.0
        ),
        # Older indoor units with the S protocol.
        _unit("RRLQ008BAV3", _UNCONFIRMED),
        _unit("RDLQ014AA6V3", _UNCONFIRMED),
    )
}


@dataclass(frozen=True, slots=True, kw_only=True)
class ActiveValue:
    """A value of the table as a unit offers it in a protocol."""

    value: UartValue
    layout: Layout
    status: Status

    @property
    def key(self) -> str:
        """Return the key of the value."""
        return self.value.key


def unit_values(unit: OutdoorUnit, protocol: Protocol) -> dict[str, ActiveValue]:
    """Return the values a unit offers in a protocol, by key."""
    values: dict[str, ActiveValue] = {}
    for value in UART_VALUES:
        layout = value.layout(protocol)
        if layout is None:
            continue
        status = unit.status(layout.feature)
        if status is Status.ABSENT:
            continue
        if value.key in values:
            raise ValueError(f"{unit.model} has two variants of {value.key}")
        values[value.key] = ActiveValue(value=value, layout=layout, status=status)
    return values


def outdoor_unit(model: str | None) -> OutdoorUnit:
    """Return the profile of an outdoor unit; unknown models get no confirmed values."""
    if model in OUTDOOR_UNIT_PROFILES:
        return OUTDOOR_UNIT_PROFILES[model]
    return _unit(model or "unknown", _UNCONFIRMED)
