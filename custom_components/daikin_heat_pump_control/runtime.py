"""Runtime data of a config entry."""

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry

from .bridge.node import BridgeNode, BusChannel
from .const import Bus
from .coordinator import CanCoordinator
from .uart_coordinator import UartCoordinator


@dataclass(slots=True, kw_only=True)
class DaikinRuntimeData:
    """Objects shared by the platforms of a config entry."""

    nodes: dict[str, BridgeNode]
    channels: dict[Bus, BusChannel]
    can: CanCoordinator | None = None
    uart: UartCoordinator | None = None


type DaikinConfigEntry = ConfigEntry[DaikinRuntimeData]
