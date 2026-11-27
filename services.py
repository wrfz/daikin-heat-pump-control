"""Services of the Daikin Heat Pump Control integration."""

from typing import Final

import probatio

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv

from .can.protocol import FRAME_LENGTH, OWN_ID
from .const import ATTR_CONFIG_ENTRY_ID, ATTR_DATA, DOMAIN, SERVICE_SEND_RAW_CAN
from .coordinator import CanCoordinator
from .runtime import DaikinConfigEntry

SEND_RAW_CAN_SCHEMA: Final = probatio.Schema(
    {
        probatio.Required(ATTR_DATA): cv.string,
        probatio.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
    }
)


def parse_raw_frame(text: str) -> bytes:
    """Return the bytes of a frame written as hex, e.g. `31 00 FA C0 FC`.

    Bytes may be separated by spaces or commas and carry a `0x` prefix; a
    single token may hold several bytes. Raises ValueError for anything else.
    """
    tokens = text.replace(",", " ").split()
    parts: list[str] = []
    for token in tokens:
        part = token[2:] if token[:2].lower() == "0x" else token
        if not part or len(part) % 2:
            raise ValueError(text)
        parts.append(part)
    data = bytes.fromhex("".join(parts))
    if not 1 <= len(data) <= FRAME_LENGTH:
        raise ValueError(text)
    return data


def _coordinator(hass: HomeAssistant, call: ServiceCall) -> CanCoordinator:
    entry: DaikinConfigEntry | None
    if (entry_id := call.data.get(ATTR_CONFIG_ENTRY_ID)) is not None:
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry is None or entry.domain != DOMAIN:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="entry_not_found",
                translation_placeholders={"entry_id": entry_id},
            )
    else:
        entries = hass.config_entries.async_loaded_entries(DOMAIN)
        entry = entries[0] if entries else None
        if entry is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="entry_not_loaded"
            )
    if entry.state is not ConfigEntryState.LOADED:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="entry_not_loaded"
        )
    if (coordinator := entry.runtime_data.can) is None:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="no_can_bus"
        )
    return coordinator


async def _async_send_raw_can(call: ServiceCall) -> ServiceResponse:
    try:
        data = parse_raw_frame(call.data[ATTR_DATA])
    except ValueError as err:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="invalid_raw_frame",
            translation_placeholders={"data": call.data[ATTR_DATA]},
        ) from err
    coordinator = _coordinator(call.hass, call)
    answer = await coordinator.async_send_raw(data)
    return {
        "sent": f"{OWN_ID:03X}#{data.hex().upper()}",
        "answer": None
        if answer is None
        else {"can_id": f"{answer.can_id:03X}", "data": answer.data.hex().upper()},
    }


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register the services."""
    hass.services.async_register(
        DOMAIN,
        SERVICE_SEND_RAW_CAN,
        _async_send_raw_can,
        schema=SEND_RAW_CAN_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
