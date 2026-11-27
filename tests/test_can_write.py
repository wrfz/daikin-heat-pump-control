"""Tests for writing, the logic and the raw CAN service against the simulator."""

from datetime import timedelta
from typing import Any

from freezegun.api import FrozenDateTimeFactory
import pytest

from homeassistant.components.button import DOMAIN as BUTTON_DOMAIN, SERVICE_PRESS
from homeassistant.components.number import (
    ATTR_VALUE,
    DOMAIN as NUMBER_DOMAIN,
    SERVICE_SET_VALUE,
)
from homeassistant.components.select import (
    ATTR_OPTION,
    DOMAIN as SELECT_DOMAIN,
    SERVICE_SELECT_OPTION,
)
from homeassistant.components.switch import DOMAIN as SWITCH_DOMAIN
from homeassistant.const import SERVICE_TURN_OFF, SERVICE_TURN_ON, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.util import dt as dt_util

from helpers import (
    DOMAIN,
    ENTRY_ID,
    FULL_POLL,
    call_with_bus,
    daikin_entry,
    requested,
    run_bus,
    setup_can,
    state_of,
    wait_for_state,
)
from sim.esp import SimulatedEsp
from sim.heat_pump import HeatPump

C = 0x180
ROOM_SETPOINT_1 = "number.daikin_can_room_setpoint_1"
HOT_WATER_SETPOINT_1 = "number.daikin_can_hot_water_setpoint_1"
OPERATING_MODE = "select.daikin_can_operating_mode"
ANTIFREEZE = "select.daikin_can_antifreeze_temperature"
OPTIMIZED_DEFROSTING = "switch.daikin_can_optimized_defrosting"
WRITES_TODAY = "sensor.daikin_can_writes_today"
ERROR_CODE = "sensor.daikin_can_error_code"

MODE_REGISTER = (0xFA, 0x01, 0x12)
STATE_REGISTER = (0xFA, 0xC0, 0xF6)
ANTIFREEZE_REGISTER = (0xFA, 0x0A, 0x00)
STORAGE_KEY = f"{DOMAIN}.{ENTRY_ID}"


def _call(hass: HomeAssistant, domain: str, service: str, **data: Any) -> Any:
    return hass.services.async_call(domain, service, data, blocking=True)


async def _ready(
    hass: HomeAssistant, esp: SimulatedEsp, freezer: FrozenDateTimeFactory, **kw: Any
) -> Any:
    entry = await setup_can(hass, esp, **kw)
    await run_bus(hass, freezer, FULL_POLL)
    return entry


@pytest.mark.parametrize(
    ("domain", "service", "entity_id", "data", "register", "stored", "state"),
    [
        (
            NUMBER_DOMAIN,
            SERVICE_SET_VALUE,
            ROOM_SETPOINT_1,
            {ATTR_VALUE: 22.3},
            (0x05,),
            b"\x00\xe1",
            "22.5",
        ),
        (
            NUMBER_DOMAIN,
            SERVICE_SET_VALUE,
            "number.daikin_can_heating_curve",
            {ATTR_VALUE: 0.62},
            (0xFA, 0x01, 0x0E),
            b"\x00\x3e",
            "0.62",
        ),
        (
            SELECT_DOMAIN,
            SERVICE_SELECT_OPTION,
            OPERATING_MODE,
            {ATTR_OPTION: "summer"},
            MODE_REGISTER,
            b"\x05\x00",
            "summer",
        ),
        (
            SELECT_DOMAIN,
            SERVICE_SELECT_OPTION,
            "select.daikin_can_electric_heater",
            {ATTR_OPTION: "9"},
            (0xFA, 0x0A, 0x20),
            b"\x0f\x00",
            "9",
        ),
        (
            SWITCH_DOMAIN,
            SERVICE_TURN_ON,
            "switch.daikin_can_1x_hot_water",
            {},
            (0xFA, 0x01, 0x44),
            b"\x00\x01",
            "on",
        ),
        (
            SWITCH_DOMAIN,
            SERVICE_TURN_OFF,
            "switch.daikin_can_heating_support",
            {},
            (0xFA, 0x06, 0x6C),
            b"\x00\x00",
            "off",
        ),
    ],
)
async def test_write_setting(
    hass: HomeAssistant,
    can_esp: SimulatedEsp,
    heat_pump: HeatPump,
    freezer: FrozenDateTimeFactory,
    domain: str,
    service: str,
    entity_id: str,
    data: dict[str, Any],
    register: tuple[int, ...],
    stored: bytes,
    state: str,
) -> None:
    """A setting is written, read back and counted."""
    await _ready(hass, can_esp, freezer)
    reads = requested(can_esp, register)
    await call_with_bus(
        hass, freezer, _call(hass, domain, service, entity_id=entity_id, **data)
    )
    assert heat_pump.can_registers[(C, register)] == stored
    assert state_of(hass, entity_id) == state
    assert requested(can_esp, register, kind=0) == 1
    assert requested(can_esp, register) == reads + 1
    writes = hass.states.get(WRITES_TODAY)
    assert writes is not None
    assert writes.state == "1"
    assert sum(v for k, v in writes.attributes.items() if isinstance(v, int)) == 1


async def test_unchanged_value_is_not_written(
    hass: HomeAssistant, can_esp: SimulatedEsp, freezer: FrozenDateTimeFactory
) -> None:
    """Writing the current value (after rounding) sends nothing."""
    await _ready(hass, can_esp, freezer)
    await call_with_bus(
        hass,
        freezer,
        _call(
            hass,
            NUMBER_DOMAIN,
            SERVICE_SET_VALUE,
            entity_id=ROOM_SETPOINT_1,
            value=21.6,
        ),
    )
    assert requested(can_esp, (0x05,), kind=0) == 0
    assert state_of(hass, WRITES_TODAY) == "0"


async def test_write_rejected(
    hass: HomeAssistant,
    can_esp: SimulatedEsp,
    heat_pump: HeatPump,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A value the heat pump does not take is reported with the value it keeps."""
    heat_pump.can_read_only.add((C, MODE_REGISTER))
    await _ready(hass, can_esp, freezer)
    with pytest.raises(HomeAssistantError) as err:
        await call_with_bus(
            hass,
            freezer,
            _call(
                hass,
                SELECT_DOMAIN,
                SERVICE_SELECT_OPTION,
                entity_id=OPERATING_MODE,
                option="summer",
            ),
        )
    assert err.value.translation_key == "write_rejected"
    assert err.value.translation_placeholders["actual"] == "heating"
    assert state_of(hass, OPERATING_MODE) == "heating"
    assert state_of(hass, WRITES_TODAY) == "1"


async def test_write_not_confirmed(
    hass: HomeAssistant,
    can_esp: SimulatedEsp,
    heat_pump: HeatPump,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A write without read-back fails after the timeout."""
    await _ready(hass, can_esp, freezer)
    heat_pump.can_silent.add((C, MODE_REGISTER))
    with pytest.raises(HomeAssistantError) as err:
        await call_with_bus(
            hass,
            freezer,
            _call(
                hass,
                SELECT_DOMAIN,
                SERVICE_SELECT_OPTION,
                entity_id=OPERATING_MODE,
                option="summer",
            ),
            seconds=5,
        )
    assert err.value.translation_key == "write_not_confirmed"
    assert heat_pump.can_registers[(C, MODE_REGISTER)] == b"\x05\x00"


async def test_read_only_setting(
    hass: HomeAssistant, can_esp: SimulatedEsp, freezer: FrozenDateTimeFactory
) -> None:
    """Settings without known write target stay read-only."""
    await _ready(hass, can_esp, freezer)
    with pytest.raises(HomeAssistantError) as err:
        await _call(
            hass,
            SWITCH_DOMAIN,
            SERVICE_TURN_ON,
            entity_id="switch.daikin_can_heating_curve_adaptation",
        )
    assert err.value.translation_key == "write_not_supported"


async def test_invalid_and_unavailable(
    hass: HomeAssistant, can_esp: SimulatedEsp, freezer: FrozenDateTimeFactory
) -> None:
    """Invalid values and writes without bus are refused."""
    entry = await _ready(hass, can_esp, freezer)
    coordinator = entry.runtime_data.can
    with pytest.raises(ServiceValidationError) as err:
        await coordinator.async_write("operating_mode", "party")
    assert err.value.translation_key == "invalid_value"
    await can_esp.drop_connections()
    await wait_for_state(hass, OPERATING_MODE, STATE_UNAVAILABLE)
    with pytest.raises(HomeAssistantError) as err:
        await coordinator.async_write("operating_mode", "summer")
    assert err.value.translation_key == "bus_unavailable"
    with pytest.raises(HomeAssistantError) as err:
        await coordinator.async_run_hot_water()
    assert err.value.translation_key == "bus_unavailable"


async def test_pending_write_dropped_on_connection_loss(
    hass: HomeAssistant,
    can_esp: SimulatedEsp,
    heat_pump: HeatPump,
    freezer: FrozenDateTimeFactory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A write that did not reach the bus fails when the connection is lost."""
    entry = await _ready(hass, can_esp, freezer)
    # Bus traffic now: the bridge holds the frame back for the quiet time.
    assert can_esp.can is not None
    can_esp.can.inject(heat_pump.panel_write((0xFA, 0x01, 0x76), b"\x00\x00"))
    task = hass.loop.create_task(
        entry.runtime_data.can.async_write("operating_mode", "summer")
    )
    await hass.async_block_till_done()
    await can_esp.drop_connections()
    with pytest.raises(HomeAssistantError) as err:
        await task
    assert err.value.translation_key == "write_not_sent"
    assert "Dropped 1 CAN write(s) because the bus is unavailable" in caplog.text


# ------------------------------------------------------------ writes today


async def test_writes_today_stored_and_reset_at_midnight(
    hass: HomeAssistant,
    can_esp: SimulatedEsp,
    freezer: FrozenDateTimeFactory,
    hass_storage: dict[str, Any],
) -> None:
    """The writes of the day survive a reload and start again at midnight."""
    now = dt_util.utcnow()
    hass_storage[STORAGE_KEY] = {
        "version": 1,
        "minor_version": 1,
        "key": STORAGE_KEY,
        "data": {
            "optimized_defrosting": False,
            "writes": [
                [now.isoformat(), "quiet"],
                [(now - timedelta(days=2)).isoformat(), "quiet"],
                ["invalid", "quiet"],
            ],
        },
    }
    entry = await _ready(hass, can_esp, freezer)
    writes = hass.states.get(WRITES_TODAY)
    assert writes is not None
    assert writes.state == "1"
    assert writes.attributes["quiet"] == 1
    await call_with_bus(
        hass,
        freezer,
        _call(
            hass,
            SELECT_DOMAIN,
            SERVICE_SELECT_OPTION,
            entity_id=OPERATING_MODE,
            option="summer",
        ),
    )
    assert state_of(hass, WRITES_TODAY) == "2"
    await run_bus(hass, freezer, 11)
    stored = hass_storage[STORAGE_KEY]["data"]["writes"]
    assert [key for _, key in stored] == ["quiet", "operating_mode"]

    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    await run_bus(hass, freezer, 1)
    assert state_of(hass, WRITES_TODAY) == "2"

    freezer.move_to(dt_util.start_of_local_day() + timedelta(days=1, seconds=1))
    await run_bus(hass, freezer, 1)
    assert state_of(hass, WRITES_TODAY) == "0"


async def test_storage_removed_with_entry(
    hass: HomeAssistant,
    can_esp: SimulatedEsp,
    freezer: FrozenDateTimeFactory,
    hass_storage: dict[str, Any],
) -> None:
    """Removing the entry removes its stored state."""
    entry = await _ready(hass, can_esp, freezer)
    await call_with_bus(
        hass,
        freezer,
        _call(
            hass,
            SWITCH_DOMAIN,
            SERVICE_TURN_ON,
            entity_id=OPTIMIZED_DEFROSTING,
        ),
        seconds=11,
    )
    assert STORAGE_KEY in hass_storage
    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert STORAGE_KEY not in hass_storage


# ---------------------------------------------------- optimized defrosting


async def test_defrost_optimization(
    hass: HomeAssistant,
    can_esp: SimulatedEsp,
    heat_pump: HeatPump,
    freezer: FrozenDateTimeFactory,
) -> None:
    """During defrosting the mode is summer, afterwards the previous mode."""
    await _ready(hass, can_esp, freezer, options={"interval_state": 2})
    assert state_of(hass, OPTIMIZED_DEFROSTING) == "off"
    await call_with_bus(
        hass,
        freezer,
        _call(hass, SWITCH_DOMAIN, SERVICE_TURN_ON, entity_id=OPTIMIZED_DEFROSTING),
    )
    assert state_of(hass, OPTIMIZED_DEFROSTING) == "on"
    # The antifreeze temperature is off already.
    assert requested(can_esp, ANTIFREEZE_REGISTER, kind=0) == 0

    heat_pump.set_can(C, STATE_REGISTER, b"\x00\x03")  # defrosting
    await run_bus(hass, freezer, 10)
    assert state_of(hass, "sensor.daikin_can_operating_state") == "defrosting"
    assert heat_pump.can_registers[(C, MODE_REGISTER)] == b"\x05\x00"
    assert state_of(hass, OPERATING_MODE) == "summer"

    heat_pump.set_can(C, STATE_REGISTER, b"\x00\x01")  # heating
    await run_bus(hass, freezer, 10)
    assert heat_pump.can_registers[(C, MODE_REGISTER)] == b"\x03\x00"
    assert state_of(hass, OPERATING_MODE) == "heating"
    writes = hass.states.get(WRITES_TODAY)
    assert writes is not None
    assert writes.attributes["operating_mode"] == 2

    # Turned off, defrosting leaves the mode alone.
    await call_with_bus(
        hass,
        freezer,
        _call(hass, SWITCH_DOMAIN, SERVICE_TURN_OFF, entity_id=OPTIMIZED_DEFROSTING),
    )
    heat_pump.set_can(C, STATE_REGISTER, b"\x00\x03")
    await run_bus(hass, freezer, 10)
    assert state_of(hass, OPERATING_MODE) == "heating"


async def test_defrost_write_failure_is_logged(
    hass: HomeAssistant,
    can_esp: SimulatedEsp,
    heat_pump: HeatPump,
    freezer: FrozenDateTimeFactory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A failed write of the optimization is logged."""
    await _ready(hass, can_esp, freezer, options={"interval_state": 2})
    await call_with_bus(
        hass,
        freezer,
        _call(hass, SWITCH_DOMAIN, SERVICE_TURN_ON, entity_id=OPTIMIZED_DEFROSTING),
    )
    heat_pump.can_read_only.add((C, MODE_REGISTER))
    heat_pump.set_can(C, STATE_REGISTER, b"\x00\x03")
    await run_bus(hass, freezer, 10)
    assert "Writing operating_mode = summer failed" in caplog.text


async def test_defrost_switch_sets_antifreeze_off(
    hass: HomeAssistant,
    can_esp: SimulatedEsp,
    heat_pump: HeatPump,
    freezer: FrozenDateTimeFactory,
    hass_storage: dict[str, Any],
) -> None:
    """Turning on sets the antifreeze off; another antifreeze value turns it off."""
    heat_pump.set_can(C, ANTIFREEZE_REGISTER, b"\xff\xd8")  # -4 °C
    await _ready(hass, can_esp, freezer)
    assert state_of(hass, ANTIFREEZE) == "minus_4"
    await call_with_bus(
        hass,
        freezer,
        _call(hass, SWITCH_DOMAIN, SERVICE_TURN_ON, entity_id=OPTIMIZED_DEFROSTING),
    )
    assert heat_pump.can_registers[(C, ANTIFREEZE_REGISTER)] == b"\xff\x60"
    assert state_of(hass, ANTIFREEZE) == "off"
    assert state_of(hass, OPTIMIZED_DEFROSTING) == "on"
    await run_bus(hass, freezer, 11)
    assert hass_storage[STORAGE_KEY]["data"]["optimized_defrosting"] is True

    assert can_esp.can is not None
    can_esp.can.inject(heat_pump.panel_write(ANTIFREEZE_REGISTER, b"\xff\xec"))
    await run_bus(hass, freezer, 0.4)
    assert state_of(hass, ANTIFREEZE) == "minus_2"
    assert state_of(hass, OPTIMIZED_DEFROSTING) == "off"


async def test_defrost_switch_restored(
    hass: HomeAssistant,
    can_esp: SimulatedEsp,
    freezer: FrozenDateTimeFactory,
    hass_storage: dict[str, Any],
) -> None:
    """The switch keeps its state over a restart."""
    hass_storage[STORAGE_KEY] = {
        "version": 1,
        "minor_version": 1,
        "key": STORAGE_KEY,
        "data": {"optimized_defrosting": True, "writes": []},
    }
    entry = await _ready(hass, can_esp, freezer)
    assert state_of(hass, OPTIMIZED_DEFROSTING) == "on"
    diagnostics = entry.runtime_data.can.diagnostics()
    assert diagnostics["storage"]["optimized_defrosting"] is True
    assert diagnostics["defrost_saved_mode"] == "standby"


# ---------------------------------------------------------- hot water run


async def test_hot_water_run(
    hass: HomeAssistant,
    can_esp: SimulatedEsp,
    heat_pump: HeatPump,
    freezer: FrozenDateTimeFactory,
) -> None:
    """The button sets 70 °C and, once confirmed, the previous setpoint."""
    await _ready(hass, can_esp, freezer)
    await call_with_bus(
        hass,
        freezer,
        _call(
            hass,
            BUTTON_DOMAIN,
            SERVICE_PRESS,
            entity_id="button.daikin_can_hot_water_run",
        ),
        seconds=4,
    )
    writes = [
        frame.data.hex().upper()
        for frame in heat_pump.can_writes
        if frame.data[2] == 0x13
    ]
    assert writes == ["30001302BC0000", "30001301F40000"]
    assert state_of(hass, HOT_WATER_SETPOINT_1) == "50.0"
    assert state_of(hass, WRITES_TODAY) == "2"


async def test_hot_water_run_unknown_setpoint(
    hass: HomeAssistant, can_esp: SimulatedEsp
) -> None:
    """Without a known setpoint the button refuses."""
    await setup_can(hass, can_esp)
    with pytest.raises(HomeAssistantError) as err:
        await _call(
            hass,
            BUTTON_DOMAIN,
            SERVICE_PRESS,
            entity_id="button.daikin_can_hot_water_run",
        )
    assert err.value.translation_key == "value_unknown"


async def test_hot_water_run_restores_after_failure(
    hass: HomeAssistant,
    can_esp: SimulatedEsp,
    heat_pump: HeatPump,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Without read-back of 70 °C the previous setpoint is written anyway."""
    await _ready(hass, can_esp, freezer)
    heat_pump.can_silent.add((C, (0x13,)))
    with pytest.raises(HomeAssistantError) as err:
        await call_with_bus(
            hass,
            freezer,
            _call(
                hass,
                BUTTON_DOMAIN,
                SERVICE_PRESS,
                entity_id="button.daikin_can_hot_water_run",
            ),
            seconds=10,
        )
    assert err.value.translation_key == "write_not_confirmed"
    assert heat_pump.can_registers[(C, (0x13,))] == b"\x01\xf4"
    assert len([f for f in heat_pump.can_writes if f.data[2] == 0x13]) == 2


async def test_hot_water_run_restore_failure_is_logged(
    hass: HomeAssistant,
    can_esp: SimulatedEsp,
    heat_pump: HeatPump,
    freezer: FrozenDateTimeFactory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A failed restore of the setpoint is logged and raised."""
    await _ready(hass, can_esp, freezer)
    original = heat_pump.on_can_write

    def _lock(target: int, register: tuple[int, ...], value: bytes) -> None:
        # After 70 °C the register no longer takes writes.
        heat_pump.can_read_only.add((C, (0x13,)))

    heat_pump.on_can_write = _lock
    with pytest.raises(HomeAssistantError) as err:
        await call_with_bus(
            hass,
            freezer,
            _call(
                hass,
                BUTTON_DOMAIN,
                SERVICE_PRESS,
                entity_id="button.daikin_can_hot_water_run",
            ),
            seconds=4,
        )
    heat_pump.on_can_write = original
    assert err.value.translation_key == "write_rejected"
    assert "setting the setpoint back to 50.0 °C failed" in caplog.text


# ------------------------------------------------------------- error code


async def test_error_code_finding(
    hass: HomeAssistant,
    can_esp: SimulatedEsp,
    heat_pump: HeatPump,
    freezer: FrozenDateTimeFactory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A cold tank in hot water mode without mixer opening is a missing flow."""
    heat_pump.set_can(C, STATE_REGISTER, b"\x00\x04")  # hot water
    heat_pump.set_can(C, (0xFA, 0x00, 0x0E), b"\x01\xc2")  # 45.0 °C
    await _ready(hass, can_esp, freezer, options={"interval_state": 10})
    error = hass.states.get(ERROR_CODE)
    assert error is not None
    assert error.attributes["finding"] is None
    await run_bus(hass, freezer, 8 * 60, step=1.0)
    error = hass.states.get(ERROR_CODE)
    assert error is not None
    assert error.state == "no_error"
    assert error.attributes["finding"] == "missing_flow"
    assert "Heat pump check found a fault: missing_flow" in caplog.text

    heat_pump.set_can(C, (0xFA, 0x00, 0x0E), b"\x01\xf4")  # 50.0 °C
    await run_bus(hass, freezer, 60)
    error = hass.states.get(ERROR_CODE)
    assert error is not None
    assert error.attributes["finding"] is None
    assert "no longer finds missing_flow" in caplog.text


# ------------------------------------------------------------ send_raw_can


def _raw(hass: HomeAssistant, **data: Any) -> Any:
    return hass.services.async_call(
        DOMAIN, "send_raw_can", data, blocking=True, return_response=True
    )


async def test_send_raw_read(
    hass: HomeAssistant, can_esp: SimulatedEsp, freezer: FrozenDateTimeFactory
) -> None:
    """A raw read returns the answer of the heat pump."""
    entry = await _ready(hass, can_esp, freezer)
    response = await call_with_bus(
        hass, freezer, _raw(hass, data="0x31 0x00 0xFA 0xC0 0xFC 0x00 0x00")
    )
    assert response == {
        "sent": "680#3100FAC0FC0000",
        "answer": {"can_id": "180", "data": "D200FAC0FC012C"},
    }
    response = await call_with_bus(
        hass,
        freezer,
        _raw(hass, data="31 00 FA 00 00 00 00", config_entry_id=entry.entry_id),
        seconds=4,
    )
    assert response == {"sent": "680#3100FA00000000", "answer": None}


async def test_send_raw_write(
    hass: HomeAssistant,
    can_esp: SimulatedEsp,
    heat_pump: HeatPump,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A raw write is sent and counted."""
    await _ready(hass, can_esp, freezer)
    response = await call_with_bus(hass, freezer, _raw(hass, data="3000FA01440001"))
    assert response == {"sent": "680#3000FA01440001", "answer": None}
    assert heat_pump.can_registers[(C, (0xFA, 0x01, 0x44))] == b"\x00\x01"
    writes = hass.states.get(WRITES_TODAY)
    assert writes is not None
    assert writes.attributes["raw"] == 1


async def test_send_raw_errors(
    hass: HomeAssistant,
    can_esp: SimulatedEsp,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Invalid frames and missing entries are reported."""
    entry = await _ready(hass, can_esp, freezer)
    with pytest.raises(ServiceValidationError) as err:
        await _raw(hass, data="31 0")
    assert err.value.translation_key == "invalid_raw_frame"
    with pytest.raises(ServiceValidationError) as err:
        await _raw(hass, data="31", config_entry_id="nope")
    assert err.value.translation_key == "entry_not_found"
    await can_esp.drop_connections()
    await wait_for_state(hass, OPERATING_MODE, STATE_UNAVAILABLE)
    with pytest.raises(HomeAssistantError) as err:
        await _raw(hass, data="31")
    assert err.value.translation_key == "bus_unavailable"
    assert await hass.config_entries.async_unload(entry.entry_id)
    with pytest.raises(ServiceValidationError) as err:
        await _raw(hass, data="31")
    assert err.value.translation_key == "entry_not_loaded"
    with pytest.raises(ServiceValidationError) as err:
        await _raw(hass, data="31", config_entry_id=entry.entry_id)
    assert err.value.translation_key == "entry_not_loaded"


async def test_send_raw_not_sent(
    hass: HomeAssistant,
    can_esp: SimulatedEsp,
    heat_pump: HeatPump,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A raw frame lost with the connection is reported."""
    entry = await _ready(hass, can_esp, freezer)
    # Bus traffic now: the bridge holds the frame back for the quiet time.
    assert can_esp.can is not None
    can_esp.can.inject(heat_pump.panel_write((0xFA, 0x01, 0x76), b"\x00\x00"))
    task = hass.loop.create_task(
        entry.runtime_data.can.async_send_raw(bytes.fromhex("3000FA01440001"))
    )
    await hass.async_block_till_done()
    await can_esp.drop_connections()
    with pytest.raises(HomeAssistantError) as err:
        await task
    assert err.value.translation_key == "raw_not_sent"


async def test_send_raw_without_can(
    hass: HomeAssistant, uart_esp: SimulatedEsp
) -> None:
    """Without CAN bus the service is refused."""
    entry = daikin_entry(hass, uart=uart_esp)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    with pytest.raises(ServiceValidationError) as err:
        await _raw(hass, data="31")
    assert err.value.translation_key == "no_can_bus"
