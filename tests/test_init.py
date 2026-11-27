"""Tests for setup, unload and the connection to the bridge nodes."""

from datetime import timedelta

from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant.common import async_fire_time_changed

from custom_components.daikin_heat_pump_control.bridge.protocol import CanFrame
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, issue_registry as ir

from helpers import (
    DOMAIN,
    MAC_BOTH,
    MAC_CAN,
    daikin_entry,
    esphome_entry,
    wait_for_state,
)
from sim.esp import FIRMWARE_BRIDGE, FIRMWARE_LEGACY_CAN, SimulatedEsp, make_noise_psk


async def _tick(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, seconds: float
) -> None:
    freezer.tick(timedelta(seconds=seconds))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


async def test_setup_and_unload(
    hass: HomeAssistant, can_esp: SimulatedEsp, uart_esp: SimulatedEsp
) -> None:
    """Both nodes connect, devices are created, unload disconnects."""
    entry = daikin_entry(hass, can=can_esp, uart=uart_esp)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    assert can_esp.connection_count == 1
    assert uart_esp.connection_count == 1

    registry = dr.async_get(hass)
    bridge = registry.async_get_device_by_identifier(
        (DOMAIN, f"bridge_{MAC_CAN}"), entry.entry_id
    )
    assert bridge is not None
    assert bridge.name == "Daikin Bridge daikin-can"
    assert bridge.sw_version == "1.0.0"
    can_device = registry.async_get_device_by_identifier(
        (DOMAIN, f"{entry.entry_id}_can"), entry.entry_id
    )
    assert can_device is not None
    assert can_device.name == "Daikin CAN"
    assert can_device.via_device_id == bridge.id
    uart_device = registry.async_get_device_by_identifier(
        (DOMAIN, f"{entry.entry_id}_uart"), entry.entry_id
    )
    assert uart_device is not None
    assert uart_device.name == "Daikin UART"

    assert (
        hass.states.get("binary_sensor.daikin_bridge_daikin_can_connection").state
        == STATE_ON
    )
    assert (
        hass.states.get("sensor.daikin_bridge_daikin_can_wi_fi_signal").state == "-61"
    )
    assert (
        hass.states.get("sensor.daikin_bridge_daikin_can_can_bus_state").state
        == "error_active"
    )
    assert (
        hass.states.get("sensor.daikin_bridge_daikin_uart_uart_buffer_overflows").state
        == "0"
    )
    assert hass.states.get("sensor.daikin_bridge_daikin_uart_can_bus_state") is None

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED
    assert can_esp.connection_count == 0
    assert uart_esp.connection_count == 0


async def test_node_with_both_buses(
    hass: HomeAssistant, both_esp: SimulatedEsp
) -> None:
    """One node serves both buses: one bridge device with both bus devices."""
    entry = daikin_entry(hass, can=both_esp, uart=both_esp)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert both_esp.connection_count == 1
    registry = dr.async_get(hass)
    bridge = registry.async_get_device_by_identifier(
        (DOMAIN, f"bridge_{MAC_BOTH}"), entry.entry_id
    )
    assert bridge is not None
    assert bridge.model == "CAN + UART bridge"
    devices = dr.async_entries_for_config_entry(registry, entry.entry_id)
    assert {d.name for d in devices} == {
        "Daikin Bridge daikin-both",
        "Daikin CAN",
        "Daikin UART",
    }
    assert all(d.via_device_id == bridge.id for d in devices if d.id != bridge.id)


async def test_not_ready_when_unreachable(
    hass: HomeAssistant, can_esp: SimulatedEsp
) -> None:
    """An unreachable node defers the setup."""
    entry = daikin_entry(hass, can=can_esp)
    await can_esp.stop()
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_auth_failed_starts_reauth(
    hass: HomeAssistant, can_esp: SimulatedEsp
) -> None:
    """A rejected key starts the reauth flow."""
    entry = daikin_entry(hass, can=can_esp)
    can_esp.noise_psk = make_noise_psk(42)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert [flow["context"]["source"] for flow in flows] == ["reauth"]


async def test_key_from_esphome_entry(
    hass: HomeAssistant, can_esp: SimulatedEsp
) -> None:
    """Host and key of the ESPHome entry win over the stored ones."""
    entry = daikin_entry(hass, can=can_esp)
    can_esp.noise_psk = make_noise_psk(42)
    esphome_entry(hass, can_esp)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    assert entry.data["nodes"][MAC_CAN]["noise_psk"] == make_noise_psk(42)


async def test_mdns_name_before_stored_host(
    hass: HomeAssistant, can_esp: SimulatedEsp, mdns: dict[str, str]
) -> None:
    """Without ESPHome entry the `.local` name is tried before the stored IP."""
    entry = daikin_entry(hass, can=can_esp)
    hass.config_entries.async_update_entry(
        entry,
        data={
            **entry.data,
            "nodes": {MAC_CAN: {**entry.data["nodes"][MAC_CAN], "host": "127.0.0.2"}},
        },
    )
    mdns["daikin-can"] = "127.0.0.1"
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.data["nodes"][MAC_CAN]["host"] == "127.0.0.1"
    diag = entry.runtime_data.nodes[MAC_CAN].connected_target
    assert diag is not None
    assert diag.source == "mdns"


async def test_reconnect_after_connection_loss(
    hass: HomeAssistant,
    can_esp: SimulatedEsp,
    freezer: FrozenDateTimeFactory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Entities become unavailable and recover after a reconnect."""
    entry = daikin_entry(hass, can=can_esp)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    connection = "binary_sensor.daikin_bridge_daikin_can_connection"
    signal = "sensor.daikin_bridge_daikin_can_wi_fi_signal"

    port = can_esp.port
    await can_esp.stop()
    await wait_for_state(hass, connection, STATE_OFF)
    assert hass.states.get(signal).state == STATE_UNAVAILABLE
    assert caplog.text.count("Lost connection to bridge daikin-can") == 1

    # Unreachable: retried with backoff, logged once
    await _tick(hass, freezer, 1)
    await _tick(hass, freezer, 2)
    warnings = [
        r.getMessage()
        for r in caplog.records
        if r.levelname == "WARNING" and r.name.startswith("custom_components")
    ]
    assert warnings == ["Lost connection to bridge daikin-can"]

    await can_esp.start(port)
    await _tick(hass, freezer, 4)
    assert hass.states.get(connection).state == STATE_ON
    assert hass.states.get(signal).state == "-61"
    assert "Bridge daikin-can is available again" in caplog.text


@pytest.mark.usefixtures("no_can_polling")
async def test_exchange_cycle(
    hass: HomeAssistant, can_esp: SimulatedEsp, freezer: FrozenDateTimeFactory
) -> None:
    """Queued CAN frames are sent and the answers reach the listeners."""
    entry = daikin_entry(hass, can=can_esp)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    channel = entry.runtime_data.channels["can"]
    results = []
    channel.async_add_listener(results.append)

    channel.async_send([CanFrame(can_id=0x680, data=bytes.fromhex("3100FAC0FC0000"))])
    await hass.async_block_till_done()
    assert results[-1].sent[0].frame.encode() == "680#3100FAC0FC0000"

    await _tick(hass, freezer, 0.2)
    received = [f.frame for r in results for f in r.received]
    assert CanFrame(can_id=0x180, data=bytes.fromhex("D200FAC0FC012C")) in received
    assert channel.exchanges >= 2
    assert len(channel.history) >= 2


async def test_info_refresh(
    hass: HomeAssistant, can_esp: SimulatedEsp, freezer: FrozenDateTimeFactory
) -> None:
    """Diagnostic values are read every 60 s."""
    entry = daikin_entry(hass, can=can_esp)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    can_esp.info_overrides["wifi"] = {"rssi": -70, "ssid": "home", "ip": "192.168.0.50"}
    can_esp.bridge_version = "1.1.0"
    await _tick(hass, freezer, 60)
    assert (
        hass.states.get("sensor.daikin_bridge_daikin_can_wi_fi_signal").state == "-70"
    )
    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, f"bridge_{MAC_CAN}"), entry.entry_id
    )
    assert device is not None
    assert device.sw_version == "1.1.0"


async def test_legacy_firmware_and_switch_back(
    hass: HomeAssistant, can_esp: SimulatedEsp, freezer: FrozenDateTimeFactory
) -> None:
    """A node with the previous firmware raises a repair issue until it runs the bridge."""
    can_esp.set_firmware(FIRMWARE_LEGACY_CAN)
    entry = daikin_entry(hass, can=can_esp)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    issue_id = f"no_bridge_firmware_{MAC_CAN.replace(':', '')}"
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is not None
    assert (
        hass.states.get("sensor.daikin_bridge_daikin_can_wi_fi_signal").state
        == STATE_UNAVAILABLE
    )
    assert (
        hass.states.get("binary_sensor.daikin_bridge_daikin_can_connection").state
        == STATE_ON
    )
    channel = entry.runtime_data.channels["can"]
    assert not channel.available

    # Flashing the bridge firmware reboots the node.
    can_esp.set_firmware(FIRMWARE_BRIDGE)
    await can_esp.drop_connections()
    await wait_for_state(
        hass, "binary_sensor.daikin_bridge_daikin_can_connection", STATE_OFF
    )
    await _tick(hass, freezer, 1)
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None
    assert channel.available
    assert (
        hass.states.get("sensor.daikin_bridge_daikin_can_wi_fi_signal").state == "-61"
    )


async def test_stale_devices_removed(
    hass: HomeAssistant, can_esp: SimulatedEsp, both_esp: SimulatedEsp
) -> None:
    """Devices of nodes no longer assigned are removed on reload."""
    entry = daikin_entry(hass, can=can_esp)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    registry = dr.async_get(hass)
    old = registry.async_get_device_by_identifier(
        (DOMAIN, f"bridge_{MAC_CAN}"), entry.entry_id
    )
    assert old is not None

    hass.config_entries.async_update_entry(
        entry,
        data={
            "nodes": {
                both_esp.mac: {
                    "host": both_esp.host,
                    "port": both_esp.port,
                    "noise_psk": both_esp.noise_psk,
                    "name": both_esp.name,
                }
            },
            "can_node": both_esp.mac,
            "uart_node": None,
        },
    )
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert (
        registry.async_get_device_by_identifier(
            (DOMAIN, f"bridge_{MAC_CAN}"), entry.entry_id
        )
        is None
    )
    assert registry.async_get_device_by_identifier(
        (DOMAIN, f"bridge_{MAC_BOTH}"), entry.entry_id
    )


async def test_remove_config_entry_device(
    hass: HomeAssistant, can_esp: SimulatedEsp
) -> None:
    """Only devices that are no longer used can be removed by the user."""
    entry = daikin_entry(hass, can=can_esp)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    registry = dr.async_get(hass)
    current = registry.async_get_device_by_identifier(
        (DOMAIN, f"bridge_{MAC_CAN}"), entry.entry_id
    )
    stale = registry.async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={(DOMAIN, "bridge_old")}
    )
    from custom_components.daikin_heat_pump_control import (  # noqa: PLC0415
        async_remove_config_entry_device,
    )

    assert not await async_remove_config_entry_device(hass, entry, current)
    assert await async_remove_config_entry_device(hass, entry, stale)
