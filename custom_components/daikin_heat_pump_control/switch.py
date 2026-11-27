"""Switches of the Daikin Heat Pump Control integration."""

from typing import Any, override

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .can.table import CAN_VALUES, Platform
from .coordinator import OPTIMIZED_DEFROSTING
from .entity import CanEntity, enum_or_none
from .runtime import DaikinConfigEntry

PARALLEL_UPDATES = 1

CAN_SWITCHES: tuple[SwitchEntityDescription, ...] = tuple(
    SwitchEntityDescription(
        key=value.key,
        translation_key=value.key,
        entity_category=enum_or_none(EntityCategory, value.category),
        entity_registry_enabled_default=value.enabled_default,
    )
    for value in CAN_VALUES
    if value.platform is Platform.SWITCH
)

OPTIMIZED_DEFROSTING_SWITCH = SwitchEntityDescription(
    key=OPTIMIZED_DEFROSTING,
    translation_key=OPTIMIZED_DEFROSTING,
    entity_category=EntityCategory.CONFIG,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DaikinConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the switches."""
    if (coordinator := entry.runtime_data.can) is None:
        return
    entities: list[SwitchEntity] = [
        CanSwitch(coordinator, description) for description in CAN_SWITCHES
    ]
    entities.append(OptimizedDefrostingSwitch(coordinator, OPTIMIZED_DEFROSTING_SWITCH))
    async_add_entities(entities)


class CanSwitch(CanEntity, SwitchEntity):
    """On/off setting of the RoCon controller."""

    @property
    @override
    def is_on(self) -> bool | None:
        """Return the state."""
        state = self.can_state
        return state if isinstance(state, bool) else None

    @override
    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the setting on."""
        await self._async_write(True)

    @override
    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the setting off."""
        await self._async_write(False)


class OptimizedDefrostingSwitch(CanEntity, SwitchEntity):
    """Switch of the defrost optimization; the state is kept by the integration."""

    @property
    @override
    def is_on(self) -> bool:
        """Return True while the optimization is on."""
        return self.coordinator.optimized_defrosting

    @override
    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the optimization on; this sets the antifreeze temperature to off."""
        await self.coordinator.async_set_optimized_defrosting(True)

    @override
    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the optimization off."""
        await self.coordinator.async_set_optimized_defrosting(False)
