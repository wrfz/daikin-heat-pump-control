"""Buttons of the Daikin Heat Pump Control integration."""

from typing import override

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import DHW_RUN
from .entity import CanEntity
from .runtime import DaikinConfigEntry

PARALLEL_UPDATES = 1

DHW_RUN_BUTTON = ButtonEntityDescription(key=DHW_RUN, translation_key=DHW_RUN)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DaikinConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the buttons."""
    if (coordinator := entry.runtime_data.can) is None:
        return
    async_add_entities([HotWaterRunButton(coordinator, DHW_RUN_BUTTON)])


class HotWaterRunButton(CanEntity, ButtonEntity):
    """Start a hot water load."""

    @override
    async def async_press(self) -> None:
        """Raise hot water setpoint 1 to 70 °C and set it back once confirmed."""
        await self.coordinator.async_run_hot_water()
