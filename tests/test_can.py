"""Tests for the CAN values against the simulated heat pump."""

from unittest.mock import patch

from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant.common import snapshot_platform
from syrupy.assertion import SnapshotAssertion

from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from helpers import (
    FULL_POLL,
    requested as _requested,
    run_bus as _run_bus,
    setup_can as _setup,
    state_of as _state,
    wait_for_state,
)
from sim.esp import SimulatedEsp
from sim.heat_pump import HeatPump

TV = "sensor.daikin_can_tv"
TV_REGISTER = (0xFA, 0xC0, 0xFC)
OPERATING_MODE = "select.daikin_can_operating_mode"


async def test_values_read(
    hass: HomeAssistant, can_esp: SimulatedEsp, freezer: FrozenDateTimeFactory
) -> None:
    """All values are read and shown with their platform."""
    await _setup(hass, can_esp)
    await _run_bus(hass, freezer, FULL_POLL)

    assert _state(hass, TV) == "30.0"
    assert _state(hass, "sensor.daikin_can_outside_temperature") == "-5.0"
    assert _state(hass, "sensor.daikin_can_water_pressure") == "1.8"
    assert _state(hass, "sensor.daikin_can_flow_rate") == "1200.0"
    assert _state(hass, "sensor.daikin_can_operating_state") == "heating"
    assert _state(hass, "sensor.daikin_can_smart_grid_state") == "sgn"
    error = hass.states.get("sensor.daikin_can_error_code")
    assert error is not None
    assert error.state == "no_error"
    assert error.attributes["code"] == 0
    assert _state(hass, "sensor.daikin_can_total_electrical_energy") == "3000.0"
    assert _state(hass, OPERATING_MODE) == "heating"
    assert _state(hass, "select.daikin_can_antifreeze_temperature") == "off"
    assert _state(hass, "select.daikin_can_heating_limit_day") == "20"
    assert _state(hass, "select.daikin_can_heating_limit_night") == "off"
    assert _state(hass, "select.daikin_can_electric_heater") == "6"
    assert _state(hass, "number.daikin_can_room_setpoint_1") == "21.5"
    assert _state(hass, "number.daikin_can_heating_curve") == "0.55"
    assert _state(hass, "number.daikin_can_hot_water_power") == "3.0"
    assert _state(hass, "number.daikin_can_cooling_setpoint_correction") == "-0.5"
    assert _state(hass, "switch.daikin_can_1x_hot_water") == "off"
    assert _state(hass, "switch.daikin_can_heating_support") == "on"
    assert _state(hass, "binary_sensor.daikin_can_compressor") == "on"
    assert (
        _state(hass, "binary_sensor.daikin_can_external_outside_temperature_sensor")
        == "on"
    )
    assert _state(hass, "sensor.daikin_can_temperature_spread") == "5.0"
    assert _state(hass, "sensor.daikin_can_tvbh_tr_delta") == "5.0"
    assert _state(hass, "sensor.daikin_can_tv_tvbh_delta") == "0.0"
    assert _state(hass, "sensor.daikin_can_flow_setpoint_tv_delta") == "0.0"
    assert _state(hass, "sensor.daikin_can_tv_max") == "30.0"
    # (30 - 25) K * 4.19 kJ/(kg K) * 1200 L/h / 3600 s/h
    assert _state(hass, "sensor.daikin_can_thermal_power") == "6.98"


@pytest.mark.freeze_time("2026-11-27 12:00:00+00:00")
@pytest.mark.usefixtures("entity_registry_enabled_by_default")
@pytest.mark.parametrize(
    "platform",
    [
        Platform.BINARY_SENSOR,
        Platform.BUTTON,
        Platform.NUMBER,
        Platform.SELECT,
        Platform.SENSOR,
        Platform.SWITCH,
    ],
)
async def test_entities(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    can_esp: SimulatedEsp,
    freezer: FrozenDateTimeFactory,
    snapshot: SnapshotAssertion,
    platform: Platform,
) -> None:
    """All CAN entities with their states."""
    with (
        patch("custom_components.daikin_heat_pump_control.PLATFORMS", [platform]),
        patch("custom_components.daikin_heat_pump_control.sensor.BRIDGE_SENSORS", ()),
    ):
        entry = await _setup(hass, can_esp)
    await _run_bus(hass, freezer, FULL_POLL + 5)
    await snapshot_platform(hass, entity_registry, snapshot, entry.entry_id)


async def test_disabled_values_not_polled(
    hass: HomeAssistant, can_esp: SimulatedEsp, freezer: FrozenDateTimeFactory
) -> None:
    """Values of disabled entities are not read from the bus."""
    entry = await _setup(hass, can_esp)
    await _run_bus(hass, freezer, FULL_POLL)
    assert _requested(can_esp, (0xFA, 0x00, 0x11)) == 0  # room temperature
    assert _requested(can_esp, (0xFA, 0x01, 0x27)) == 0  # system time seconds
    assert entry.runtime_data.can is not None
    assert "t_room" not in entry.runtime_data.can.scheduler.keys


async def test_enabling_an_entity_polls_its_values(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    can_esp: SimulatedEsp,
    freezer: FrozenDateTimeFactory,
) -> None:
    """An entity enabled by the user is polled after the reload."""
    await hass.config.async_set_time_zone("Europe/Berlin")
    entry = await _setup(hass, can_esp)
    for entity_id in (
        "sensor.daikin_can_system_time",
        "sensor.daikin_can_room_temperature",
    ):
        entity_registry.async_update_entity(entity_id, disabled_by=None)
    # Home Assistant reloads the entry 30 s after an entity was enabled.
    await _run_bus(hass, freezer, 31)
    assert "system_time_second" in entry.runtime_data.can.scheduler.keys
    await _run_bus(hass, freezer, FULL_POLL + 5)
    assert _state(hass, "sensor.daikin_can_system_time") == "2026-11-27T11:30:45+00:00"
    assert _state(hass, "sensor.daikin_can_room_temperature") == "21.5"


async def test_panel_change_is_heard(
    hass: HomeAssistant,
    can_esp: SimulatedEsp,
    heat_pump: HeatPump,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A setting changed on the RoCon panel arrives without a request."""
    await _setup(hass, can_esp)
    await _run_bus(hass, freezer, FULL_POLL)
    assert can_esp.can is not None
    requests = _requested(can_esp, (0xFA, 0x01, 0x12))
    can_esp.can.inject(heat_pump.panel_write((0xFA, 0x01, 0x12), b"\x05\x00"))
    await _run_bus(hass, freezer, 0.4)
    assert _state(hass, OPERATING_MODE) == "summer"
    assert _requested(can_esp, (0xFA, 0x01, 0x12)) == requests


async def test_unanswered_register_does_not_block(
    hass: HomeAssistant,
    can_esp: SimulatedEsp,
    heat_pump: HeatPump,
    freezer: FrozenDateTimeFactory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A register without answer is asked again after its interval only."""
    silent = (0x300, (0xFA, 0x0A, 0x0C))
    heat_pump.can_silent.add(silent)
    entry = await _setup(hass, can_esp)
    await _run_bus(hass, freezer, FULL_POLL + 3)
    assert _state(hass, "sensor.daikin_can_t_outside") == STATE_UNKNOWN
    assert _state(hass, "number.daikin_can_cooling_setpoint_correction") == "-0.5"
    assert caplog.text.count("No answer from the heat pump for t_ext") == 1
    assert _requested(can_esp, (0xFA, 0x0A, 0x0C)) == 1

    await _run_bus(hass, freezer, 30)
    assert _requested(can_esp, (0xFA, 0x0A, 0x0C)) == 2
    assert caplog.text.count("No answer from the heat pump for t_ext") == 1

    heat_pump.can_silent.discard(silent)
    await _run_bus(hass, freezer, 32)
    assert _state(hass, "sensor.daikin_can_t_outside") == "-5.0"
    assert "CAN value t_ext answers again" in caplog.text
    assert entry.runtime_data.can is not None
    lost = entry.runtime_data.can.scheduler.diagnostics()["values"]["t_ext"]["lost"]
    assert lost == 2


async def test_implausible_and_missing_values(
    hass: HomeAssistant,
    can_esp: SimulatedEsp,
    heat_pump: HeatPump,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Out-of-range values are dropped, the no-value marker means unknown."""
    heat_pump.set_can(0x180, (0xFA, 0xC2, 0xFA), b"\x80\x00")
    heat_pump.set_can(0x180, (0xFA, 0x13, 0x88), b"\x27\x0f")
    await _setup(hass, can_esp)
    await _run_bus(hass, freezer, FULL_POLL)
    assert _state(hass, "sensor.daikin_can_total_electrical_energy") == STATE_UNKNOWN
    error = hass.states.get("sensor.daikin_can_error_code")
    assert error is not None
    assert error.state == "unknown"
    assert error.attributes["code"] == 9999

    heat_pump.set_can(0x180, TV_REGISTER, b"\x00\x00")
    await _run_bus(hass, freezer, 32)
    assert _requested(can_esp, TV_REGISTER) > 1
    assert _state(hass, TV) == "30.0"


async def test_tv_max(
    hass: HomeAssistant,
    can_esp: SimulatedEsp,
    heat_pump: HeatPump,
    freezer: FrozenDateTimeFactory,
) -> None:
    """TV is read every 2 s; TV and its window maximum are shown in the interval."""
    # Settings and counters rarely, so that the bus has room for TV.
    await _setup(
        hass, can_esp, options={"interval_setting": 300, "interval_counter": 300}
    )
    # After the first full poll most values are due again at about 30-40 s.
    await _run_bus(hass, freezer, FULL_POLL + 15)
    assert _state(hass, TV) == "30.0"
    requests = _requested(can_esp, TV_REGISTER)
    heat_pump.set_can(0x180, TV_REGISTER, b"\x01\x5e")  # 35.0 °C
    await _run_bus(hass, freezer, 4)
    heat_pump.set_can(0x180, TV_REGISTER, b"\x01\x36")  # 31.0 °C
    await _run_bus(hass, freezer, 4)
    assert _state(hass, TV) == "30.0"
    assert _requested(can_esp, TV_REGISTER) - requests >= 3
    # The next publication is due 30 s after the previous one.
    await _run_bus(hass, freezer, 26)
    assert _state(hass, TV) == "31.0"
    assert _state(hass, "sensor.daikin_can_tv_max") == "35.0"


async def test_polling_intervals_from_options(
    hass: HomeAssistant, can_esp: SimulatedEsp
) -> None:
    """Group intervals win over the defaults of single values."""
    entry = await _setup(
        hass,
        can_esp,
        options={"scan_interval": 45, "interval_measurement": 60},
    )
    scheduler = entry.runtime_data.can.scheduler
    assert scheduler.interval_ms("water_pressure") == 60000
    assert scheduler.interval_ms("flow_rate") == 60000
    assert scheduler.interval_ms("tv") == 2000
    assert scheduler.interval_ms("operating_mode") == 5000
    assert scheduler.interval_ms("qch") == 45000


async def test_connection_loss_resets_values(
    hass: HomeAssistant, can_esp: SimulatedEsp, freezer: FrozenDateTimeFactory
) -> None:
    """Values are unavailable without connection and read again afterwards."""
    await _setup(hass, can_esp)
    await _run_bus(hass, freezer, FULL_POLL)
    await can_esp.drop_connections()
    await wait_for_state(hass, TV, STATE_UNAVAILABLE)
    await _run_bus(hass, freezer, 1)
    assert _state(hass, OPERATING_MODE) in (STATE_UNKNOWN, "heating")
    await _run_bus(hass, freezer, FULL_POLL)
    assert _state(hass, TV) == "30.0"
    assert _state(hass, OPERATING_MODE) == "heating"
