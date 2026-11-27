"""Find the current address of a node."""

from dataclasses import dataclass
import logging

from zeroconf.asyncio import AsyncServiceInfo

from homeassistant.components import zeroconf
from homeassistant.core import HomeAssistant

from ..const import ESPHOME_CONF_NOISE_PSK, ESPHOME_DOMAIN
from .client import normalize_mac

_LOGGER = logging.getLogger(__name__)

ESPHOME_SERVICE_TYPE = "_esphomelib._tcp.local."
RESOLVE_TIMEOUT_MS = 3000


@dataclass(frozen=True, slots=True, kw_only=True)
class Target:
    """An address to try when connecting to a node."""

    host: str
    port: int
    noise_psk: str | None
    source: str


def esphome_entry_target(hass: HomeAssistant, mac: str) -> Target | None:
    """Return host, port and key of the ESPHome config entry with this MAC."""
    for entry in hass.config_entries.async_entries(
        ESPHOME_DOMAIN, include_ignore=False
    ):
        if entry.unique_id is None or normalize_mac(entry.unique_id) != mac:
            continue
        host = entry.data.get("host")
        if not host:
            return None
        return Target(
            host=host,
            port=int(entry.data.get("port", 6053)),
            noise_psk=entry.data.get(ESPHOME_CONF_NOISE_PSK) or None,
            source="esphome",
        )
    return None


async def async_resolve_node_name(hass: HomeAssistant, name: str) -> str | None:
    """Resolve `<name>.local` of an ESPHome node via mDNS."""
    aiozc = await zeroconf.async_get_async_instance(hass)
    info = AsyncServiceInfo(ESPHOME_SERVICE_TYPE, f"{name}.{ESPHOME_SERVICE_TYPE}")
    if not await info.async_request(aiozc.zeroconf, RESOLVE_TIMEOUT_MS):
        return None
    addresses = info.parsed_scoped_addresses()
    return addresses[0] if addresses else None


async def async_targets(
    hass: HomeAssistant,
    *,
    mac: str,
    name: str,
    host: str,
    port: int,
    noise_psk: str | None,
) -> list[Target]:
    """Return the addresses to try, best first.

    The ESPHome config entry of the node comes first because the ESPHome
    integration keeps its host and key current. Next is the mDNS name of the
    node, last the stored address.
    """
    targets: list[Target] = []
    if (esphome := esphome_entry_target(hass, mac)) is not None:
        targets.append(esphome)
    if name:
        try:
            resolved = await async_resolve_node_name(hass, name)
        except OSError as err:
            _LOGGER.debug("Resolving %s.local failed: %s", name, err)
            resolved = None
        if resolved is not None:
            targets.append(
                Target(host=resolved, port=port, noise_psk=noise_psk, source="mdns")
            )
    targets.append(Target(host=host, port=port, noise_psk=noise_psk, source="stored"))
    unique: list[Target] = []
    for target in targets:
        if not any(
            t.host == target.host
            and t.port == target.port
            and t.noise_psk == target.noise_psk
            for t in unique
        ):
            unique.append(target)
    return unique
