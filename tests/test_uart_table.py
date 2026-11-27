"""Tests for the UART value table, the profiles and the saturation tables."""

import itertools
import re

from data.saturation_1k import R32, R410A
import pytest

from custom_components.daikin_heat_pump_control.const import OUTDOOR_UNITS
from custom_components.daikin_heat_pump_control.uart import saturation_tables
from custom_components.daikin_heat_pump_control.uart.protocol import Protocol
from custom_components.daikin_heat_pump_control.uart.saturation import (
    AMBIENT_PRESSURE,
    Refrigerant,
    saturation_temperature,
)
from custom_components.daikin_heat_pump_control.uart.table import (
    OUTDOOR_UNIT_PROFILES,
    UART_VALUES,
    Status,
    decode,
    outdoor_unit,
    unit_values,
)
from custom_components.daikin_heat_pump_control.uart_coordinator import (
    resolve_protocol,
    uart_entities,
)

from sim.indoor import (
    ERGA_FRAMES,
    HPSU_0X10_STARTUP,
    HPSU_0X21,
    HPSU_0X30_DEFROST,
    HPSU_0X60_HOT_WATER,
    HPSU_0X60_STANDBY,
    HPSU_FRAMES,
    S_FRAMES,
    le16,
    payload,
)

# Largest error of the interpolated 1 K table against the reference equations
# (R32: 0.0181 K, R410A: 0.0170 K, measured with CoolProp).
OLD_TABLE_ERROR = 0.0181
# The fine table stores 0.0001 bar: up to 0.0017 K at -65 °C.
FINE_TABLE_ERROR = 0.002

TRANSLATION_KEY = re.compile(r"^(?!.+[_-]{2})(?![_-])[a-z0-9-_]+(?<![_-])$")


def _decode_all(
    model: str, protocol: Protocol, frames: tuple[bytes, ...]
) -> dict[str, object]:
    unit = OUTDOOR_UNIT_PROFILES[model]
    values = unit_values(unit, protocol)
    states: dict[str, object] = {}
    for frame in frames:
        register, data = (
            (frame[1], frame[3:-1])
            if protocol is Protocol.I
            else (frame[0], frame[1:-1])
        )
        for key, active in values.items():
            if active.layout.register == register and active.layout.fits(data):
                states[key] = decode(active.value, active.layout, data, unit)
    return states


def test_hpsu_frames() -> None:
    """The real frames of a Rotex HPSU are decoded."""
    states = _decode_all("RRLQ008CAV3", Protocol.I, HPSU_FRAMES)
    assert states == {
        "outdoor_inv_compressors": 1.0,
        "outdoor_std_compressors": 0.0,
        "outdoor_fans": 1.0,
        "outdoor_expansion_valves": 1.0,
        "outdoor_4_way_valves": 1.0,
        "outdoor_crankcase_heaters": 0.0,
        "outdoor_solenoid_valves": 2.0,
        "indoor_units_max": 1.0,
        "indoor_units_connected": 1.0,
        "press_eq": False,
        "defrost_operation": False,
        "startup_control": False,
        "tgt_evap_temp": 34.3,
        "tgt_cond_temp": 0.0,
        "outdoor_temp": -3.5,
        "temp_after_compr": 59.5,
        "exch_temp": -6.5,
        "heat_sink_temp": 7.0,
        "refrigerant_pressure": 19.1,
        "saturation_temp": 32.5,
        "inv_prim_current": 5.8,
        "inv_sec_current": 5.0,
        "inv_freq": 3480.0,
        "fan_speed": 800.0,
        "exv": 465.0,
        "4_way_valve": "heating",
        "mode_of_operating": "heating",
        "thermostat": True,
        "dhw_setpoint": 49.0,
        "supply_setpoint": 33.0,
        "flow_switch": True,
        "water_pump": True,
        "3_way_valve": "heating",
        "buh1": False,
        "buh2": False,
        "buh_bsh": False,
        "tv": 29.7,
        "tv_bh": 29.9,
        "t_liq": 29.7,
        "tr": 26.7,
        "dhw_temp": 48.0,
    }
    # 0x21 has no voltage: five payload bytes only.
    voltage = unit_values(OUTDOOR_UNIT_PROFILES["RRLQ008CAV3"], Protocol.I)["voltage"]
    assert not voltage.layout.fits(HPSU_0X21[3:-1])


def test_other_hpsu_states() -> None:
    """Hot water, standby, defrost and start-up frames."""
    states = _decode_all(
        "RRLQ008CAV3",
        Protocol.I,
        (HPSU_0X60_HOT_WATER, HPSU_0X10_STARTUP, HPSU_0X30_DEFROST),
    )
    assert states["3_way_valve"] == "hot_water"
    assert states["supply_setpoint"] == 48.0
    assert states["mode_of_operating"] == "hot_water"
    assert states["startup_control"] is True
    assert states["4_way_valve"] == "cooling"
    assert states["inv_freq"] == 44 * 60
    states = _decode_all("RRLQ008CAV3", Protocol.I, (HPSU_0X60_STANDBY,))
    assert states["water_pump"] is False
    assert states["thermostat"] is False
    assert states["flow_switch"] is False
    assert states["dhw_setpoint"] == 25.0
    assert states["mode_of_operating"] == "standby"


def test_erga_e_frames() -> None:
    """ERGA E: pressure from 0x62 with R32, flow rate in L/h."""
    states = _decode_all("ERGA06EAV3", Protocol.I, ERGA_FRAMES)
    assert states["refrigerant_pressure"] == 18.0
    assert states["saturation_temp"] == 29.5
    # 14.8 l/min
    assert states["flow_rate"] == 888.0
    assert states["circulation_pump"] is False
    assert states["temp_after_compr"] == 43.0
    assert states["t_liq"] == 29.2
    assert states["inv_freq"] == 22 * 60
    for key in ("heat_sink_temp", "4_way_valve", "discharge_pressure"):
        assert key not in states


def test_s_frames() -> None:
    """S protocol values."""
    states = _decode_all("RRLQ008BAV3", Protocol.S, S_FRAMES)
    assert states == {
        "mode_of_operating": "heating",
        "tv": 29.5,
        "t_liq": 0.0,
        "tr": 26.5,
        "dhw_temp": 0.0,
        "circulation_pump": True,
        "dhw_priority": False,
    }


def test_special_conversions() -> None:
    """Target temperatures, unknown modes, fan factor."""
    unit = OUTDOOR_UNIT_PROFILES["RRLQ011CAW1"]
    values = unit_values(unit, Protocol.I)
    target = values["tgt_evap_temp"]
    data = payload(16, {6: (479).to_bytes(2, "little")})
    assert decode(target.value, target.layout, data, unit) == 18.7
    data = payload(16, {6: b"\x00\x80"})
    assert decode(target.value, target.layout, data, unit) == 0.0
    data = payload(16, {6: (-479 & 0xFFFF).to_bytes(2, "little")})
    assert decode(target.value, target.layout, data, unit) == -18.7
    fan = values["fan_speed"]
    assert decode(fan.value, fan.layout, payload(12, {1: b"\x51"}), unit) == 8100.0
    mode = values["mode_of_operating"]
    assert decode(mode.value, mode.layout, payload(13, {2: b"\x30"}), unit) == "unknown"
    assert decode(mode.value, mode.layout, payload(13, {2: b"\x90"}), unit) == "unknown"
    saturation = values["saturation_temp"]
    data = payload(17, {14: le16(48.0)})
    assert decode(saturation.value, saturation.layout, data, unit) is None


def test_profiles() -> None:
    """Every outdoor unit has a profile without conflicting variants."""
    assert set(OUTDOOR_UNIT_PROFILES) == set(OUTDOOR_UNITS)
    for unit in OUTDOOR_UNIT_PROFILES.values():
        for protocol in Protocol:
            unit_values(unit, protocol)
    erga = unit_values(OUTDOOR_UNIT_PROFILES["ERGA08EAV3"], Protocol.I)
    assert erga["refrigerant_pressure"].layout.register == 0x62
    assert "heat_sink_temp" not in erga
    cav3 = unit_values(OUTDOOR_UNIT_PROFILES["RRLQ006CAV3"], Protocol.I)
    assert not [value for value in cav3.values() if value.layout.register == 0x62]
    assert cav3["refrigerant_pressure"].layout.register == 0x20
    s_values = unit_values(OUTDOOR_UNIT_PROFILES["RDLQ014AA6V3"], Protocol.S)
    assert {value.layout.register for value in s_values.values()} == {
        0x53,
        0x54,
        0x55,
    }
    unknown = outdoor_unit("XYZ")
    assert unknown.model == "XYZ"
    assert {value.status for value in unit_values(unknown, Protocol.I).values()} == {
        Status.CONFIRMED,
        Status.UNCONFIRMED,
    }
    assert outdoor_unit(None).model == "unknown"
    assert outdoor_unit("ERGA04EAV3").refrigerant is Refrigerant.R32


def test_entities_per_profile() -> None:
    """Confirmed values are enabled, unconfirmed ones disabled."""
    assert uart_entities(OUTDOOR_UNIT_PROFILES["RRLQ008CAV3"], None) == {}
    cav3 = uart_entities(OUTDOOR_UNIT_PROFILES["RRLQ008CAV3"], Protocol.I)
    assert cav3["tv"] is True
    assert cav3["refrigerant_pressure"] is True
    assert cav3["voltage"] is False
    assert cav3["flow_rate"] is False
    assert cav3["thermal_power"] is False
    assert cav3["subcooling"] is True
    assert cav3["temperature_spread"] is True
    assert cav3["temperature_spread_raw"] is False
    assert "dhw_priority" not in cav3
    no_0x62 = uart_entities(OUTDOOR_UNIT_PROFILES["RRLQ006CAV3"], Protocol.I)
    assert "flow_rate" not in no_0x62
    assert "thermal_power" not in no_0x62
    erga = uart_entities(OUTDOOR_UNIT_PROFILES["ERGA06EAV3"], Protocol.I)
    assert erga["thermal_power"] is True
    assert erga["thermal_power_raw"] is False
    assert erga["subcooling"] is True
    assert erga["inv_prim_current"] is False
    w1 = uart_entities(OUTDOOR_UNIT_PROFILES["RRLQ011CAW1"], Protocol.I)
    assert w1["subcooling"] is False
    assert w1["tv"] is True
    s_unit = uart_entities(OUTDOOR_UNIT_PROFILES["RRLQ008BAV3"], Protocol.S)
    assert set(s_unit) == {
        "mode_of_operating",
        "tv",
        "t_liq",
        "tr",
        "dhw_temp",
        "circulation_pump",
        "dhw_priority",
        "temperature_spread",
        "temperature_spread_raw",
    }


def test_resolve_protocol() -> None:
    """A fixed option wins; the detected protocol counts only with auto."""
    assert resolve_protocol("i", "s") == (Protocol.I, False)
    assert resolve_protocol("s", None) == (Protocol.S, False)
    assert resolve_protocol("auto", "s") == (Protocol.S, True)
    assert resolve_protocol("auto", None) == (None, True)
    assert resolve_protocol(None, "x") == (None, True)


def test_translation_keys() -> None:
    """Keys are valid translation keys."""
    for value in UART_VALUES:
        assert TRANSLATION_KEY.match(value.translation_key or value.key)
        for protocol in Protocol:
            for option in value.option_keys(protocol):
                assert TRANSLATION_KEY.match(option)


@pytest.mark.parametrize(
    ("refrigerant", "pressure", "expected"),
    [
        (Refrigerant.R410A, 18.0, 30.2),
        (Refrigerant.R32, 18.0, 29.5),
        (Refrigerant.R32, 18.5, 30.5),
        (Refrigerant.R410A, 48.0, None),
        (Refrigerant.R410A, -0.6, None),
    ],
)
def test_saturation_temperature(
    refrigerant: Refrigerant, pressure: float, expected: float | None
) -> None:
    """Check values of the saturation temperature."""
    assert saturation_temperature(refrigerant, pressure) == expected


def _interpolate(table: tuple[tuple[float, float], ...], pressure: float) -> float:
    for (t1, p1), (t2, p2) in itertools.pairwise(table):
        if pressure <= p2:
            return t1 + (pressure - p1) * (t2 - t1) / (p2 - p1)
    raise AssertionError(pressure)  # pragma: no cover


@pytest.mark.parametrize(
    ("refrigerant", "reference"),
    [(Refrigerant.R410A, R410A), (Refrigerant.R32, R32)],
)
def test_saturation_against_1k_table(
    refrigerant: Refrigerant, reference: tuple[tuple[float, float], ...]
) -> None:
    """The 0.1 K table agrees with the 1 K table within the error of the latter.

    Against the reference equations of state, the linear interpolation of the
    1 K table is off by up to 0.018 K (its points by up to 0.016 K). A 1 K
    chord of the fine table is off the fine curve by less than 0.01 K.
    """
    assert all(
        _chord_error(refrigerant, t1, t2) < 0.01
        for (t1, _), (t2, _) in itertools.pairwise(reference)
    )
    for (_, p1), (_, p2) in itertools.pairwise(reference):
        for step in range(1, 20):
            pressure = p1 + (p2 - p1) * step / 20
            new = saturation_temperature(refrigerant, pressure - AMBIENT_PRESSURE, None)
            assert new is not None
            deviation = abs(new - _interpolate(reference, pressure))
            assert deviation <= OLD_TABLE_ERROR + FINE_TABLE_ERROR


def _pressure_at(refrigerant: Refrigerant, temperature: float) -> float:
    table = (
        saturation_tables.R32
        if refrigerant is Refrigerant.R32
        else saturation_tables.R410A
    )
    index = round((temperature - saturation_tables.FIRST_TEMPERATURE) * 10)
    return table[index]


def _chord_error(refrigerant: Refrigerant, t1: float, t2: float) -> float:
    """Return how far the chord between t1 and t2 is off the fine table."""
    p1 = _pressure_at(refrigerant, t1)
    p2 = _pressure_at(refrigerant, t2)
    error = 0.0
    for step in range(1, 10):
        temperature = t1 + step / 10
        pressure = _pressure_at(refrigerant, temperature)
        chord = t1 + (pressure - p1) * (t2 - t1) / (p2 - p1)
        error = max(error, abs(chord - temperature))
    return error
