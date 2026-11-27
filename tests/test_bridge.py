"""Tests for the bridge connection: failures, timeouts and address resolution."""

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant.common import async_fire_time_changed

from custom_components.daikin_heat_pump_control.bridge import resolve
from custom_components.daikin_heat_pump_control.bridge.protocol import CanFrame
from custom_components.daikin_heat_pump_control.bridge.resolve import (
    async_resolve_node_name as real_resolve_node_name,
)
from custom_components.daikin_heat_pump_control.sensor import BRIDGE_SENSORS
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant

from helpers import DOMAIN, MAC_CAN, daikin_entry, esphome_entry, wait_for_state
from sim.esp import SimulatedEsp, make_noise_psk
from sim.heat_pump import SimCanFrame

pytestmark = pytest.mark.usefixtures("no_can_polling")

CONNECTION = "binary_sensor.daikin_bridge_daikin_can_connection"
FRAME = CanFrame(can_id=0x680, data=bytes.fromhex("3100FAC0FC0000"))


async def _tick(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, seconds: float
) -> None:
    freezer.tick(timedelta(seconds=seconds))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


async def _setup(hass: HomeAssistant, **nodes: SimulatedEsp):  # type: ignore[no-untyped-def]
    entry = daikin_entry(hass, **nodes)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_failing_exchange_is_counted(
    hass: HomeAssistant,
    can_esp: SimulatedEsp,
    freezer: FrozenDateTimeFactory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A failing exchange action is counted and logged at debug level."""
    entry = await _setup(hass, can=can_esp)
    channel = entry.runtime_data.channels["can"]
    can_esp.fail_actions.add("daikin_can_exchange")
    caplog.set_level("DEBUG")
    await _tick(hass, freezer, 0.2)
    assert channel.errors == 1
    assert "can exchange failed" in caplog.text
    can_esp.fail_actions.clear()
    await _tick(hass, freezer, 0.2)
    assert channel.exchanges >= 1


async def test_exchange_timeout(
    hass: HomeAssistant, can_esp: SimulatedEsp, freezer: FrozenDateTimeFactory
) -> None:
    """An unanswered exchange times out and the next one runs."""
    entry = await _setup(hass, can=can_esp)
    channel = entry.runtime_data.channels["can"]
    can_esp.action_hook = lambda name, args: name != "daikin_can_exchange"
    freezer.tick(timedelta(seconds=0.2))
    async_fire_time_changed(hass)
    # The request is on its way; let the action timeout expire.
    await _tick(hass, freezer, 4)
    assert channel.errors >= 1
    can_esp.action_hook = None
    exchanges = channel.exchanges
    await _tick(hass, freezer, 0.2)
    assert channel.exchanges > exchanges


async def test_frames_dropped_on_connection_loss(
    hass: HomeAssistant,
    can_esp: SimulatedEsp,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Frames that wait while the connection drops are reported as lost."""
    entry = await _setup(hass, can=can_esp)
    channel = entry.runtime_data.channels["can"]
    can_esp.action_hook = lambda name, args: name != "daikin_can_exchange"
    channel.async_send([FRAME])
    channel.async_send([FRAME, FRAME])
    await can_esp.stop()
    await wait_for_state(hass, CONNECTION, STATE_OFF)
    await hass.async_block_till_done()
    assert "dropped 2 CAN frames because the connection was lost" in caplog.text
    assert channel.errors == 1


async def test_many_frames_split(
    hass: HomeAssistant, can_esp: SimulatedEsp, freezer: FrozenDateTimeFactory
) -> None:
    """More frames than the bridge queue holds are handed over in several calls."""
    entry = await _setup(hass, can=can_esp)
    channel = entry.runtime_data.channels["can"]
    results = []
    channel.async_add_listener(results.append)
    channel.async_send([FRAME] * 20)
    await hass.async_block_till_done()
    assert can_esp.can is not None
    assert len(can_esp.can.tx_queue) + len(can_esp.can.sent) < 20
    for _ in range(3):
        await _tick(hass, freezer, 0.2)
    in_bridge = len(can_esp.can.tx_queue) + len(can_esp.can.sent)
    assert in_bridge + len(channel._queue) == 20
    assert len(can_esp.can.sent) == 3
    assert can_esp.can.dropped == 0
    assert all(r.dropped == 0 for r in results)


async def test_uart_channel(
    hass: HomeAssistant, uart_esp: SimulatedEsp, freezer: FrozenDateTimeFactory
) -> None:
    """Bytes are handed to the UART bridge and the answer is collected."""
    entry = await _setup(hass, uart=uart_esp)
    channel = entry.runtime_data.channels["uart"]
    received = bytearray()
    channel.async_add_listener(lambda result: received.extend(result.received))
    channel.async_send(bytes.fromhex("0340615B"))
    await hass.async_block_till_done()
    await _tick(hass, freezer, 0.2)
    assert received.hex().upper() == "40610E000102030405060708090A0B0E"
    remove = channel.async_add_listener(lambda result: None)
    remove()


async def test_invalid_bridge_info_at_setup(
    hass: HomeAssistant, can_esp: SimulatedEsp
) -> None:
    """A malformed info answer defers the setup."""
    can_esp.info_overrides["buses"] = "can"
    entry = daikin_entry(hass, can=can_esp)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_failing_info_refresh_keeps_values(
    hass: HomeAssistant, can_esp: SimulatedEsp, freezer: FrozenDateTimeFactory
) -> None:
    """A failing info refresh keeps the last values."""
    entry = await _setup(hass, can=can_esp)
    can_esp.fail_actions.add("daikin_bridge_info")
    await _tick(hass, freezer, 60)
    assert (
        hass.states.get("sensor.daikin_bridge_daikin_can_wi_fi_signal").state == "-61"
    )
    node = entry.runtime_data.nodes[MAC_CAN]
    await node.async_stop()
    await node.async_refresh_info()


async def test_wrong_device_at_esphome_address(
    hass: HomeAssistant, can_esp: SimulatedEsp, uart_esp: SimulatedEsp
) -> None:
    """Another device at the ESPHome address is skipped; the stored one works."""
    entry = daikin_entry(hass, can=can_esp)
    esphome_entry(hass, can_esp)
    esphome = hass.config_entries.async_entries("esphome")[0]
    hass.config_entries.async_update_entry(
        esphome,
        data={**esphome.data, "port": uart_esp.port, "noise_psk": uart_esp.noise_psk},
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    target = entry.runtime_data.nodes[MAC_CAN].connected_target
    assert target is not None
    assert target.source == "stored"


async def test_auth_failure_on_reconnect(
    hass: HomeAssistant, can_esp: SimulatedEsp, freezer: FrozenDateTimeFactory
) -> None:
    """A key change while running starts the reauth flow and stops retrying."""
    await _setup(hass, can=can_esp)
    can_esp.noise_psk = make_noise_psk(77)
    await can_esp.drop_connections()
    await wait_for_state(hass, CONNECTION, STATE_OFF)
    await _tick(hass, freezer, 1)
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert [flow["context"]["source"] for flow in flows] == ["reauth"]
    connections = can_esp.stats.connections
    await _tick(hass, freezer, 120)
    assert can_esp.stats.connections == connections


async def test_missing_bus_logged(
    hass: HomeAssistant,
    can_esp: SimulatedEsp,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A bridge that lacks an assigned bus logs it; the bus stays unavailable."""
    entry = await _setup(hass, can=can_esp, uart=can_esp)
    assert "does not offer the assigned bus(es) uart" in caplog.text
    assert not entry.runtime_data.channels["uart"].available
    assert entry.runtime_data.channels["can"].available
    assert hass.states.get(CONNECTION).state == STATE_ON


async def test_start_after_stop(hass: HomeAssistant, can_esp: SimulatedEsp) -> None:
    """A stopped node can be started again."""
    entry = await _setup(hass, can=can_esp)
    node = entry.runtime_data.nodes[MAC_CAN]
    await node.async_stop()
    node.async_start()
    node.async_start()
    await node.async_connect()
    await hass.async_block_till_done()
    assert node.connected
    await node.async_connect()


def test_sensor_values_without_info() -> None:
    """Sensors return None before the first bridge info."""
    node = MagicMock(info=None, boot_time=None)
    assert {d.key: d.value_fn(node) for d in BRIDGE_SENSORS} == dict.fromkeys(
        (d.key for d in BRIDGE_SENSORS), None
    )
    node.info = MagicMock(can=None, uart=None)
    assert (
        next(d for d in BRIDGE_SENSORS if d.key == "can_bus_state").value_fn(node)
        is None
    )
    node.info.can = MagicMock(state="weird")
    assert (
        next(d for d in BRIDGE_SENSORS if d.key == "can_bus_state").value_fn(node)
        == "unknown"
    )


async def test_esphome_entry_without_host(
    hass: HomeAssistant, can_esp: SimulatedEsp
) -> None:
    """An ESPHome entry without host is not used."""
    entry = esphome_entry(hass, can_esp)
    hass.config_entries.async_update_entry(entry, data={**entry.data, "host": ""})
    assert resolve.esphome_entry_target(hass, MAC_CAN) is None


async def test_resolve_node_name(hass: HomeAssistant) -> None:
    """The `.local` name is looked up via the zeroconf instance."""
    info = MagicMock()
    info.async_request = AsyncMock(return_value=True)
    info.parsed_scoped_addresses.return_value = ["192.168.0.9"]
    with (
        patch.object(resolve, "AsyncServiceInfo", return_value=info),
        patch.object(resolve.zeroconf, "async_get_async_instance", AsyncMock()),
    ):
        assert await real_resolve_node_name(hass, "x") == "192.168.0.9"
        info.parsed_scoped_addresses.return_value = []
        assert await real_resolve_node_name(hass, "x") is None
        info.async_request = AsyncMock(return_value=False)
        assert await real_resolve_node_name(hass, "x") is None


async def test_resolve_error_falls_back(
    hass: HomeAssistant, mdns: dict[str, str]
) -> None:
    """A failing mDNS lookup falls back to the stored address."""
    with patch.object(resolve, "async_resolve_node_name", side_effect=OSError("boom")):
        targets = await resolve.async_targets(
            hass, mac=MAC_CAN, name="x", host="10.0.0.1", port=6053, noise_psk=None
        )
    assert [t.source for t in targets] == ["stored"]


async def test_more_frames_fetched_at_once(
    hass: HomeAssistant, can_esp: SimulatedEsp, freezer: FrozenDateTimeFactory
) -> None:
    """More frames than fit into one answer are fetched in the same cycle."""
    entry = await _setup(hass, can=can_esp)
    channel = entry.runtime_data.channels["can"]
    received = []
    channel.async_add_listener(lambda result: received.extend(result.received))
    assert can_esp.can is not None
    for i in range(150):
        can_esp.can.inject(SimCanFrame(0x10A, bytes((0x30, 0, 0x28, 0, i, 0, 0))))
    await _tick(hass, freezer, 0.2)
    assert len(received) == 150
