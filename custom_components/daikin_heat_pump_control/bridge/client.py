"""Open an ESPHome API connection to a node and find out what it runs."""

import asyncio
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from enum import StrEnum
import logging
from typing import Any

from aioesphomeapi import (
    APIClient,
    APIConnectionError,
    BadMACAddressAPIError,
    DeviceInfo,
    EncryptionPlaintextAPIError,
    InvalidAuthAPIError,
    InvalidEncryptionKeyAPIError,
    RequiresEncryptionAPIError,
    UserService,
)

from ..const import (
    ACTION_BRIDGE_INFO,
    ACTION_TIMEOUT,
    BUS_EXCHANGE_ACTION,
    CLIENT_INFO,
    CONNECT_TIMEOUT,
    LEGACY_MANIFEST_ACTIONS,
    Bus,
)
from .protocol import BridgeInfo, BridgeProtocolError, parse_bridge_info

_LOGGER = logging.getLogger(__name__)


class BridgeError(Exception):
    """Base class of bridge errors."""


class BridgeConnectionError(BridgeError):
    """The node cannot be reached or the connection failed."""


class BridgeAuthError(BridgeError):
    """The node rejected the API encryption key."""


class BridgeWrongDeviceError(BridgeConnectionError):
    """Another device answered at the address."""


class BridgeActionError(BridgeError):
    """A bridge action failed or returned an invalid response."""


class Firmware(StrEnum):
    """Firmware recognised on a node."""

    BRIDGE = "bridge"
    LEGACY = "legacy"
    OTHER = "other"


def normalize_mac(mac: str) -> str:
    """Return a MAC address as lowercase hex pairs separated by colons."""
    digits = "".join(ch for ch in mac.lower() if ch in "0123456789abcdef")
    if len(digits) != 12:
        return mac.lower()
    return ":".join(digits[i : i + 2] for i in range(0, 12, 2))


def _compact_mac(mac: str) -> str:
    return normalize_mac(mac).replace(":", "")


@dataclass(frozen=True, slots=True, kw_only=True)
class NodeIdentity:
    """What a node reported about itself and its firmware."""

    mac: str
    name: str
    friendly_name: str
    host: str
    port: int
    noise_psk: str | None
    project_name: str
    project_version: str
    esphome_version: str
    firmware: Firmware
    buses: frozenset[Bus]
    info: BridgeInfo | None

    @property
    def title(self) -> str:
        """Return a human readable name of the node."""
        return self.friendly_name or self.name


@dataclass(slots=True, kw_only=True)
class OpenConnection:
    """An open connection to a node."""

    client: APIClient
    identity: NodeIdentity
    services: dict[str, UserService]


async def async_execute(
    client: APIClient,
    service: UserService,
    data: dict[str, Any],
) -> bytes:
    """Execute an action and return its response data."""
    try:
        response = await client.execute_service(
            service, data, return_response=True, timeout=ACTION_TIMEOUT
        )
    except TimeoutError as err:
        raise BridgeActionError(f"Action {service.name} timed out") from err
    except APIConnectionError as err:
        raise BridgeActionError(f"Action {service.name} failed: {err}") from err
    if response is None or not response.success:
        message = response.error_message if response is not None else "no response"
        raise BridgeActionError(f"Action {service.name} failed: {message}")
    return bytes(response.response_data)


async def async_read_info(client: APIClient, service: UserService) -> BridgeInfo:
    """Call `daikin_bridge_info` and parse the answer."""
    data = await async_execute(client, service, {})
    try:
        return parse_bridge_info(data)
    except BridgeProtocolError as err:
        raise BridgeActionError(f"Invalid bridge info: {err}") from err


def _identify(
    device_info: DeviceInfo,
    services: dict[str, UserService],
    info: BridgeInfo | None,
    host: str,
    port: int,
    noise_psk: str | None,
) -> NodeIdentity:
    if info is not None:
        firmware = Firmware.BRIDGE
        buses = frozenset(
            bus for bus in info.buses if BUS_EXCHANGE_ACTION[bus] in services
        )
    elif legacy := {
        bus for action, bus in LEGACY_MANIFEST_ACTIONS.items() if action in services
    }:
        firmware = Firmware.LEGACY
        buses = frozenset(legacy)
    else:
        firmware = Firmware.OTHER
        buses = frozenset()
    return NodeIdentity(
        mac=normalize_mac(device_info.mac_address),
        name=device_info.name,
        friendly_name=device_info.friendly_name,
        host=host,
        port=port,
        noise_psk=noise_psk,
        project_name=device_info.project_name,
        project_version=device_info.project_version,
        esphome_version=device_info.esphome_version,
        firmware=firmware,
        buses=buses,
        info=info,
    )


async def async_open(
    host: str,
    port: int,
    noise_psk: str | None,
    *,
    expected_mac: str | None = None,
    zeroconf_instance: Any = None,
    on_stop: Callable[[bool], Coroutine[Any, Any, None]] | None = None,
) -> OpenConnection:
    """Connect to a node, read its identity and keep the connection open."""
    client = APIClient(
        host,
        port,
        None,
        client_info=CLIENT_INFO,
        noise_psk=noise_psk or None,
        expected_mac=_compact_mac(expected_mac) if expected_mac else None,
        zeroconf_instance=zeroconf_instance,
    )
    try:
        async with asyncio.timeout(CONNECT_TIMEOUT):
            await client.connect(on_stop=on_stop, login=True, log_errors=False)
            device_info = await client.device_info()
            _, service_list = await client.list_entities_services()
            services = {service.name: service for service in service_list}
            info = None
            if (info_service := services.get(ACTION_BRIDGE_INFO)) is not None:
                info = await async_read_info(client, info_service)
    except (
        InvalidEncryptionKeyAPIError,
        RequiresEncryptionAPIError,
        EncryptionPlaintextAPIError,
        InvalidAuthAPIError,
    ) as err:
        await client.disconnect(force=True)
        raise BridgeAuthError(str(err)) from err
    except BadMACAddressAPIError as err:
        await client.disconnect(force=True)
        raise BridgeWrongDeviceError(str(err)) from err
    except (APIConnectionError, TimeoutError, OSError) as err:
        await client.disconnect(force=True)
        raise BridgeConnectionError(str(err) or type(err).__name__) from err
    except BridgeActionError as err:
        await client.disconnect(force=True)
        raise BridgeConnectionError(str(err)) from err
    identity = _identify(device_info, services, info, host, port, noise_psk)
    return OpenConnection(client=client, identity=identity, services=services)


async def async_probe(
    host: str,
    port: int,
    noise_psk: str | None,
    *,
    expected_mac: str | None = None,
    zeroconf_instance: Any = None,
) -> NodeIdentity:
    """Connect to a node, read its identity and disconnect again."""
    connection = await async_open(
        host,
        port,
        noise_psk,
        expected_mac=expected_mac,
        zeroconf_instance=zeroconf_instance,
    )
    await connection.client.disconnect()
    return connection.identity
