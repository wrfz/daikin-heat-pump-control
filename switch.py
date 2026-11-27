"""Switches of the Daikin Heat Pump Control integration."""

from typing import Any, override

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .can.table import CAN_VALUES, Platform
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


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DaikinConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the switches."""
    if (coordinator := entry.runtime_data.can) is None:
        return
    async_add_entities(
        CanSwitch(coordinator, description) for description in CAN_SWITCHES
    )


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
        self._raise_read_only()

    @override
    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the setting off."""
        self._raise_read_only()
