"""Tests for several Home Assistant instances at one bridge (master)."""

from datetime import timedelta
from typing import Any

from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant.common import async_fire_time_changed
from pytest_homeassistant.typing import WebSocketGenerator

from custom_components.daikin_heat_pump_control.can.protocol import read_frame
from custom_components.daikin_heat_pump_control.can.table import CAN_VALUES_BY_KEY
from homeassistant.components.number import (
    ATTR_VALUE,
    DOMAIN as NUMBER_DOMAIN,
    SERVICE_SET_VALUE,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import issue_registry as ir

from helpers import DOMAIN, MAC_CAN, call_with_bus, daikin_entry, state_of
from sim.esp import FIRMWARE_BRIDGE_V1, SimulatedEsp
from sim.heat_pump import HeatPump, uart_checksum

OTHER = "other-instance"
TV = "sensor.daikin_can_tv"
UART_TV = "sensor.daikin_uart_tv"
ROOM_SETPOINT_1 = "number.daikin_can_room_setpoint_1"
TV_READ = read_frame(CAN_VALUES_BY_KEY["tv"].command).encode()


class OtherInstance:
    """A second Home Assistant instance at the same bridge, in the simulator."""

    def __init__(self, esp: SimulatedEsp) -> None:
        """Initialize."""
        self.esp = esp
        self.alive = True
        self.can_frames: list[str] = []
        self.uart_data = ""
        self.results: list[dict[str, Any]] = []

    def claim(self) -> dict[str, Any]:
        """Become the master."""
        return self.esp.claim(OTHER)

    def exchange(self) -> None:
        """Call the bridge as the instance would every 200 ms."""
        if not self.alive:
            return
        if self.esp.can is not None:
            frames, self.can_frames = self.can_frames, []
            self.results.append(self.esp.can_exchange(OTHER, frames))
        if self.esp.uart is not None:
            data, self.uart_data = self.uart_data, ""
            self.results.append(self.esp.uart_exchange(OTHER, data))


async def _run(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    other: OtherInstance,
    seconds: float,
) -> None:
    for _ in range(round(seconds / 0.2)):
        freezer.tick(timedelta(seconds=0.2))
        other.exchange()
        async_fire_time_changed(hass)
        await hass.async_block_till_done()


async def _setup(hass: HomeAssistant, **kwargs: Any) -> Any:
    entry = daikin_entry(hass, **kwargs)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _sent_by_ha(esp: SimulatedEsp, before: int) -> int:
    assert esp.can is not None
    return len(esp.can.sent) - before


async def test_listen_take_over_and_claim(
    hass: HomeAssistant,
    can_esp: SimulatedEsp,
    freezer: FrozenDateTimeFactory,
    hass_ws_client: WebSocketGenerator,
) -> None:
    """Another master polls, this instance shows its answers and takes over."""
    other = OtherInstance(can_esp)
    assert other.claim()["master"]
    entry = await _setup(hass, can=can_esp)
    node = entry.runtime_data.nodes[MAC_CAN]
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": f"{DOMAIN}/master/subscribe"})
    assert (await client.receive_json())["success"]
    # Before the first exchange the bridge has not reported anything yet.
    assert (await client.receive_json())["event"] == {"master": False, "clients": 0}

    await _run(hass, freezer, other, 1)
    assert not node.master
    assert node.clients == 2
    assert (await client.receive_json())["event"] == {"master": False, "clients": 2}
    assert can_esp.can is not None
    assert can_esp.can.sent == []

    # The answer to a request of the other instance reaches this one too.
    other.can_frames.append(TV_READ)
    await _run(hass, freezer, other, 1)
    assert len(can_esp.can.sent) == 1
    assert state_of(hass, TV) == "30.0"
    assert other.results[-1]["master"]

    with pytest.raises(HomeAssistantError) as err:
        await hass.services.async_call(
            NUMBER_DOMAIN,
            SERVICE_SET_VALUE,
            {"entity_id": ROOM_SETPOINT_1, ATTR_VALUE: 22},
            blocking=True,
        )
    assert err.value.translation_key == "not_master"

    # Without calls of the other instance the bridge makes this one the master.
    other.alive = False
    await _run(hass, freezer, other, 4)
    assert node.master
    assert (await client.receive_json())["event"] == {"master": True, "clients": 1}
    before = len(can_esp.can.sent)
    await _run(hass, freezer, other, 2)
    assert _sent_by_ha(can_esp, before) > 0

    # The other instance comes back and takes the bridge; this one claims it back.
    other.alive = True
    other.claim()
    await _run(hass, freezer, other, 0.4)
    assert not node.master
    ws = await hass_ws_client(hass)
    await ws.send_json_auto_id({"type": f"{DOMAIN}/master/claim"})
    response = await ws.receive_json()
    assert response["success"]
    assert response["result"] == {"master": True, "clients": 2}
    assert node.master
    assert can_esp.clients.master == node.client_id
    assert entry.runtime_data.can is not None
    assert entry.runtime_data.can.diagnostics()["master"]


async def test_write_dropped_when_master_lost(
    hass: HomeAssistant, can_esp: SimulatedEsp, freezer: FrozenDateTimeFactory
) -> None:
    """A write waiting while another instance takes over is not sent."""
    entry = await _setup(hass, can=can_esp)
    other = OtherInstance(can_esp)
    other.alive = False
    await _run(hass, freezer, other, 30)
    assert entry.runtime_data.nodes[MAC_CAN].master
    call = hass.services.async_call(
        NUMBER_DOMAIN,
        SERVICE_SET_VALUE,
        {"entity_id": ROOM_SETPOINT_1, ATTR_VALUE: 22},
        blocking=True,
    )
    other.claim()
    with pytest.raises(HomeAssistantError) as err:
        await call_with_bus(hass, freezer, call)
    assert err.value.translation_key in ("write_not_sent", "not_master")


async def test_preferred_master(
    hass: HomeAssistant, can_esp: SimulatedEsp, freezer: FrozenDateTimeFactory
) -> None:
    """With the option the instance becomes the master after connecting."""
    other = OtherInstance(can_esp)
    other.claim()
    entry = await _setup(hass, can=can_esp, options={"preferred_master": True})
    node = entry.runtime_data.nodes[MAC_CAN]
    assert node.master
    assert can_esp.clients.claims == [OTHER, node.client_id]
    await _run(hass, freezer, other, 1)
    assert node.master
    assert not other.results[-1]["master"]


async def test_preferred_master_fails(
    hass: HomeAssistant, can_esp: SimulatedEsp, caplog: pytest.LogCaptureFixture
) -> None:
    """A failing claim is logged; the instance keeps listening."""
    can_esp.fail_actions.add("daikin_bridge_claim")
    await _setup(hass, can=can_esp, options={"preferred_master": True})
    assert can_esp.clients.claims == []
    assert "could not become the master" in caplog.text


async def test_claim_fails(
    hass: HomeAssistant,
    can_esp: SimulatedEsp,
    hass_ws_client: WebSocketGenerator,
) -> None:
    """A failing claim is reported to the panel."""
    await _setup(hass, can=can_esp)
    can_esp.fail_actions.add("daikin_bridge_claim")
    ws = await hass_ws_client(hass)
    await ws.send_json_auto_id({"type": f"{DOMAIN}/master/claim"})
    response = await ws.receive_json()
    assert not response["success"]
    assert response["error"]["code"] == "claim_failed"


async def test_claim_invalid_answer(hass: HomeAssistant, can_esp: SimulatedEsp) -> None:
    """An invalid claim answer is an action error."""
    entry = await _setup(hass, can=can_esp)
    node = entry.runtime_data.nodes[MAC_CAN]
    action = can_esp.actions["daikin_bridge_claim"]
    action.handler = lambda args: {"error": "too_many_clients"}
    with pytest.raises(Exception, match="too_many_clients"):
        await node.async_claim()
    await node.async_stop()
    with pytest.raises(Exception, match="not connected"):
        await node.async_claim()


async def test_master_websocket_not_loaded(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator, can_esp: SimulatedEsp
) -> None:
    """The master commands need a loaded entry."""
    entry = await _setup(hass, can=can_esp)
    assert await hass.config_entries.async_unload(entry.entry_id)
    ws = await hass_ws_client(hass)
    for command in ("master/subscribe", "master/claim"):
        await ws.send_json_auto_id({"type": f"{DOMAIN}/{command}"})
        response = await ws.receive_json()
        assert response["error"]["code"] == "not_loaded"


async def test_too_many_clients(
    hass: HomeAssistant,
    can_esp: SimulatedEsp,
    freezer: FrozenDateTimeFactory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A bridge with all clients taken refuses this instance; it is logged once."""
    others = [f"other-{index}" for index in range(4)]
    for other in others:
        can_esp.claim(other)
    entry = await _setup(hass, can=can_esp)
    channel = entry.runtime_data.channels["can"]
    idle = OtherInstance(can_esp)
    idle.alive = False
    for _ in range(5):
        freezer.tick(timedelta(seconds=0.2))
        for other in others:
            can_esp.can_exchange(other, [])
        async_fire_time_changed(hass)
        await hass.async_block_till_done()
    assert channel.errors >= 2
    warnings = [
        record
        for record in caplog.records
        if record.levelname == "WARNING"
        and record.name.startswith("custom_components")
        and "too_many_clients" in record.message
    ]
    assert len(warnings) == 1
    assert not entry.runtime_data.nodes[MAC_CAN].master
    # Once the others are gone the instance gets in.
    await _run(hass, freezer, idle, 4)
    assert entry.runtime_data.nodes[MAC_CAN].master


async def test_lose_master_while_refused(
    hass: HomeAssistant, can_esp: SimulatedEsp, freezer: FrozenDateTimeFactory
) -> None:
    """A master that the bridge forgot and refuses is no longer the master."""
    entry = await _setup(hass, can=can_esp)
    node = entry.runtime_data.nodes[MAC_CAN]
    other = OtherInstance(can_esp)
    other.alive = False
    await _run(hass, freezer, other, 0.4)
    assert node.master
    action = can_esp.actions["daikin_can_exchange"]
    action.handler = lambda args: {"error": "too_many_clients"}
    await _run(hass, freezer, other, 0.4)
    assert not node.master


async def test_outdated_bridge_firmware(
    hass: HomeAssistant, can_esp: SimulatedEsp, freezer: FrozenDateTimeFactory
) -> None:
    """A bridge firmware without clients raises a repair issue; the bus is off."""
    can_esp.set_firmware(FIRMWARE_BRIDGE_V1)
    entry = await _setup(hass, can=can_esp)
    issue_registry = ir.async_get(hass)
    issue = issue_registry.async_get_issue(
        DOMAIN, "bridge_firmware_outdated_aabbcc000001"
    )
    assert issue is not None
    assert issue.translation_placeholders is not None
    assert issue.translation_placeholders["version"] == "1.0.0"
    assert not entry.runtime_data.channels["can"].available
    assert can_esp.stats.actions.get("daikin_can_exchange") is None

    # After flashing the current firmware the issue goes away.
    can_esp.set_firmware("bridge")
    await can_esp.drop_connections()
    await _run(hass, freezer, OtherInstance(can_esp), 3)
    assert (
        issue_registry.async_get_issue(DOMAIN, "bridge_firmware_outdated_aabbcc000001")
        is None
    )
    assert entry.runtime_data.channels["can"].available


def _uart_request(register: int) -> str:
    request = bytes((0x03, 0x40, register))
    return (request + bytes((uart_checksum(request),))).hex().upper()


async def test_uart_listener(
    hass: HomeAssistant,
    uart_esp: SimulatedEsp,
    heat_pump: HeatPump,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A listening instance reads the UART answers to the requests of the master."""
    other = OtherInstance(uart_esp)
    other.claim()
    entry = await _setup(hass, uart=uart_esp)
    assert entry.runtime_data.uart is not None
    requests = len(heat_pump.uart_requests)
    for register in sorted(heat_pump.uart_registers):
        other.uart_data = _uart_request(register)
        await _run(hass, freezer, other, 0.6)
    assert len(heat_pump.uart_requests) - requests == len(heat_pump.uart_registers)
    assert state_of(hass, UART_TV) == "29.7"
    assert not entry.runtime_data.uart.diagnostics()["master"]

    # Taking over: the polling starts where the listening left off.
    registers = entry.runtime_data.uart.scheduler.registers.values()
    assert all(state.last_answer is not None for state in registers)
    other.alive = False
    await _run(hass, freezer, other, 4)
    assert entry.runtime_data.uart.master
    requests = len(heat_pump.uart_requests)
    await _run(hass, freezer, other, 2)
    assert len(heat_pump.uart_requests) > requests


async def test_uart_master_lost_during_request(
    hass: HomeAssistant,
    uart_esp: SimulatedEsp,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Losing the master drops the open request and the answer poll."""
    entry = await _setup(hass, uart=uart_esp)
    other = OtherInstance(uart_esp)
    other.alive = False
    await _run(hass, freezer, other, 0.2)
    coordinator = entry.runtime_data.uart
    assert coordinator is not None
    assert coordinator.scheduler.open is not None
    other.claim()
    await _run(hass, freezer, other, 0.4)
    assert not coordinator.master
    assert coordinator.scheduler.open is None
