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

from .can.table import CAN_VALUES, Platform
from .entity import BridgeEntity, CanEntity, UartEntity, enum_or_none
from .runtime import DaikinConfigEntry
from .uart.table import Platform as UartPlatform
from .uart_coordinator import UartCoordinator, uart_entities

PARALLEL_UPDATES = 0

CONNECTED = BinarySensorEntityDescription(
    key="connected",
    translation_key="connected",
    device_class=BinarySensorDeviceClass.CONNECTIVITY,
    entity_category=EntityCategory.DIAGNOSTIC,
)

CAN_BINARY_SENSORS: tuple[BinarySensorEntityDescription, ...] = tuple(
    BinarySensorEntityDescription(
        key=value.key,
        translation_key=value.key,
        device_class=enum_or_none(BinarySensorDeviceClass, value.device_class),
        entity_category=enum_or_none(EntityCategory, value.category),
        entity_registry_enabled_default=value.enabled_default,
    )
    for value in CAN_VALUES
    if value.platform is Platform.BINARY_SENSOR
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DaikinConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the binary sensors."""
    entities: list[BinarySensorEntity] = [
        BridgeConnectedSensor(node, CONNECTED)
        for node in entry.runtime_data.nodes.values()
    ]
    if (coordinator := entry.runtime_data.can) is not None:
        entities.extend(
            CanBinarySensor(coordinator, description)
            for description in CAN_BINARY_SENSORS
        )
    if (uart := entry.runtime_data.uart) is not None:
        entities.extend(
            UartBinarySensor(uart, description)
            for description in uart_binary_sensors(uart)
        )
    async_add_entities(entities)


def uart_binary_sensors(
    coordinator: UartCoordinator,
) -> list[BinarySensorEntityDescription]:
    """Return the binary sensors the outdoor unit offers in the protocol in use."""
    descriptions: list[BinarySensorEntityDescription] = []
    for key, enabled in uart_entities(coordinator.unit, coordinator.protocol).items():
        active = coordinator.values.get(key)
        if active is None or active.value.platform is not UartPlatform.BINARY_SENSOR:
            continue
        value = active.value
        descriptions.append(
            BinarySensorEntityDescription(
                key=key,
                translation_key=value.translation_key or key,
                device_class=enum_or_none(BinarySensorDeviceClass, value.device_class),
                entity_category=enum_or_none(EntityCategory, value.category),
                entity_registry_enabled_default=enabled,
            )
        )
    return descriptions


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


class CanBinarySensor(CanEntity, BinarySensorEntity):
    """Binary value of the RoCon controller."""

    @property
    @override
    def is_on(self) -> bool | None:
        """Return the state."""
        state = self.can_state
        return state if isinstance(state, bool) else None


class UartBinarySensor(UartEntity, BinarySensorEntity):
    """Binary value of the indoor unit."""

    @property
    @override
    def is_on(self) -> bool | None:
        """Return the state."""
        state = self.uart_state
        return state if isinstance(state, bool) else None
