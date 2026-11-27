"""Numbers of the Daikin Heat Pump Control integration."""

from typing import override

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .can.table import CAN_VALUES, CanValue, Platform
from .entity import CanEntity, enum_or_none
from .runtime import DaikinConfigEntry

PARALLEL_UPDATES = 1


def _description(value: CanValue) -> NumberEntityDescription:
    assert value.minimum is not None
    assert value.maximum is not None
    assert value.step is not None
    return NumberEntityDescription(
        key=value.key,
        translation_key=value.key,
        device_class=enum_or_none(NumberDeviceClass, value.device_class),
        native_unit_of_measurement=value.unit,
        native_min_value=value.minimum,
        native_max_value=value.maximum,
        native_step=value.step,
        mode=NumberMode.BOX,
        entity_category=enum_or_none(EntityCategory, value.category),
        entity_registry_enabled_default=value.enabled_default,
    )


CAN_NUMBERS: tuple[NumberEntityDescription, ...] = tuple(
    _description(value) for value in CAN_VALUES if value.platform is Platform.NUMBER
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DaikinConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the numbers."""
    if (coordinator := entry.runtime_data.can) is None:
        return
    async_add_entities(
        CanNumber(coordinator, description) for description in CAN_NUMBERS
    )


class CanNumber(CanEntity, NumberEntity):
    """Numeric setting of the RoCon controller."""

    @property
    @override
    def native_value(self) -> float | None:
        """Return the value."""
        state = self.can_state
        return state if isinstance(state, float) else None

    @override
    async def async_set_native_value(self, value: float) -> None:
        """Change the value."""
        await self._async_write(value)
