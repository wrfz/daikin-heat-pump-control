"""Connection to one bridge node and the exchange cycle of its buses."""

from collections import deque
from collections.abc import Callable
from datetime import datetime, timedelta
from enum import StrEnum
import logging
from typing import TYPE_CHECKING, Any, override

from aioesphomeapi import APIClient, UserService

from homeassistant.core import CALLBACK_TYPE, HassJob, HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.event import async_call_later, async_track_time_interval
from homeassistant.util import dt as dt_util

from ..const import (
    ACTION_BRIDGE_INFO,
    BUS_EXCHANGE_ACTION,
    DOMAIN,
    EXCHANGE_INTERVAL,
    INFO_INTERVAL,
    ISSUE_NO_BRIDGE_FIRMWARE,
    RECONNECT_MAX_DELAY,
    RECONNECT_MIN_DELAY,
    Bus,
)
from .client import (
    BridgeActionError,
    BridgeAuthError,
    BridgeConnectionError,
    BridgeWrongDeviceError,
    Firmware,
    NodeIdentity,
    async_execute,
    async_open,
    async_read_info,
)
from .protocol import (
    BridgeInfo,
    BridgeProtocolError,
    CanExchangeResult,
    CanFrame,
    EspClock,
    UartExchangeResult,
    parse_can_exchange,
    parse_uart_exchange,
)
from .resolve import Target, async_targets

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

_LOGGER = logging.getLogger(__name__)

RAW_HISTORY = 50
BOOT_TIME_TOLERANCE = timedelta(seconds=30)
CAN_TX_QUEUE = 16


class NodeState(StrEnum):
    """Connection state of a node."""

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    AUTH_FAILED = "auth_failed"
    STOPPED = "stopped"


class BusChannel:
    """Exchange of one bus over its bridge node."""

    bus: Bus

    def __init__(self, node: BridgeNode) -> None:
        """Initialize the channel."""
        self.node = node
        self.clock = EspClock()
        self.history: deque[dict[str, Any]] = deque(maxlen=RAW_HISTORY)
        self.exchanges = 0
        self.errors = 0
        self.overflows = 0
        self._in_flight = False
        self._again = False
        self._more = False
        self._listeners: list[Callable[[Any], None]] = []

    @property
    def available(self) -> bool:
        """Return True while the bus can be used."""
        return self.node.bridge_ready and self.bus in self.node.bridge_buses

    @callback
    def async_add_listener(self, listener: Callable[[Any], None]) -> CALLBACK_TYPE:
        """Register a listener for exchange results."""
        self._listeners.append(listener)

        @callback
        def _remove() -> None:
            self._listeners.remove(listener)

        return _remove

    def has_pending(self) -> bool:
        """Return True if data waits to be handed to the bridge."""
        raise NotImplementedError

    def build_request(self) -> dict[str, Any]:
        """Return the action arguments and take the pending data."""
        raise NotImplementedError

    def handle_response(self, data: bytes) -> Any:
        """Parse and record a response; return the result for the listeners."""
        raise NotImplementedError

    def reset(self) -> None:
        """Drop pending data after the connection was lost."""
        self.clock.reset()
        self._in_flight = False
        self._again = False
        self._more = False

    @callback
    def async_request_exchange(self) -> None:
        """Exchange as soon as possible."""
        if self._in_flight:
            self._again = True
            return
        self.node.async_start_exchange(self)

    async def async_exchange(self, client: APIClient, service: UserService) -> None:
        """Run one exchange with the bridge."""
        if self._in_flight:
            self._again = True
            return
        self._in_flight = True
        try:
            while True:
                self._again = False
                request = self.build_request()
                try:
                    data = await async_execute(client, service, request)
                    result = self.handle_response(data)
                except (BridgeActionError, BridgeProtocolError) as err:
                    self.errors += 1
                    _LOGGER.debug(
                        "%s: %s exchange failed: %s", self.node.title, self.bus, err
                    )
                    return
                self.exchanges += 1
                for listener in list(self._listeners):
                    listener(result)
                if (
                    not (self._again or self._more or self.has_pending())
                    or not self.available
                ):
                    return
        finally:
            self._in_flight = False


class CanChannel(BusChannel):
    """CAN exchange."""

    bus = Bus.CAN

    def __init__(self, node: BridgeNode) -> None:
        """Initialize the channel."""
        super().__init__(node)
        self._queue: list[CanFrame] = []
        self._bridge_free = CAN_TX_QUEUE

    @override
    def has_pending(self) -> bool:
        """Return True if frames wait and the bridge has room for them."""
        return bool(self._queue) and self._bridge_free > 0

    @callback
    def async_send(self, frames: list[CanFrame]) -> None:
        """Queue frames for the bridge and exchange right away."""
        self._queue.extend(frames)
        self.async_request_exchange()

    @override
    def build_request(self) -> dict[str, Any]:
        """Take as many frames as the send queue of the bridge has room for."""
        count = max(self._bridge_free, 0)
        frames, self._queue = self._queue[:count], self._queue[count:]
        self._bridge_free -= len(frames)
        return {"frames": [frame.encode() for frame in frames]}

    @override
    def handle_response(self, data: bytes) -> CanExchangeResult:
        """Parse a CAN exchange response."""
        result = parse_can_exchange(data)
        self.clock.extend(result.now)
        self.overflows = result.overflows
        self._bridge_free = CAN_TX_QUEUE - result.pending
        self._more = result.more
        if result.received or result.sent:
            self.history.append(
                {
                    "now": result.now,
                    "rx": [[f.timestamp, f.frame.encode()] for f in result.received],
                    "tx": [[f.timestamp, f.frame.encode()] for f in result.sent],
                }
            )
        return result

    @override
    def reset(self) -> None:
        """Drop queued frames."""
        if self._queue:
            _LOGGER.warning(
                "%s: dropped %d CAN frames because the connection was lost",
                self.node.title,
                len(self._queue),
            )
        self._queue.clear()
        self._bridge_free = CAN_TX_QUEUE
        super().reset()


class UartChannel(BusChannel):
    """UART exchange."""

    bus = Bus.UART

    def __init__(self, node: BridgeNode) -> None:
        """Initialize the channel."""
        super().__init__(node)
        self._pending = b""

    @override
    def has_pending(self) -> bool:
        """Return True if bytes wait to be handed to the bridge."""
        return bool(self._pending)

    @callback
    def async_send(self, data: bytes) -> None:
        """Queue bytes for the bridge and exchange right away."""
        self._pending += data
        self.async_request_exchange()

    @override
    def build_request(self) -> dict[str, Any]:
        """Take the pending bytes."""
        data, self._pending = self._pending, b""
        return {"data": data.hex().upper()}

    @override
    def handle_response(self, data: bytes) -> UartExchangeResult:
        """Parse a UART exchange response."""
        result = parse_uart_exchange(data)
        self.clock.extend(result.now)
        self.overflows = result.overflows
        if result.received:
            self.history.append(
                {"t": result.received_at, "rx": result.received.hex().upper()}
            )
        return result

    @override
    def reset(self) -> None:
        """Drop pending bytes."""
        self._pending = b""
        super().reset()


CHANNEL_TYPES: dict[Bus, type[BusChannel]] = {
    Bus.CAN: CanChannel,
    Bus.UART: UartChannel,
}


class BridgeNode:
    """Connection to one ESP node running the bridge firmware."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        *,
        mac: str,
        name: str,
        host: str,
        port: int,
        noise_psk: str | None,
        buses: frozenset[Bus],
    ) -> None:
        """Initialize the node."""
        self.hass = hass
        self.entry = entry
        self.mac = mac
        self.name = name
        self.host = host
        self.port = port
        self.noise_psk = noise_psk
        self.assigned_buses = buses
        self.channels: dict[Bus, BusChannel] = {
            bus: CHANNEL_TYPES[bus](self) for bus in sorted(buses)
        }
        self.state = NodeState.DISCONNECTED
        self.identity: NodeIdentity | None = None
        self.info: BridgeInfo | None = None
        self.boot_time: datetime | None = None
        self.connected_target: Target | None = None
        self.last_error: str | None = None
        self.connect_count = 0
        self._client: APIClient | None = None
        self._services: dict[str, UserService] = {}
        self._listeners: list[CALLBACK_TYPE] = []
        self._unsub_timers: list[CALLBACK_TYPE] = []
        self._unsub_reconnect: CALLBACK_TYPE | None = None
        self._reconnect_delay = RECONNECT_MIN_DELAY
        self._was_connected = False
        self._logged_unavailable = False
        self._missing_buses_logged: frozenset[Bus] = frozenset()
        self._generation = 0
        self._connected_generation: int | None = None

    @property
    def title(self) -> str:
        """Return the node name for logs."""
        return self.name or self.mac

    @property
    def connected(self) -> bool:
        """Return True while the API connection is up."""
        return self.state is NodeState.CONNECTED

    @property
    def firmware(self) -> Firmware | None:
        """Return the firmware found on the last connection."""
        return self.identity.firmware if self.identity else None

    @property
    def bridge_ready(self) -> bool:
        """Return True while connected to the bridge firmware."""
        return self.connected and self.firmware is Firmware.BRIDGE

    @property
    def bridge_buses(self) -> frozenset[Bus]:
        """Return the assigned buses the bridge currently offers."""
        if self.identity is None:
            return frozenset()
        return self.identity.buses & self.assigned_buses

    @property
    def issue_id(self) -> str:
        """Return the repair issue id of this node."""
        return f"{ISSUE_NO_BRIDGE_FIRMWARE}_{self.mac.replace(':', '')}"

    @callback
    def async_add_listener(self, listener: CALLBACK_TYPE) -> CALLBACK_TYPE:
        """Register a listener for state and info changes."""
        self._listeners.append(listener)

        @callback
        def _remove() -> None:
            self._listeners.remove(listener)

        return _remove

    @callback
    def _notify(self) -> None:
        for listener in list(self._listeners):
            listener()

    async def async_connect(self) -> None:
        """Connect once; raise BridgeAuthError or BridgeConnectionError on failure."""
        if self.state in (NodeState.CONNECTED, NodeState.CONNECTING):
            return
        self.state = NodeState.CONNECTING
        try:
            await self._async_connect_targets()
        except BridgeAuthError as err:
            self.state = NodeState.AUTH_FAILED
            self.last_error = str(err)
            self._notify()
            raise
        except BridgeConnectionError as err:
            self.state = NodeState.DISCONNECTED
            self.last_error = str(err)
            self._notify()
            raise

    async def _async_connect_targets(self) -> None:
        targets = await async_targets(
            self.hass,
            mac=self.mac,
            name=self.name,
            host=self.host,
            port=self.port,
            noise_psk=self.noise_psk,
        )
        auth_error: BridgeAuthError | None = None
        last_error: BridgeConnectionError | None = None
        for target in targets:
            self._generation += 1
            generation = self._generation

            async def _on_stop(
                expected_disconnect: bool, generation: int = generation
            ) -> None:
                await self._async_on_stop(generation, expected_disconnect)

            try:
                connection = await async_open(
                    target.host,
                    target.port,
                    target.noise_psk,
                    expected_mac=self.mac,
                    on_stop=_on_stop,
                )
            except BridgeAuthError as err:
                auth_error = err
                continue
            except BridgeWrongDeviceError as err:
                last_error = err
                continue
            except BridgeConnectionError as err:
                last_error = err
                continue
            self._connected_generation = generation
            self._async_on_connected(
                target, connection.client, connection.identity, connection.services
            )
            return
        if auth_error is not None and last_error is None:
            raise auth_error
        if last_error is not None:
            raise last_error
        raise BridgeConnectionError("No address to connect to")  # pragma: no cover

    @callback
    def _async_on_connected(
        self,
        target: Target,
        client: APIClient,
        identity: NodeIdentity,
        services: dict[str, UserService],
    ) -> None:
        self._client = client
        self._services = services
        self.identity = identity
        self._async_set_info(identity.info)
        self.connected_target = target
        self.state = NodeState.CONNECTED
        self.last_error = None
        self.connect_count += 1
        self._reconnect_delay = RECONNECT_MIN_DELAY
        if self._logged_unavailable:
            _LOGGER.info("Bridge %s is available again", self.title)
            self._logged_unavailable = False
        self._was_connected = True
        self._async_store_target(target)
        self._async_check_firmware()
        if self.bridge_ready:
            self._unsub_timers.append(
                async_track_time_interval(
                    self.hass,
                    self._async_exchange_tick,
                    timedelta(seconds=EXCHANGE_INTERVAL),
                    name=f"{DOMAIN} exchange {self.title}",
                    cancel_on_shutdown=True,
                )
            )
            self._unsub_timers.append(
                async_track_time_interval(
                    self.hass,
                    self._async_info_tick,
                    timedelta(seconds=INFO_INTERVAL),
                    name=f"{DOMAIN} info {self.title}",
                    cancel_on_shutdown=True,
                )
            )
        self._notify()

    @callback
    def _async_store_target(self, target: Target) -> None:
        """Remember the address and key that worked."""
        if (target.host, target.port, target.noise_psk) == (
            self.host,
            self.port,
            self.noise_psk,
        ):
            return
        self.host, self.port, self.noise_psk = (
            target.host,
            target.port,
            target.noise_psk,
        )
        nodes = dict(self.entry.data.get("nodes", {}))
        if self.mac in nodes:
            nodes[self.mac] = {
                **nodes[self.mac],
                "host": target.host,
                "port": target.port,
                "noise_psk": target.noise_psk,
            }
            self.hass.config_entries.async_update_entry(
                self.entry, data={**self.entry.data, "nodes": nodes}
            )

    @callback
    def _async_check_firmware(self) -> None:
        identity = self.identity
        assert identity is not None
        if identity.firmware is Firmware.BRIDGE:
            ir.async_delete_issue(self.hass, DOMAIN, self.issue_id)
            missing = self.assigned_buses - identity.buses
            if missing and missing != self._missing_buses_logged:
                _LOGGER.warning(
                    "Bridge %s does not offer the assigned bus(es) %s",
                    self.title,
                    ", ".join(sorted(missing)),
                )
            self._missing_buses_logged = missing
            return
        _LOGGER.warning(
            "Node %s does not run the bridge firmware; its buses stay unavailable",
            self.title,
        )
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            self.issue_id,
            is_fixable=False,
            is_persistent=False,
            severity=ir.IssueSeverity.ERROR,
            translation_key=ISSUE_NO_BRIDGE_FIRMWARE,
            translation_placeholders={"name": identity.title, "host": identity.host},
        )

    async def _async_on_stop(self, generation: int, expected_disconnect: bool) -> None:
        """Handle the end of the connection."""
        if generation != self._connected_generation:
            return
        self._connected_generation = None
        self._async_cancel_timers()
        self._client = None
        self._services = {}
        for channel in self.channels.values():
            channel.reset()
        if self.state is NodeState.STOPPED:
            return
        self.state = NodeState.DISCONNECTED
        if not self._logged_unavailable:
            _LOGGER.warning("Lost connection to bridge %s", self.title)
            self._logged_unavailable = True
        self._notify()
        self._async_schedule_reconnect()

    @callback
    def async_start(self) -> None:
        """Keep the node connected; reconnect after failures."""
        if self.state is NodeState.STOPPED:
            self.state = NodeState.DISCONNECTED
        if self.state is NodeState.DISCONNECTED and self._unsub_reconnect is None:
            self._async_schedule_reconnect(0)

    @callback
    def _async_schedule_reconnect(self, delay: float | None = None) -> None:
        if self._unsub_reconnect is not None:
            self._unsub_reconnect()
        if delay is None:
            delay = self._reconnect_delay
            self._reconnect_delay = min(self._reconnect_delay * 2, RECONNECT_MAX_DELAY)
        self._unsub_reconnect = async_call_later(
            self.hass,
            delay,
            HassJob(
                self._async_reconnect,
                f"{DOMAIN} reconnect {self.title}",
                cancel_on_shutdown=True,
            ),
        )

    async def _async_reconnect(self, _now: Any) -> None:
        self._unsub_reconnect = None
        if self.state is not NodeState.DISCONNECTED:
            return
        try:
            await self.async_connect()
        except BridgeAuthError:
            _LOGGER.error("Bridge %s rejected the API encryption key", self.title)
            self.entry.async_start_reauth(self.hass)
        except BridgeConnectionError as err:
            if not self._logged_unavailable:
                _LOGGER.warning("Bridge %s is not reachable: %s", self.title, err)
                self._logged_unavailable = True
            else:
                _LOGGER.debug("Bridge %s is still not reachable: %s", self.title, err)
            self._async_schedule_reconnect()

    @callback
    def _async_cancel_timers(self) -> None:
        for unsub in self._unsub_timers:
            unsub()
        self._unsub_timers.clear()

    async def async_stop(self) -> None:
        """Disconnect and stop reconnecting."""
        was_connected = self.state is NodeState.CONNECTED
        self.state = NodeState.STOPPED
        if self._unsub_reconnect is not None:
            self._unsub_reconnect()
            self._unsub_reconnect = None
        self._async_cancel_timers()
        if (client := self._client) is not None:
            self._client = None
            await client.disconnect(force=not was_connected)

    @callback
    def _async_exchange_tick(self, _now: Any) -> None:
        for channel in self.channels.values():
            if channel.available:
                self.async_start_exchange(channel)

    @callback
    def async_start_exchange(self, channel: BusChannel) -> None:
        """Start an exchange of a channel in a task."""
        client = self._client
        service = self._services.get(BUS_EXCHANGE_ACTION[channel.bus])
        if client is None or service is None or not channel.available:
            return
        self.entry.async_create_task(
            self.hass,
            channel.async_exchange(client, service),
            f"{DOMAIN} {channel.bus} exchange {self.title}",
            eager_start=True,
        )

    @callback
    def _async_info_tick(self, _now: Any) -> None:
        self.entry.async_create_task(
            self.hass, self.async_refresh_info(), f"{DOMAIN} info {self.title}"
        )

    async def async_refresh_info(self) -> None:
        """Read the diagnostic values of the bridge."""
        client = self._client
        service = self._services.get(ACTION_BRIDGE_INFO)
        if client is None or service is None:
            return
        try:
            info = await async_read_info(client, service)
        except BridgeActionError as err:
            _LOGGER.debug("%s: reading bridge info failed: %s", self.title, err)
            return
        self._async_set_info(info)
        self._notify()

    @callback
    def _async_set_info(self, info: BridgeInfo | None) -> None:
        """Store bridge info and derive the boot time from the uptime."""
        self.info = info
        if info is None:
            return
        boot_time = dt_util.utcnow().replace(microsecond=0) - timedelta(
            seconds=info.uptime
        )
        if (
            self.boot_time is None
            or abs(boot_time - self.boot_time) > BOOT_TIME_TOLERANCE
        ):
            self.boot_time = boot_time
