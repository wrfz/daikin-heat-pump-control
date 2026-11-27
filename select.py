"""Selects of the Daikin Heat Pump Control integration."""

from typing import override

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .can.table import CAN_VALUES, Platform
from .entity import CanEntity, enum_or_none
from .runtime import DaikinConfigEntry

PARALLEL_UPDATES = 1

CAN_SELECTS: tuple[SelectEntityDescription, ...] = tuple(
    SelectEntityDescription(
        key=value.key,
        translation_key=value.key,
        options=value.option_keys,
        entity_category=enum_or_none(EntityCategory, value.category),
        entity_registry_enabled_default=value.enabled_default,
    )
    for value in CAN_VALUES
    if value.platform is Platform.SELECT
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DaikinConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the selects."""
    if (coordinator := entry.runtime_data.can) is None:
        return
    async_add_entities(
        CanSelect(coordinator, description) for description in CAN_SELECTS
    )


class CanSelect(CanEntity, SelectEntity):
    """Setting of the RoCon controller with a list of options."""

    @property
    @override
    def current_option(self) -> str | None:
        """Return the selected option."""
        state = self.can_state
        return state if isinstance(state, str) else None

    @override
    async def async_select_option(self, option: str) -> None:
        """Change the option."""
        self._raise_read_only()
