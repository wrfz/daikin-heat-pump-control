"""Tests for the UART values against the simulated indoor unit."""

from unittest.mock import patch

from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant.common import MockConfigEntry, snapshot_platform
from syrupy.assertion import SnapshotAssertion

from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from helpers import (
    DOMAIN,
    ENTRY_ID,
    daikin_entry,
    run_bus,
    state_of as _state,
    wait_for_state,
)
from sim.esp import SimulatedEsp
from sim.heat_pump import HeatPump
from sim.indoor import (
    ERGA_0X10,
    ERGA_0X60,
    ERGA_0X62,
    ERGA_FRAMES,
    HPSU_0X20,
    HPSU_0X30_DEFROST,
    HPSU_0X30_HEATING,
    HPSU_0X30_STANDSTILL,
    HPSU_0X60_HOT_WATER,
    hpsu_0x20,
    hpsu_0x61,
    i_frame,
    load_indoor,
    load_s,
    with_bytes,
)

FULL_POLL = 3  # s to read every polled register once
TV = "sensor.daikin_uart_tv"
SUBCOOLING = "sensor.daikin_uart_subcooling"
SUPERHEAT = "sensor.daikin_uart_discharge_superheat"
SATURATION = "sensor.daikin_uart_saturation_temperature"


async def _run(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, seconds: float
) -> None:
    await run_bus(hass, freezer, seconds, step=0.1)


async def _setup(
    hass: HomeAssistant,
    esp: SimulatedEsp,
    outdoor_unit: str = "RRLQ008CAV3",
    protocol: str = "i",
    detected: str | None = None,
) -> MockConfigEntry:
    entry = daikin_entry(
        hass,
        uart=esp,
        options={"outdoor_unit": outdoor_unit, "uart_protocol": protocol},
    )
    if detected is not None:
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, "uart_detected_protocol": detected}
        )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _erga(heat_pump: HeatPump) -> None:
    heat_pump.uart_registers.clear()
    load_indoor(heat_pump, ERGA_FRAMES)


def _requests(heat_pump: HeatPump, register: int) -> int:
    return heat_pump.uart_requests.count(register)


async def test_values_read(
    hass: HomeAssistant, uart_esp: SimulatedEsp, freezer: FrozenDateTimeFactory
) -> None:
    """The values of a Rotex HPSU are read."""
    await _setup(hass, uart_esp)
    await _run(hass, freezer, FULL_POLL)
    assert _state(hass, TV) == "29.7"
    assert _state(hass, "sensor.daikin_uart_tr") == "26.7"
    assert _state(hass, "sensor.daikin_uart_outdoor_air_temperature") == "-3.5"
    assert _state(hass, "sensor.daikin_uart_refrigerant_pressure") == "19.1"
    assert _state(hass, SATURATION) == "32.5"
    assert _state(hass, "sensor.daikin_uart_compressor_speed") == "3480.0"
    assert _state(hass, "sensor.daikin_uart_fan_speed") == "800.0"
    assert _state(hass, "sensor.daikin_uart_4_way_valve") == "heating"
    assert _state(hass, "sensor.daikin_uart_3_way_valve") == "heating"
    assert _state(hass, "sensor.daikin_uart_operating_state") == "heating"
    assert _state(hass, "binary_sensor.daikin_uart_water_pump") == "on"
    assert hass.states.get("sensor.daikin_uart_voltage") is None  # disabled
    await _run(hass, freezer, 11)
    assert _state(hass, "sensor.daikin_uart_temperature_spread") == "3.0"


async def test_answers_in_time(
    hass: HomeAssistant,
    uart_esp: SimulatedEsp,
    heat_pump: HeatPump,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Every register is asked again 5 s after its answer."""
    await _setup(hass, uart_esp)
    await _run(hass, freezer, FULL_POLL)
    assert set(heat_pump.uart_requests) == {0x00, 0x10, 0x20, 0x21, 0x30, 0x60, 0x61}
    count = _requests(heat_pump, 0x61)
    await _run(hass, freezer, 5.5)
    assert _requests(heat_pump, 0x61) == count + 1


@pytest.mark.freeze_time("2026-11-27 12:00:00+00:00")
@pytest.mark.usefixtures("entity_registry_enabled_by_default")
@pytest.mark.parametrize("platform", [Platform.BINARY_SENSOR, Platform.SENSOR])
@pytest.mark.parametrize(
    ("outdoor_unit", "protocol"),
    [("RRLQ008CAV3", "i"), ("ERGA06EAV3", "i"), ("RRLQ008BAV3", "s")],
)
async def test_entities(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    uart_esp: SimulatedEsp,
    heat_pump: HeatPump,
    freezer: FrozenDateTimeFactory,
    snapshot: SnapshotAssertion,
    platform: Platform,
    outdoor_unit: str,
    protocol: str,
) -> None:
    """All UART entities of a unit with their states."""
    if outdoor_unit.startswith("ERGA"):
        _erga(heat_pump)
    if protocol == "s":
        load_s(heat_pump)
    with (
        patch("custom_components.daikin_heat_pump_control.PLATFORMS", [platform]),
        patch("custom_components.daikin_heat_pump_control.sensor.BRIDGE_SENSORS", ()),
    ):
        entry = await _setup(hass, uart_esp, outdoor_unit, protocol)
    await _run(hass, freezer, FULL_POLL)
    await snapshot_platform(hass, entity_registry, snapshot, entry.entry_id)


async def test_erga_e(
    hass: HomeAssistant,
    uart_esp: SimulatedEsp,
    heat_pump: HeatPump,
    freezer: FrozenDateTimeFactory,
) -> None:
    """ERGA E: pressure from 0x62 (R32), flow rate and thermal power."""
    _erga(heat_pump)
    await _setup(hass, uart_esp, "ERGA06EAV3")
    await _run(hass, freezer, FULL_POLL)
    assert _state(hass, "sensor.daikin_uart_refrigerant_pressure") == "18.0"
    assert _state(hass, SATURATION) == "29.5"
    assert _state(hass, "sensor.daikin_uart_flow_rate") == "888.0"
    assert hass.states.get("sensor.daikin_uart_heat_sink_temperature") is None
    assert hass.states.get("sensor.daikin_uart_4_way_valve") is None
    assert hass.states.get("sensor.daikin_uart_high_pressure") is None
    # (29.8 - 27.6) K * 4.19 kJ/(kg K) * 888 L/h / 3600 s/h
    await _run(hass, freezer, 11)
    assert _state(hass, "sensor.daikin_uart_thermal_power") == "2.27"


async def test_erga_e_subcooling(
    hass: HomeAssistant,
    uart_esp: SimulatedEsp,
    heat_pump: HeatPump,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Without 4-way valve, defrost and mode decide whether the circuit heats."""
    _erga(heat_pump)
    await _setup(hass, uart_esp, "ERGA06EAV3")
    await _run(hass, freezer, 7)
    assert _requests(heat_pump, 0x62) >= 2
    assert _state(hass, SUBCOOLING) == STATE_UNKNOWN
    heat_pump.set_uart_frame(with_bytes(ERGA_0X62, {15: b"\xb9\x00"}))  # 18.5 bar
    await _run(hass, freezer, 6)
    assert _state(hass, SATURATION) == "30.5"
    assert _state(hass, SUBCOOLING) == "1.3"
    assert _state(hass, SUPERHEAT) == "12.5"

    heat_pump.set_uart_frame(with_bytes(ERGA_0X10, {1: b"\x10"}))  # defrost
    await _run(hass, freezer, 6)
    assert _state(hass, "binary_sensor.daikin_uart_defrost") == "on"
    assert _state(hass, SUBCOOLING) == STATE_UNKNOWN

    heat_pump.set_uart_frame(ERGA_0X10)
    heat_pump.set_uart_frame(ERGA_0X62)
    await _run(hass, freezer, 6)
    assert _state(hass, SUBCOOLING) == "0.3"
    assert _state(hass, SUPERHEAT) == "13.5"

    # Cooling; the next 0x62 answer runs the computation.
    heat_pump.set_uart_frame(with_bytes(ERGA_0X60, {2: b"\x28"}))
    await _run(hass, freezer, 12)
    assert _state(hass, "sensor.daikin_uart_operating_state") == "cooling"
    assert _state(hass, SUBCOOLING) == STATE_UNKNOWN


async def test_hpsu_subcooling(
    hass: HomeAssistant,
    uart_esp: SimulatedEsp,
    heat_pump: HeatPump,
    freezer: FrozenDateTimeFactory,
) -> None:
    """One value per new outdoor frame; none while defrosting or stopped."""
    heat_pump.set_uart_frame(hpsu_0x61(t_liq=29.7))
    await _setup(hass, uart_esp)
    await _run(hass, freezer, 7)
    assert _state(hass, SUBCOOLING) == STATE_UNKNOWN

    heat_pump.set_uart_frame(hpsu_0x20(discharge=62.0, pressure=18.0))
    await _run(hass, freezer, 6)
    assert _state(hass, SATURATION) == "30.2"
    assert _state(hass, SUBCOOLING) == "0.5"
    assert _state(hass, SUPERHEAT) == "31.8"

    heat_pump.set_uart_frame(hpsu_0x61(t_liq=29.0))
    await _run(hass, freezer, 6)
    assert _state(hass, SUBCOOLING) == "0.5"
    heat_pump.set_uart_frame(hpsu_0x20(discharge=62.5, pressure=18.0))
    await _run(hass, freezer, 6)
    assert _state(hass, SUBCOOLING) == "1.2"
    assert _state(hass, SUPERHEAT) == "32.3"

    heat_pump.set_uart_frame(HPSU_0X30_DEFROST)
    await _run(hass, freezer, 6)
    assert _state(hass, "sensor.daikin_uart_4_way_valve") == "cooling"
    assert _state(hass, SUBCOOLING) == STATE_UNKNOWN
    heat_pump.set_uart_frame(HPSU_0X30_HEATING)
    await _run(hass, freezer, 6)
    assert _state(hass, SUBCOOLING) == STATE_UNKNOWN
    heat_pump.set_uart_frame(hpsu_0x20(discharge=60.0, pressure=18.0))
    await _run(hass, freezer, 6)
    assert _state(hass, SUBCOOLING) == "1.2"  # 30.2 - 29.0
    assert _state(hass, SUPERHEAT) == "29.8"

    heat_pump.set_uart_frame(hpsu_0x20(discharge=60.0, pressure=48.0))
    await _run(hass, freezer, 6)
    assert _state(hass, SATURATION) == STATE_UNKNOWN
    assert _state(hass, SUBCOOLING) == STATE_UNKNOWN
    heat_pump.set_uart_frame(HPSU_0X30_STANDSTILL)
    await _run(hass, freezer, 6)
    assert _state(hass, "sensor.daikin_uart_compressor_speed") == "0.0"
    assert _state(hass, SUPERHEAT) == STATE_UNKNOWN


async def test_s_protocol(
    hass: HomeAssistant,
    uart_esp: SimulatedEsp,
    heat_pump: HeatPump,
    freezer: FrozenDateTimeFactory,
) -> None:
    """With protocol S only the S registers are asked."""
    load_s(heat_pump)
    await _setup(hass, uart_esp, "RRLQ008BAV3", "s")
    await _run(hass, freezer, FULL_POLL)
    assert set(heat_pump.uart_requests) == {0x53, 0x54, 0x55}
    assert _state(hass, TV) == "29.5"
    assert _state(hass, "sensor.daikin_uart_tr") == "26.5"
    assert _state(hass, "sensor.daikin_uart_operating_state") == "heating"
    assert _state(hass, "binary_sensor.daikin_uart_circulation_pump") == "on"
    assert _state(hass, "binary_sensor.daikin_uart_hot_water_priority") == "off"
    assert hass.states.get("sensor.daikin_uart_outdoor_air_temperature") is None


async def test_detect_i(
    hass: HomeAssistant,
    uart_esp: SimulatedEsp,
    heat_pump: HeatPump,
    freezer: FrozenDateTimeFactory,
) -> None:
    """The detected protocol is stored and the entry reloads with its entities."""
    entry = await _setup(hass, uart_esp, protocol="auto")
    assert hass.states.get(TV) is None
    await _run(hass, freezer, 1)
    assert heat_pump.uart_requests[0] == 0x60
    assert entry.data["uart_detected_protocol"] == "i"
    await _run(hass, freezer, FULL_POLL)
    assert _state(hass, TV) == "29.7"
    assert entry.runtime_data.uart is not None
    assert entry.runtime_data.uart.may_detect


@pytest.mark.parametrize("foreign_reply", [b"\x15\xea", None])
async def test_detect_s(
    hass: HomeAssistant,
    uart_esp: SimulatedEsp,
    heat_pump: HeatPump,
    freezer: FrozenDateTimeFactory,
    foreign_reply: bytes | None,
) -> None:
    """An S unit rejects or ignores the I probe."""
    load_s(heat_pump)
    heat_pump.uart_foreign_reply = foreign_reply
    entry = await _setup(hass, uart_esp, "RRLQ008BAV3", "auto")
    await _run(hass, freezer, 3)
    assert entry.data["uart_detected_protocol"] == "s"
    # Without a NAK the S probe for 0x53 comes first.
    first = 0x53 if foreign_reply is None else 0x55
    assert heat_pump.uart_requests[0] == first
    await _run(hass, freezer, FULL_POLL)
    assert _state(hass, TV) == "29.5"
    assert hass.states.get("binary_sensor.daikin_uart_hot_water_priority") is not None


async def test_detection_without_answer(
    hass: HomeAssistant,
    uart_esp: SimulatedEsp,
    heat_pump: HeatPump,
    freezer: FrozenDateTimeFactory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Without any answer I is tried; the first I answer counts as detection."""
    heat_pump.uart_silent.update({0x60, 0x53})
    heat_pump.uart_foreign_reply = None
    entry = await _setup(hass, uart_esp, protocol="auto")
    await _run(hass, freezer, 5)
    assert "No answer to the UART protocol detection; trying I" in caplog.text
    assert "uart_detected_protocol" not in entry.data
    assert entry.runtime_data.uart is not None
    assert entry.runtime_data.uart.diagnostics()["detections"][0]["protocol"] is None
    assert hass.states.get(TV) is None

    heat_pump.uart_silent.clear()
    await _run(hass, freezer, 4)
    assert "UART protocol I confirmed by an answer" in caplog.text
    assert entry.data["uart_detected_protocol"] == "i"


async def test_detection_again_after_failures(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    uart_esp: SimulatedEsp,
    heat_pump: HeatPump,
    freezer: FrozenDateTimeFactory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """When nothing answers any more, the protocol is detected again."""
    entry = await _setup(hass, uart_esp, protocol="auto", detected="i")
    await _run(hass, freezer, FULL_POLL)
    assert _state(hass, TV) == "29.7"
    speed = "sensor.daikin_uart_compressor_speed"
    assert entity_registry.async_get(speed) is not None

    load_s(heat_pump)
    heat_pump.uart_foreign_reply = None
    await _run(hass, freezer, 70)
    assert "no longer answers in UART protocol I but in S" in caplog.text
    assert entry.data["uart_detected_protocol"] == "s"
    await _run(hass, freezer, FULL_POLL)
    assert _state(hass, TV) == "29.5"
    assert entity_registry.async_get(speed) is None


async def test_detection_finds_the_same_protocol(
    hass: HomeAssistant,
    uart_esp: SimulatedEsp,
    heat_pump: HeatPump,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A unit that rejects the S probe keeps protocol I."""
    entry = await _setup(hass, uart_esp, protocol="auto", detected="i")
    heat_pump.uart_silent.update({0x00, 0x10, 0x20, 0x21, 0x30, 0x60, 0x61})
    await _run(hass, freezer, 70)
    uart = entry.runtime_data.uart
    assert uart is not None
    assert uart.diagnostics()["detections"][-1]["protocol"] == "i"
    assert entry.data["uart_detected_protocol"] == "i"
    assert _state(hass, TV) == STATE_UNAVAILABLE
    heat_pump.uart_silent.clear()
    await _run(hass, freezer, 4)
    assert not uart.scheduler.is_failed(0x61)
    assert _state(hass, TV) == "29.7"


async def test_failed_register(
    hass: HomeAssistant,
    uart_esp: SimulatedEsp,
    heat_pump: HeatPump,
    freezer: FrozenDateTimeFactory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A register without answer is asked every 10 minutes; its values are unavailable."""
    heat_pump.uart_silent.add(0x21)
    current = "sensor.daikin_uart_inverter_primary_current"
    await _setup(hass, uart_esp)
    await _run(hass, freezer, 12)
    assert _state(hass, current) == STATE_UNAVAILABLE
    assert _state(hass, TV) == "29.7"
    assert caplog.text.count("UART register 0x21 does not answer") == 1
    assert _requests(heat_pump, 0x21) == 3
    await _run(hass, freezer, 60)
    assert _requests(heat_pump, 0x21) == 3

    heat_pump.uart_silent.clear()
    await _run(hass, freezer, 600)
    assert _state(hass, current) == "5.8"
    assert "UART register 0x21 answers again" in caplog.text


async def test_nak_and_bad_frames(
    hass: HomeAssistant,
    uart_esp: SimulatedEsp,
    heat_pump: HeatPump,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Wrong checksums, answers of other registers and NAKs set no value."""
    entry = await _setup(hass, uart_esp)
    await _run(hass, freezer, FULL_POLL)
    bad = bytearray(hpsu_0x61(tv=35.0))
    bad[-1] ^= 0xFF
    for answer, tv in (
        (bytes(bad), "31.0"),
        (i_frame(0x62, bytes(17)), "32.0"),
        (b"\x15\xea", "33.0"),
    ):
        heat_pump.set_uart_frame(hpsu_0x61(tv=float(tv)))
        heat_pump.uart_next_answer[0x61] = answer
        await _run(hass, freezer, 9)
        assert _state(hass, TV) == tv
    uart = entry.runtime_data.uart
    assert uart is not None
    assert uart.scheduler.registers[0x61].lost == 3


async def test_short_payload(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    uart_esp: SimulatedEsp,
    freezer: FrozenDateTimeFactory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A value beyond the payload stays unknown and is reported once."""
    entry = daikin_entry(
        hass,
        uart=uart_esp,
        options={"outdoor_unit": "RRLQ008CAV3", "uart_protocol": "i"},
    )
    entity_registry.async_get_or_create(
        "sensor",
        DOMAIN,
        f"{ENTRY_ID}_uart_voltage",
        suggested_object_id="v",
        config_entry=entry,
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    await _run(hass, freezer, 12)
    assert _state(hass, "sensor.v") == STATE_UNKNOWN
    assert caplog.text.count("voltage is not in it") == 1


async def test_hot_water_frame(
    hass: HomeAssistant,
    uart_esp: SimulatedEsp,
    heat_pump: HeatPump,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Changed frames reach the entities."""
    await _setup(hass, uart_esp)
    await _run(hass, freezer, FULL_POLL)
    heat_pump.set_uart_frame(HPSU_0X60_HOT_WATER)
    await _run(hass, freezer, 6)
    assert _state(hass, "sensor.daikin_uart_3_way_valve") == "hot_water"
    assert _state(hass, "sensor.daikin_uart_flow_setpoint") == "48.0"


async def test_connection_loss(
    hass: HomeAssistant,
    uart_esp: SimulatedEsp,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Values are unavailable without connection and read again afterwards."""
    await _setup(hass, uart_esp)
    await _run(hass, freezer, FULL_POLL)
    await uart_esp.drop_connections()
    await wait_for_state(hass, TV, STATE_UNAVAILABLE)
    await _run(hass, freezer, 2 + FULL_POLL)
    assert _state(hass, TV) == "29.7"


async def test_other_protocol_entities_removed(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    uart_esp: SimulatedEsp,
) -> None:
    """Entities the unit does not offer in the protocol are removed."""
    entry = daikin_entry(
        hass,
        uart=uart_esp,
        options={"outdoor_unit": "RRLQ008CAV3", "uart_protocol": "i"},
    )
    for platform, unique_id in (
        ("binary_sensor", f"{ENTRY_ID}_uart_dhw_priority"),
        ("sensor", f"{ENTRY_ID}_can_tv"),
    ):
        entity_registry.async_get_or_create(
            platform, DOMAIN, unique_id, config_entry=entry
        )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    keys = {
        item.unique_id
        for item in er.async_entries_for_config_entry(entity_registry, ENTRY_ID)
    }
    assert f"{ENTRY_ID}_uart_dhw_priority" not in keys
    assert f"{ENTRY_ID}_can_tv" in keys
    assert f"{ENTRY_ID}_uart_tv" in keys


async def test_options_change_detects_again(
    hass: HomeAssistant, uart_esp: SimulatedEsp
) -> None:
    """Changing the UART options forgets the detected protocol."""
    entry = await _setup(hass, uart_esp, protocol="auto", detected="i")
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"outdoor_unit": "RRLQ008CAV3", "uart_protocol": "auto"}
    )
    await hass.async_block_till_done()
    assert entry.data["uart_detected_protocol"] == "i"
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"outdoor_unit": "RRLQ006CAV3", "uart_protocol": "auto"}
    )
    await hass.async_block_till_done()
    assert "uart_detected_protocol" not in entry.data


async def test_diagnostics_values(
    hass: HomeAssistant, uart_esp: SimulatedEsp, freezer: FrozenDateTimeFactory
) -> None:
    """The diagnostics show the values with their frames."""
    entry = await _setup(hass, uart_esp)
    await _run(hass, freezer, FULL_POLL)
    uart = entry.runtime_data.uart
    assert uart is not None
    diagnostics = uart.diagnostics()
    assert diagnostics["values"]["tv"]["state"] == 29.7
    assert diagnostics["values"]["tv"]["frame"].startswith("40610E")
    assert diagnostics["protocol"] == "i"
    assert not diagnostics["detecting"]
    assert HPSU_0X20.hex().upper() == diagnostics["values"]["outdoor_temp"]["frame"]
