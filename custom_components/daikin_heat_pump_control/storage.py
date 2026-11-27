"""Stored state of the CAN bus: the writes of the day and the defrost switch."""

from collections import Counter
from datetime import date, datetime
from typing import Any, Final, TypedDict

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import DOMAIN

STORAGE_VERSION: Final = 1
SAVE_DELAY: Final = 10.0


class _StoredData(TypedDict):
    optimized_defrosting: bool
    writes: list[list[str]]


class CanStorage:
    """Times of the writes of the current day and the defrost switch."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        """Initialize the storage of a config entry."""
        self._store: Store[_StoredData] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry_id}"
        )
        self.optimized_defrosting = False
        self._writes: list[tuple[datetime, str]] = []

    async def async_load(self) -> None:
        """Load the stored state."""
        data = await self._store.async_load()
        if data is None:
            return
        self.optimized_defrosting = bool(data.get("optimized_defrosting", False))
        self._writes = [
            (time, str(item[1]))
            for item in data.get("writes", [])
            if isinstance(item, list)
            and len(item) == 2
            and (time := dt_util.parse_datetime(item[0])) is not None
        ]
        self._prune()

    def _data(self) -> _StoredData:
        return {
            "optimized_defrosting": self.optimized_defrosting,
            "writes": [[time.isoformat(), key] for time, key in self._writes],
        }

    def _save(self) -> None:
        self._store.async_delay_save(self._data, SAVE_DELAY)

    async def async_remove(self) -> None:
        """Remove the stored state."""
        await self._store.async_remove()

    def _today(self) -> date:
        return dt_util.now().date()

    def _prune(self) -> None:
        today = self._today()
        self._writes = [
            (time, key)
            for time, key in self._writes
            if dt_util.as_local(time).date() == today
        ]

    def set_optimized_defrosting(self, on: bool) -> None:
        """Store the state of the defrost switch."""
        if on != self.optimized_defrosting:
            self.optimized_defrosting = on
            self._save()

    def record_write(self, key: str) -> None:
        """Record a write sent to the heat pump."""
        self._prune()
        self._writes.append((dt_util.utcnow(), key))
        self._save()

    def writes_today(self) -> int:
        """Return the number of writes of the current day."""
        self._prune()
        return len(self._writes)

    def writes_by_key(self) -> dict[str, int]:
        """Return the writes of the current day per value."""
        self._prune()
        return dict(sorted(Counter(key for _, key in self._writes).items()))

    def diagnostics(self) -> dict[str, Any]:
        """Return the stored state."""
        return {
            "optimized_defrosting": self.optimized_defrosting,
            "writes_today": self.writes_by_key(),
        }


class _PanelData(TypedDict):
    config: dict[str, Any]


class PanelStorage:
    """Appearance of the panel, shared by all users."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        """Initialize the storage of a config entry."""
        self._store: Store[_PanelData] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry_id}.panel"
        )
        self.config: dict[str, Any] = {}

    async def async_load(self) -> None:
        """Load the stored appearance."""
        data = await self._store.async_load()
        if data is not None and isinstance(data.get("config"), dict):
            self.config = data["config"]

    async def async_save(self, config: dict[str, Any]) -> None:
        """Store a new appearance."""
        self.config = config
        await self._store.async_save({"config": config})

    async def async_remove(self) -> None:
        """Remove the stored appearance."""
        await self._store.async_remove()
