"""The Daikin Heat Pump Control integration."""

import asyncio
from functools import partial
import logging

from homeassistant.const import EVENT_HOMEASSISTANT_STOP, Platform
from homeassistant.core import Event, HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import (
    device_registry as dr,
    entity_registry as er,
    issue_registry as ir,
)

from .bridge.client import BridgeAuthError, BridgeConnectionError
from .bridge.node import BridgeNode, CanChannel
from .const import (
    BUS_CONF,
    CONF_NODE_NAME,
    CONF_NODES,
    CONF_NOISE_PSK,
    DEFAULT_PORT,
    DOMAIN,
    ISSUE_NO_BRIDGE_FIRMWARE,
    Bus,
)
from .coordinator import CanCoordinator, entity_defaults, polling_intervals
from .entity import (
    async_register_devices,
    async_update_bridge_device,
    bridge_device_identifier,
    bus_device_identifier,
    can_unique_id,
)
from .runtime import DaikinConfigEntry, DaikinRuntimeData

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]


def _assigned_buses(entry: DaikinConfigEntry) -> dict[str, set[Bus]]:
    """Return the buses assigned to each node MAC."""
    assigned: dict[str, set[Bus]] = {}
    for bus, key in BUS_CONF.items():
        if mac := entry.data.get(key):
            assigned.setdefault(mac, set()).add(bus)
    return assigned


def _create_nodes(
    hass: HomeAssistant, entry: DaikinConfigEntry
) -> dict[str, BridgeNode]:
    nodes: dict[str, BridgeNode] = {}
    stored = entry.data.get(CONF_NODES, {})
    for mac, buses in _assigned_buses(entry).items():
        config = stored.get(mac, {})
        nodes[mac] = BridgeNode(
            hass,
            entry,
            mac=mac,
            name=config.get(CONF_NODE_NAME, ""),
            host=config.get("host", ""),
            port=int(config.get("port", DEFAULT_PORT)),
            noise_psk=config.get(CONF_NOISE_PSK),
            buses=frozenset(buses),
        )
    return nodes


async def _async_stop_nodes(nodes: dict[str, BridgeNode]) -> None:
    await asyncio.gather(*(node.async_stop() for node in nodes.values()))


async def async_setup_entry(hass: HomeAssistant, entry: DaikinConfigEntry) -> bool:
    """Set up Daikin Heat Pump Control from a config entry."""
    nodes = _create_nodes(hass, entry)
    results = await asyncio.gather(
        *(node.async_connect() for node in nodes.values()), return_exceptions=True
    )
    for node, result in zip(nodes.values(), results, strict=True):
        if isinstance(result, BridgeAuthError):
            await _async_stop_nodes(nodes)
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN,
                translation_key="invalid_auth",
                translation_placeholders={"name": node.title},
            ) from result
    for node, result in zip(nodes.values(), results, strict=True):
        if isinstance(result, BridgeConnectionError):
            await _async_stop_nodes(nodes)
            raise ConfigEntryNotReady(
                translation_domain=DOMAIN,
                translation_key="cannot_connect",
                translation_placeholders={"name": node.title, "error": str(result)},
            ) from result
        if isinstance(result, BaseException):  # pragma: no cover
            await _async_stop_nodes(nodes)
            raise result

    channels = {
        bus: channel
        for node in nodes.values()
        for bus, channel in node.channels.items()
    }
    can = None
    if isinstance(channel := channels.get(Bus.CAN), CanChannel):
        can = CanCoordinator(
            hass,
            channel,
            active=_active_can_keys(hass, entry),
            intervals=polling_intervals(entry.options),
        )
        entry.async_on_unload(can.async_start())
    entry.runtime_data = DaikinRuntimeData(nodes=nodes, channels=channels, can=can)
    _async_update_devices(hass, entry)
    _async_remove_stale_issues(hass, entry)

    async def _async_on_hass_stop(_event: Event) -> None:
        await _async_stop_nodes(nodes)

    entry.async_on_unload(
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _async_on_hass_stop)
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    for node in nodes.values():
        entry.async_on_unload(
            node.async_add_listener(partial(async_update_bridge_device, node))
        )
        node.async_start()
    return True


def _active_can_keys(hass: HomeAssistant, entry: DaikinConfigEntry) -> set[str]:
    """Return the keys of the enabled CAN entities.

    Entities not registered yet count as their default; values that no
    enabled entity needs are not polled. Enabling an entity reloads the entry.
    """
    registered: dict[str, bool] = {}
    prefix = can_unique_id(entry, "")
    for entity in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id):
        if entity.unique_id.startswith(prefix):
            registered[entity.unique_id.removeprefix(prefix)] = not entity.disabled
    return {
        key
        for key, default in entity_defaults().items()
        if registered.get(key, default)
    }


def _async_update_devices(hass: HomeAssistant, entry: DaikinConfigEntry) -> None:
    """Create the bridge and bus devices and remove those no longer used."""
    expected = async_register_devices(hass, entry)
    registry = dr.async_get(hass)
    for device in dr.async_entries_for_config_entry(registry, entry.entry_id):
        if not device.identifiers & expected:
            _LOGGER.debug("Removing stale device %s", device.name)
            registry.async_update_device(
                device.id, remove_config_entry_id=entry.entry_id
            )


def _async_remove_stale_issues(hass: HomeAssistant, entry: DaikinConfigEntry) -> None:
    current = {node.issue_id for node in entry.runtime_data.nodes.values()}
    registry = ir.async_get(hass)
    for domain, issue_id in list(registry.issues):
        if (
            domain == DOMAIN
            and issue_id.startswith(ISSUE_NO_BRIDGE_FIRMWARE)
            and issue_id not in current
        ):
            ir.async_delete_issue(hass, DOMAIN, issue_id)


async def async_unload_entry(hass: HomeAssistant, entry: DaikinConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await _async_stop_nodes(entry.runtime_data.nodes)
    return unloaded


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: DaikinConfigEntry, device: dr.DeviceEntry
) -> bool:
    """Allow removing devices that are no longer part of the configuration."""
    current = {bridge_device_identifier(mac) for mac in entry.runtime_data.nodes}
    current |= {
        bus_device_identifier(entry, bus) for bus in entry.runtime_data.channels
    }
    return not device.identifiers & current
