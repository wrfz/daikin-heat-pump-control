"""Config flow for Daikin Heat Pump Control."""

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass, replace
from fnmatch import fnmatch
import logging
from typing import Any, override

import probatio

from homeassistant.components import zeroconf
from homeassistant.config_entries import (
    SOURCE_RECONFIGURE,
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo

from .bridge.client import (
    BridgeAuthError,
    BridgeConnectionError,
    Firmware,
    NodeIdentity,
    async_probe,
    normalize_mac,
)
from .bridge.resolve import esphome_entry_target
from .can.table import Group
from .const import (
    BUS_CONF,
    CONF_CAN_NODE,
    CONF_NODE_NAME,
    CONF_NODES,
    CONF_NOISE_PSK,
    CONF_OUTDOOR_UNIT,
    CONF_SCAN_INTERVAL,
    CONF_UART_NODE,
    CONF_UART_PROTOCOL,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    ESPHOME_CONF_NOISE_PSK,
    ESPHOME_DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
    OUTDOOR_UNITS,
    PROJECT_NAME_PATTERN,
    Bus,
    UartProtocol,
)
from .coordinator import group_option

_LOGGER = logging.getLogger(__name__)

TITLE = "Daikin Heat Pump"
NO_NODE = "none"
CONF_ADD_MANUAL = "add_manual"
KEEP = "keep"
USE_NEW = "use_new"
LEGACY_MARK = " *"


@dataclass(frozen=True, slots=True, kw_only=True)
class Candidate:
    """A node that can be assigned to a bus."""

    mac: str
    name: str
    title: str
    host: str
    port: int
    noise_psk: str | None
    buses: frozenset[Bus]
    firmware: Firmware | None

    @classmethod
    def from_identity(cls, identity: NodeIdentity) -> Candidate:
        """Build a candidate from a probed node."""
        return cls(
            mac=identity.mac,
            name=identity.name,
            title=identity.title,
            host=identity.host,
            port=identity.port,
            noise_psk=identity.noise_psk,
            buses=identity.buses,
            firmware=identity.firmware,
        )

    @property
    def label(self) -> str:
        """Return the label shown in the selection."""
        mark = LEGACY_MARK if self.firmware is Firmware.LEGACY else ""
        return f"{self.title} ({self.host}){mark}"

    def stored(self) -> dict[str, Any]:
        """Return the node as stored in the config entry."""
        return {
            CONF_HOST: self.host,
            CONF_PORT: self.port,
            CONF_NOISE_PSK: self.noise_psk,
            CONF_NODE_NAME: self.name,
        }


async def _async_zeroconf_for(hass: Any, host: str) -> Any:
    if host.endswith(".local"):
        return await zeroconf.async_get_async_instance(hass)
    return None


def _manual_schema(defaults: Mapping[str, Any]) -> probatio.Schema:
    return probatio.Schema(
        {
            probatio.Required(CONF_HOST, default=defaults.get(CONF_HOST, "")): str,
            probatio.Required(
                CONF_PORT, default=defaults.get(CONF_PORT, DEFAULT_PORT)
            ): probatio.All(probatio.Coerce(int), probatio.Range(min=1, max=65535)),
            probatio.Optional(
                CONF_NOISE_PSK, default=defaults.get(CONF_NOISE_PSK) or ""
            ): TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD)),
        }
    )


def _uart_schema(defaults: Mapping[str, Any]) -> probatio.Schema:
    outdoor = defaults.get(CONF_OUTDOOR_UNIT)
    return probatio.Schema(
        {
            probatio.Required(
                CONF_OUTDOOR_UNIT,
                default=outdoor if outdoor in OUTDOOR_UNITS else probatio.UNDEFINED,
            ): SelectSelector(
                SelectSelectorConfig(
                    options=list(OUTDOOR_UNITS), mode=SelectSelectorMode.DROPDOWN
                )
            ),
            probatio.Required(
                CONF_UART_PROTOCOL,
                default=defaults.get(CONF_UART_PROTOCOL, UartProtocol.AUTO),
            ): SelectSelector(
                SelectSelectorConfig(
                    options=[protocol.value for protocol in UartProtocol],
                    mode=SelectSelectorMode.DROPDOWN,
                    translation_key=CONF_UART_PROTOCOL,
                )
            ),
        }
    )


class DaikinConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Daikin Heat Pump Control."""

    VERSION = 1
    MINOR_VERSION = 1

    def __init__(self) -> None:
        """Initialize the flow."""
        self._candidates: dict[str, Candidate] = {}
        self._assignment: dict[Bus, str | None] = {Bus.CAN: None, Bus.UART: None}
        self._target: ConfigEntry | None = None
        self._search_empty = False
        self._discovered: Candidate | None = None
        self._reauth_macs: list[str] = []

    @staticmethod
    @callback
    @override
    def async_get_options_flow(config_entry: ConfigEntry) -> DaikinOptionsFlow:
        """Return the options flow."""
        return DaikinOptionsFlow()

    # ------------------------------------------------------------------ helpers

    def _existing_entry(self) -> ConfigEntry | None:
        entries = self._async_current_entries(include_ignore=False)
        return entries[0] if entries else None

    def _load_entry(self, entry: ConfigEntry) -> None:
        """Take the current assignment and nodes of an entry as starting point."""
        self._target = entry
        for bus, key in BUS_CONF.items():
            self._assignment[bus] = entry.data.get(key)
        for mac, node in entry.data.get(CONF_NODES, {}).items():
            buses = frozenset(
                bus for bus, key in BUS_CONF.items() if entry.data.get(key) == mac
            )
            self._candidates.setdefault(
                mac,
                Candidate(
                    mac=mac,
                    name=node.get(CONF_NODE_NAME, ""),
                    title=node.get(CONF_NODE_NAME) or mac,
                    host=node.get(CONF_HOST, ""),
                    port=int(node.get(CONF_PORT, DEFAULT_PORT)),
                    noise_psk=node.get(CONF_NOISE_PSK),
                    buses=buses,
                    firmware=None,
                ),
            )

    def _add_candidate(self, candidate: Candidate) -> None:
        current = self._candidates.get(candidate.mac)
        if current is not None and current.firmware is None:
            # An offline node of the entry keeps the buses it is assigned to.
            candidate = replace(candidate, buses=candidate.buses | current.buses)
        self._candidates[candidate.mac] = candidate

    async def _async_probe(
        self, host: str, port: int, noise_psk: str | None, mac: str | None = None
    ) -> NodeIdentity:
        return await async_probe(
            host,
            port,
            noise_psk,
            expected_mac=mac,
            zeroconf_instance=await _async_zeroconf_for(self.hass, host),
        )

    async def _async_search(self) -> None:
        """Probe the nodes of all ESPHome config entries."""
        targets: list[tuple[str, str, int, str | None]] = []
        for entry in self.hass.config_entries.async_entries(
            ESPHOME_DOMAIN, include_ignore=False
        ):
            host = entry.data.get(CONF_HOST)
            if not host or entry.unique_id is None:
                continue
            targets.append(
                (
                    normalize_mac(entry.unique_id),
                    host,
                    int(entry.data.get(CONF_PORT, DEFAULT_PORT)),
                    entry.data.get(ESPHOME_CONF_NOISE_PSK) or None,
                )
            )
        results = await asyncio.gather(
            *(
                self._async_probe(host, port, psk, mac)
                for mac, host, port, psk in targets
            ),
            return_exceptions=True,
        )
        found = False
        for (mac, host, _, _), result in zip(targets, results, strict=True):
            if isinstance(result, NodeIdentity):
                if result.firmware is not Firmware.OTHER:
                    self._add_candidate(Candidate.from_identity(result))
                    found = True
            else:
                _LOGGER.debug("Node %s (%s) not usable: %s", mac, host, result)
        self._search_empty = not found and not self._candidates

    def _bus_options(self, bus: Bus) -> list[SelectOptionDict]:
        options = [SelectOptionDict(value=NO_NODE, label="-")]
        options.extend(
            SelectOptionDict(value=c.mac, label=c.label)
            for c in self._candidates.values()
            if bus in c.buses
        )
        return options

    def _default_for(self, bus: Bus) -> str | None:
        if (current := self._assignment.get(bus)) is not None:
            return current
        offering = [c for c in self._candidates.values() if bus in c.buses]
        if len(offering) == 1:
            return offering[0].mac
        both = [c for c in offering if len(c.buses) == len(Bus)]
        if len(both) == 1:
            return both[0].mac
        return None

    # --------------------------------------------------------------- user flow

    @override
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Start the setup."""
        if self._existing_entry() is not None:
            return self.async_abort(reason="single_instance_allowed")
        return self.async_show_menu(step_id="user", menu_options=["search", "manual"])

    async def async_step_search(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Search the nodes known to the ESPHome integration."""
        await self._async_search()
        if self._search_empty:
            return await self.async_step_manual()
        return await self.async_step_assign()

    async def async_step_manual(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Add a node by host, port and key."""
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            port = int(user_input[CONF_PORT])
            noise_psk = user_input.get(CONF_NOISE_PSK) or None
            try:
                identity = await self._async_probe(host, port, noise_psk)
            except BridgeAuthError:
                errors["base"] = "invalid_auth"
            except BridgeConnectionError:
                errors["base"] = "cannot_connect"
            else:
                if identity.firmware is Firmware.OTHER:
                    errors["base"] = "not_daikin_node"
                else:
                    self._add_candidate(Candidate.from_identity(identity))
                    return await self.async_step_assign()
        elif self._search_empty:
            errors["base"] = "no_nodes_found"
        return self.async_show_form(
            step_id="manual",
            data_schema=_manual_schema(user_input or {}),
            errors=errors,
        )

    async def async_step_assign(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Assign a node to each bus."""
        errors: dict[str, str] = {}
        if user_input is not None:
            assignment = {
                bus: (
                    value
                    if (value := user_input.get(key, NO_NODE)) != NO_NODE
                    and value in self._candidates
                    else None
                )
                for bus, key in BUS_CONF.items()
            }
            self._assignment = assignment
            if user_input.get(CONF_ADD_MANUAL):
                return await self.async_step_manual()
            if all(mac is None for mac in assignment.values()):
                errors["base"] = "no_bus"
            else:
                return await self._async_after_assign()

        fields: dict[Any, Any] = {}
        for bus, key in BUS_CONF.items():
            options = self._bus_options(bus)
            if len(options) == 1:
                continue
            default = self._default_for(bus)
            fields[
                probatio.Required(key, default=default)
                if default
                else probatio.Required(key)
            ] = SelectSelector(
                SelectSelectorConfig(options=options, mode=SelectSelectorMode.DROPDOWN)
            )
        fields[probatio.Optional(CONF_ADD_MANUAL, default=False)] = bool
        return self.async_show_form(
            step_id="assign",
            data_schema=probatio.Schema(fields),
            errors=errors,
        )

    async def _async_after_assign(self) -> ConfigFlowResult:
        options = self._target.options if self._target else {}
        if self._assignment[Bus.UART] is not None and CONF_OUTDOOR_UNIT not in options:
            return await self.async_step_uart()
        return await self._async_finish({})

    async def async_step_uart(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Select outdoor unit and UART protocol."""
        if user_input is not None:
            return await self._async_finish(user_input)
        return self.async_show_form(step_id="uart", data_schema=_uart_schema({}))

    async def _async_finish(self, uart_options: dict[str, Any]) -> ConfigFlowResult:
        """Create or update the entry with the current assignment."""
        macs = {mac for mac in self._assignment.values() if mac is not None}
        data: dict[str, Any] = {
            CONF_NODES: {mac: self._candidates[mac].stored() for mac in sorted(macs)},
            CONF_CAN_NODE: self._assignment[Bus.CAN],
            CONF_UART_NODE: self._assignment[Bus.UART],
        }
        if (target := self._target) is None:
            await self.async_set_unique_id(DOMAIN, raise_on_progress=False)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(title=TITLE, data=data, options=uart_options)
        options = {**target.options, **uart_options}
        if self.source == SOURCE_RECONFIGURE:
            return self.async_update_reload_and_abort(
                target, data=data, options=options
            )
        return self.async_update_reload_and_abort(
            target, data=data, options=options, reason="node_assigned"
        )

    # --------------------------------------------------------------- zeroconf

    @override
    async def async_step_zeroconf(
        self, discovery_info: ZeroconfServiceInfo
    ) -> ConfigFlowResult:
        """Handle a bridge found via zeroconf."""
        properties = discovery_info.properties
        project_name = str(properties.get("project_name", "")).lower()
        mac_raw = str(properties.get("mac", ""))
        if not fnmatch(project_name, PROJECT_NAME_PATTERN) or not mac_raw:
            return self.async_abort(reason="not_daikin_bridge")
        mac = normalize_mac(mac_raw)
        host = discovery_info.host
        port = discovery_info.port or DEFAULT_PORT
        name = discovery_info.name.partition(".")[0]

        await self.async_set_unique_id(mac)
        if (entry := self._existing_entry()) is not None:
            nodes = entry.data.get(CONF_NODES, {})
            if mac in nodes:
                node = nodes[mac]
                if (node.get(CONF_HOST), node.get(CONF_PORT)) != (host, port):
                    self.hass.config_entries.async_update_entry(
                        entry,
                        data={
                            **entry.data,
                            CONF_NODES: {
                                **nodes,
                                mac: {**node, CONF_HOST: host, CONF_PORT: port},
                            },
                        },
                    )
                return self.async_abort(reason="already_configured")
            self._load_entry(entry)
        self._abort_if_unique_id_configured()

        noise_psk = None
        if (target := esphome_entry_target(self.hass, mac)) is not None:
            noise_psk = target.noise_psk
        self._discovered = Candidate(
            mac=mac,
            name=name,
            title=str(properties.get("friendly_name") or name),
            host=host,
            port=port,
            noise_psk=noise_psk,
            buses=frozenset(),
            firmware=None,
        )
        self.context["title_placeholders"] = {"name": self._discovered.title}
        if noise_psk is None and properties.get("api_encryption"):
            return await self.async_step_discovery_key()
        return await self._async_probe_discovered(None)

    async def _async_probe_discovered(self, noise_psk: str | None) -> ConfigFlowResult:
        assert self._discovered is not None
        discovered = self._discovered
        psk = noise_psk if noise_psk is not None else discovered.noise_psk
        try:
            identity = await self._async_probe(
                discovered.host, discovered.port, psk, discovered.mac
            )
        except BridgeAuthError:
            return await self.async_step_discovery_key(error="invalid_auth")
        except BridgeConnectionError:
            return self.async_abort(reason="cannot_connect")
        if identity.firmware is not Firmware.BRIDGE or not identity.buses:
            return self.async_abort(reason="not_daikin_bridge")
        self._discovered = Candidate.from_identity(identity)
        self._add_candidate(self._discovered)
        if self._target is not None:
            return await self.async_step_discovery_assign()
        return await self.async_step_discovery_confirm()

    async def async_step_discovery_key(
        self, user_input: dict[str, Any] | None = None, error: str | None = None
    ) -> ConfigFlowResult:
        """Ask for the API key of a discovered node."""
        if user_input is not None:
            return await self._async_probe_discovered(user_input[CONF_NOISE_PSK])
        assert self._discovered is not None
        return self.async_show_form(
            step_id="discovery_key",
            data_schema=probatio.Schema(
                {
                    probatio.Required(CONF_NOISE_PSK): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    )
                }
            ),
            description_placeholders={"name": self._discovered.title},
            errors={"base": error} if error else {},
        )

    async def async_step_discovery_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm setting up a discovered bridge."""
        assert self._discovered is not None
        discovered = self._discovered
        if user_input is not None:
            for bus in discovered.buses:
                self._assignment[bus] = discovered.mac
            return await self._async_after_assign()
        self._set_confirm_only()
        return self.async_show_form(
            step_id="discovery_confirm",
            description_placeholders={
                "name": discovered.title,
                "host": discovered.host,
                "buses": ", ".join(bus.upper() for bus in sorted(discovered.buses)),
            },
        )

    async def async_step_discovery_assign(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Assign a newly found bridge to buses of the existing entry."""
        assert self._discovered is not None and self._target is not None
        discovered = self._discovered
        buses = sorted(discovered.buses)
        if user_input is not None:
            changed = False
            for bus in buses:
                if user_input.get(BUS_CONF[bus]) == USE_NEW:
                    self._assignment[bus] = discovered.mac
                    changed = True
            if not changed:
                return self.async_abort(reason="no_changes")
            return await self._async_after_assign()

        def current(bus: Bus) -> str:
            mac = self._assignment.get(bus)
            if mac is None:
                return "-"
            return self._candidates[mac].title if mac in self._candidates else mac

        fields = {
            probatio.Required(BUS_CONF[bus], default=KEEP): SelectSelector(
                SelectSelectorConfig(
                    options=[KEEP, USE_NEW],
                    mode=SelectSelectorMode.LIST,
                    translation_key="discovery_assign",
                )
            )
            for bus in buses
        }
        return self.async_show_form(
            step_id="discovery_assign",
            data_schema=probatio.Schema(fields),
            description_placeholders={
                "name": discovered.title,
                "host": discovered.host,
                "can": current(Bus.CAN),
                "uart": current(Bus.UART),
            },
        )

    # ------------------------------------------------------------ reconfigure

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the node assignment."""
        self._load_entry(self._get_reconfigure_entry())
        return self.async_show_menu(
            step_id="reconfigure", menu_options=["search", "manual"]
        )

    # ----------------------------------------------------------------- reauth

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Handle a rejected API key."""
        entry = self._get_reauth_entry()
        self._load_entry(entry)
        self._reauth_macs = []
        nodes = dict(entry.data.get(CONF_NODES, {}))
        for mac, node in nodes.items():
            try:
                await self._async_probe(
                    node[CONF_HOST],
                    int(node.get(CONF_PORT, DEFAULT_PORT)),
                    node.get(CONF_NOISE_PSK),
                    mac,
                )
            except BridgeAuthError:
                target = esphome_entry_target(self.hass, mac)
                if target is not None and target.noise_psk != node.get(CONF_NOISE_PSK):
                    try:
                        await self._async_probe(
                            target.host, target.port, target.noise_psk, mac
                        )
                    except BridgeConnectionError, BridgeAuthError:
                        pass
                    else:
                        self._set_candidate_key(mac, target.noise_psk)
                        continue
                self._reauth_macs.append(mac)
            except BridgeConnectionError:
                continue
        if not self._reauth_macs:
            return self._async_finish_reauth()
        return await self.async_step_reauth_confirm()

    def _set_candidate_key(self, mac: str, noise_psk: str | None) -> None:
        self._candidates[mac] = replace(self._candidates[mac], noise_psk=noise_psk)

    @callback
    def _async_finish_reauth(self) -> ConfigFlowResult:
        assert self._target is not None
        nodes = {
            mac: {**node, CONF_NOISE_PSK: self._candidates[mac].noise_psk}
            for mac, node in self._target.data.get(CONF_NODES, {}).items()
        }
        return self.async_update_reload_and_abort(
            self._target, data={**self._target.data, CONF_NODES: nodes}
        )

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the new API key of a node."""
        mac = self._reauth_macs[0]
        candidate = self._candidates[mac]
        errors: dict[str, str] = {}
        if user_input is not None:
            noise_psk = user_input[CONF_NOISE_PSK]
            try:
                await self._async_probe(candidate.host, candidate.port, noise_psk, mac)
            except BridgeAuthError:
                errors["base"] = "invalid_auth"
            except BridgeConnectionError:
                errors["base"] = "cannot_connect"
            else:
                self._set_candidate_key(mac, noise_psk)
                self._reauth_macs.pop(0)
                if not self._reauth_macs:
                    return self._async_finish_reauth()
                return await self.async_step_reauth_confirm()
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=probatio.Schema(
                {
                    probatio.Required(CONF_NOISE_PSK): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    )
                }
            ),
            description_placeholders={"name": candidate.title, "host": candidate.host},
            errors=errors,
        )


def _interval_selector() -> NumberSelector:
    return NumberSelector(
        NumberSelectorConfig(
            min=MIN_SCAN_INTERVAL,
            max=MAX_SCAN_INTERVAL,
            step=1,
            mode=NumberSelectorMode.BOX,
            unit_of_measurement="s",
        )
    )


def _interval_schema(options: Mapping[str, Any]) -> dict[Any, Any]:
    fields: dict[Any, Any] = {
        probatio.Required(
            CONF_SCAN_INTERVAL,
            default=options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
        ): _interval_selector()
    }
    for group in Group:
        key = group_option(group)
        fields[
            probatio.Optional(key, description={"suggested_value": options.get(key)})
        ] = _interval_selector()
    return fields


class DaikinOptionsFlow(OptionsFlowWithReload):
    """Options of the integration."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the options."""
        options = self.config_entry.options
        data = self.config_entry.data
        if user_input is not None:
            group_keys = {group_option(group) for group in Group}
            kept = {k: v for k, v in options.items() if k not in group_keys}
            return self.async_create_entry(data={**kept, **user_input})
        fields: dict[Any, Any] = {}
        if data.get(CONF_CAN_NODE) is not None:
            fields.update(_interval_schema(options))
        if data.get(CONF_UART_NODE) is not None:
            fields.update(_uart_schema(options).schema)
        return self.async_show_form(step_id="init", data_schema=probatio.Schema(fields))
