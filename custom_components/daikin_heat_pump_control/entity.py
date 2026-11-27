"""Devices and base entities."""

from enum import StrEnum
from typing import TYPE_CHECKING, NoReturn, override

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity, EntityDescription

from .bridge.node import BridgeNode
from .can.table import CAN_VALUES_BY_KEY, StateValue
from .const import DOMAIN, Bus
from .coordinator import CanCoordinator, CanState

if TYPE_CHECKING:
    from .runtime import DaikinConfigEntry

BUS_DEVICE_NAMES = {Bus.CAN: "Daikin CAN", Bus.UART: "Daikin UART"}
BUS_DEVICE_MODELS = {Bus.CAN: "RoCon (CAN)", Bus.UART: "Indoor unit (UART)"}


def bridge_device_identifier(mac: str) -> tuple[str, str]:
    """Return the device identifier of a bridge node."""
    return (DOMAIN, f"bridge_{mac}")


def bus_device_identifier(entry: ConfigEntry, bus: Bus) -> tuple[str, str]:
    """Return the device identifier of a bus device."""
    return (DOMAIN, f"{entry.entry_id}_{bus}")


def _bridge_model(node: BridgeNode) -> str:
    buses = " + ".join(bus.upper() for bus in sorted(node.assigned_buses))
    return f"{buses} bridge"


@callback
def async_register_devices(
    hass: HomeAssistant, entry: DaikinConfigEntry
) -> set[tuple[str, str]]:
    """Create or update the bridge and bus devices; return their identifiers."""
    registry = dr.async_get(hass)
    identifiers: set[tuple[str, str]] = set()
    bridge_ids: dict[str, str] = {}
    for node in entry.runtime_data.nodes.values():
        identifier = bridge_device_identifier(node.mac)
        device = registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={identifier},
            name=f"Daikin Bridge {node.name or node.mac}",
            manufacturer="wrfz",
            model=_bridge_model(node),
            sw_version=(node.info.bridge_version or None) if node.info else None,
        )
        bridge_ids[node.mac] = device.id
        identifiers.add(identifier)
    for bus, channel in entry.runtime_data.channels.items():
        identifier = bus_device_identifier(entry, bus)
        registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={identifier},
            name=BUS_DEVICE_NAMES[bus],
            manufacturer="Daikin",
            model=BUS_DEVICE_MODELS[bus],
            via_device_id=bridge_ids[channel.node.mac],
        )
        identifiers.add(identifier)
    return identifiers


class BridgeEntity(Entity):
    """Diagnostic entity of a bridge node."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, node: BridgeNode, description: EntityDescription) -> None:
        """Initialize the entity."""
        self.node = node
        self.entity_description = description
        self._attr_unique_id = f"{node.entry.entry_id}_{node.mac}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={bridge_device_identifier(node.mac)}
        )

    @property
    @override
    def available(self) -> bool:
        """Return True while the bridge answers."""
        return self.node.bridge_ready

    @override
    async def async_added_to_hass(self) -> None:
        """Subscribe to node updates."""
        self.async_on_remove(self.node.async_add_listener(self._handle_node_update))

    @callback
    def _handle_node_update(self) -> None:
        self.async_write_ha_state()


def enum_or_none[E: StrEnum](enum: type[E], value: str | None) -> E | None:
    """Convert a plain string of the value table to a Home Assistant enum."""
    return None if value is None else enum(value)


def can_unique_id(entry: ConfigEntry, key: str) -> str:
    """Return the unique id of a CAN entity."""
    return f"{entry.entry_id}_{Bus.CAN}_{key}"


class CanEntity(Entity):
    """Entity of a value of the RoCon controller."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self, coordinator: CanCoordinator, description: EntityDescription
    ) -> None:
        """Initialize the entity."""
        self.coordinator = coordinator
        self.entity_description = description
        entry = coordinator.channel.node.entry
        self._attr_unique_id = can_unique_id(entry, description.key)
        self._attr_device_info = DeviceInfo(
            identifiers={bus_device_identifier(entry, Bus.CAN)}
        )

    @property
    @override
    def available(self) -> bool:
        """Return True while the CAN bus can be used."""
        return self.coordinator.available

    @property
    def can_state(self) -> CanState:
        """Return the state of the value."""
        return self.coordinator.state(self.entity_description.key)

    @override
    async def async_added_to_hass(self) -> None:
        """Subscribe to changes of the value."""
        self.async_on_remove(
            self.coordinator.async_add_listener(
                self.entity_description.key, self._handle_update
            )
        )

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()

    def _raise_read_only(self) -> NoReturn:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="write_not_supported",
            translation_placeholders={"entity": self.entity_id},
        )

    async def _async_write(self, state: StateValue) -> None:
        """Write the setting and wait for the read-back of the heat pump."""
        key = self.entity_description.key
        if not CAN_VALUES_BY_KEY[key].can_write:
            self._raise_read_only()
        await self.coordinator.async_write(key, state)


@callback
def async_update_bridge_device(node: BridgeNode) -> None:
    """Keep the firmware version of the bridge device current."""
    registry = dr.async_get(node.hass)
    device = registry.async_get_device_by_identifier(
        bridge_device_identifier(node.mac), node.entry.entry_id
    )
    if device is None or node.info is None or not node.info.bridge_version:
        return
    if device.sw_version != node.info.bridge_version:
        registry.async_update_device(device.id, sw_version=node.info.bridge_version)
