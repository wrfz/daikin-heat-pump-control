"""The Daikin Heat Pump Control integration."""

import asyncio
from functools import partial
import logging

from homeassistant.const import EVENT_HOMEASSISTANT_STOP, Platform
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import (
    config_validation as cv,
    device_registry as dr,
    entity_registry as er,
    issue_registry as ir,
)
from homeassistant.helpers.typing import ConfigType

from .bridge.client import BridgeAuthError, BridgeConnectionError
from .bridge.node import BridgeNode, CanChannel, UartChannel
from .const import (
    BUS_CONF,
    CONF_NODE_NAME,
    CONF_NODES,
    CONF_NOISE_PSK,
    CONF_OUTDOOR_UNIT,
    CONF_UART_DETECTED_PROTOCOL,
    CONF_UART_PROTOCOL,
    DEFAULT_PORT,
    DOMAIN,
    ISSUE_NO_BRIDGE_FIRMWARE,
    Bus,
)
from .coordinator import (
    CanCoordinator,
    entity_defaults,
    error_settings,
    polling_intervals,
)
from .entity import (
    async_register_devices,
    async_update_bridge_device,
    bridge_device_identifier,
    bus_device_identifier,
    bus_unique_id,
)
from .panel import async_register_panel, async_setup_frontend
from .runtime import DaikinConfigEntry, DaikinRuntimeData
from .services import async_setup_services
from .storage import CanStorage, PanelStorage
from .uart.protocol import Protocol
from .uart.table import outdoor_unit
from .uart_coordinator import UartCoordinator, resolve_protocol, uart_entities
from .websocket import async_setup_websocket

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
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


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the services, the WebSocket API and the frontend module."""
    async_setup_services(hass)
    async_setup_websocket(hass)
    await async_setup_frontend(hass)
    return True


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
        storage = CanStorage(hass, entry.entry_id)
        await storage.async_load()
        can = CanCoordinator(
            hass,
            channel,
            active=_active_keys(hass, entry, Bus.CAN, entity_defaults()),
            intervals=polling_intervals(entry.options),
            storage=storage,
            settings=error_settings(entry.options),
        )
        entry.async_on_unload(can.async_start())
    uart = None
    if isinstance(channel := channels.get(Bus.UART), UartChannel):
        uart = _create_uart(hass, entry, channel)
        entry.async_on_unload(uart.async_start())
    panel = PanelStorage(hass, entry.entry_id)
    await panel.async_load()
    entry.runtime_data = DaikinRuntimeData(
        nodes=nodes, channels=channels, panel=panel, can=can, uart=uart
    )
    _async_update_devices(hass, entry)
    _async_remove_stale_issues(hass, entry)

    async def _async_on_hass_stop(_event: Event) -> None:
        await _async_stop_nodes(nodes)

    entry.async_on_unload(
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _async_on_hass_stop)
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await async_register_panel(hass, entry)
    for node in nodes.values():
        entry.async_on_unload(
            node.async_add_listener(partial(async_update_bridge_device, node))
        )
        node.async_start()
    return True


def _active_keys(
    hass: HomeAssistant, entry: DaikinConfigEntry, bus: Bus, defaults: dict[str, bool]
) -> set[str]:
    """Return the keys of the enabled entities of a bus.

    Entities not registered yet count as their default; values that no
    enabled entity needs are not polled. Enabling an entity reloads the entry.
    """
    registered: dict[str, bool] = {}
    prefix = bus_unique_id(entry, bus, "")
    for entity in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id):
        if entity.unique_id.startswith(prefix):
            registered[entity.unique_id.removeprefix(prefix)] = not entity.disabled
    return {key for key, default in defaults.items() if registered.get(key, default)}


def _create_uart(
    hass: HomeAssistant, entry: DaikinConfigEntry, channel: UartChannel
) -> UartCoordinator:
    """Create the UART coordinator for the configured unit and protocol."""
    unit = outdoor_unit(entry.options.get(CONF_OUTDOOR_UNIT))
    protocol, may_detect = resolve_protocol(
        entry.options.get(CONF_UART_PROTOCOL),
        entry.data.get(CONF_UART_DETECTED_PROTOCOL),
    )
    entities = uart_entities(unit, protocol)
    if protocol is not None:
        _async_remove_other_entities(hass, entry, Bus.UART, set(entities))

    @callback
    def _on_detected(detected: Protocol) -> None:
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, CONF_UART_DETECTED_PROTOCOL: detected.value}
        )
        hass.config_entries.async_schedule_reload(entry.entry_id)

    return UartCoordinator(
        hass,
        channel,
        unit=unit,
        protocol=protocol,
        may_detect=may_detect,
        active=_active_keys(hass, entry, Bus.UART, entities),
        on_detected=_on_detected,
    )


def _async_remove_other_entities(
    hass: HomeAssistant, entry: DaikinConfigEntry, bus: Bus, keys: set[str]
) -> None:
    """Remove the entities of a bus that the current configuration does not offer."""
    registry = er.async_get(hass)
    prefix = bus_unique_id(entry, bus, "")
    for entity in er.async_entries_for_config_entry(registry, entry.entry_id):
        if (
            entity.unique_id.startswith(prefix)
            and entity.unique_id.removeprefix(prefix) not in keys
        ):
            _LOGGER.debug("Removing entity %s", entity.entity_id)
            registry.async_remove(entity.entity_id)


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


async def async_remove_entry(hass: HomeAssistant, entry: DaikinConfigEntry) -> None:
    """Remove the stored state of a removed config entry."""
    await CanStorage(hass, entry.entry_id).async_remove()
    await PanelStorage(hass, entry.entry_id).async_remove()


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: DaikinConfigEntry, device: dr.DeviceEntry
) -> bool:
    """Allow removing devices that are no longer part of the configuration."""
    current = {bridge_device_identifier(mac) for mac in entry.runtime_data.nodes}
    current |= {
        bus_device_identifier(entry, bus) for bus in entry.runtime_data.channels
    }
    return not device.identifiers & current
