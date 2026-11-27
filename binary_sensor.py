"""Binary sensors of the Daikin Heat Pump Control integration."""

from typing import override

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .entity import BridgeEntity
from .runtime import DaikinConfigEntry

PARALLEL_UPDATES = 0

CONNECTED = BinarySensorEntityDescription(
    key="connected",
    translation_key="connected",
    device_class=BinarySensorDeviceClass.CONNECTIVITY,
    entity_category=EntityCategory.DIAGNOSTIC,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DaikinConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the binary sensors."""
    async_add_entities(
        BridgeConnectedSensor(node, CONNECTED)
        for node in entry.runtime_data.nodes.values()
    )


class BridgeConnectedSensor(BridgeEntity, BinarySensorEntity):
    """Connection state of a bridge node; always available."""

    @property
    @override
    def available(self) -> bool:
        """Return True; the state itself tells whether the node is reachable."""
        return True

    @property
    @override
    def is_on(self) -> bool:
        """Return True while the node is connected."""
        return self.node.connected
