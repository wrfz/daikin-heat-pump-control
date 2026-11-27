"""Frontend module, card and sidebar panel."""

from pathlib import Path
from typing import Any, Final

import probatio

from homeassistant.components import frontend, panel_custom
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_integration

from .const import (
    CONF_SHOW_PANEL,
    DOMAIN,
    FRONTEND_MODULE,
    FRONTEND_URL,
    PANEL_ELEMENT,
    PANEL_ICON,
    PANEL_URL_PATH,
)
from .runtime import DaikinConfigEntry

FRONTEND_DIR: Final = Path(__file__).parent / "frontend"

# Sidebar titles by system language; Home Assistant does not translate the
# title of a custom panel per user.
PANEL_TITLES: Final[dict[str, str]] = {
    "de": "Wärmepumpe",
    "en": "Heat pump",
    "fr": "Pompe à chaleur",
    "it": "Pompa di calore",
}

LAYOUTS: Final = ("auto", "light", "dark", "petrol")

_COLOR = probatio.All(
    [probatio.All(int, probatio.Range(min=0, max=255))],
    probatio.Length(min=3, max=3),
)
_PERCENT = probatio.All(probatio.Coerce(float), probatio.Range(min=0, max=100))

# Appearance of the dashboard, shared by the card configuration and the panel.
APPEARANCE_SCHEMA: Final = probatio.Schema(
    {
        probatio.Optional("layout"): probatio.In(LAYOUTS),
        probatio.Optional("animations"): bool,
        probatio.Optional("background"): {
            probatio.Optional("show"): bool,
            probatio.Optional("color"): _COLOR,
            probatio.Optional("opacity"): _PERCENT,
        },
        probatio.Optional("box"): {
            probatio.Optional("fill"): _COLOR,
            probatio.Optional("fill_opacity"): _PERCENT,
            probatio.Optional("border"): _COLOR,
            probatio.Optional("border_opacity"): _PERCENT,
        },
        probatio.Optional("text"): {
            probatio.Optional("value_color"): _COLOR,
            probatio.Optional("label_color"): _COLOR,
        },
    }
)


def panel_title(language: str) -> str:
    """Return the sidebar title for a language such as `de` or `de-CH`."""
    return PANEL_TITLES.get(
        language.split("-", maxsplit=1)[0].lower(), PANEL_TITLES["en"]
    )


async def async_setup_frontend(hass: HomeAssistant) -> None:
    """Serve the frontend files and load the module on every page."""
    integration = await async_get_integration(hass, DOMAIN)
    await hass.http.async_register_static_paths(
        [StaticPathConfig(FRONTEND_URL, str(FRONTEND_DIR), cache_headers=True)]
    )
    frontend.add_extra_js_url(
        hass, f"{FRONTEND_URL}/{FRONTEND_MODULE}?v={integration.version}"
    )


async def async_register_panel(hass: HomeAssistant, entry: DaikinConfigEntry) -> None:
    """Add the panel to the sidebar unless it is switched off."""
    if not entry.options.get(CONF_SHOW_PANEL, True):
        return
    integration = await async_get_integration(hass, DOMAIN)
    config: dict[str, Any] = {"entry_id": entry.entry_id}
    await panel_custom.async_register_panel(
        hass,
        frontend_url_path=PANEL_URL_PATH,
        webcomponent_name=PANEL_ELEMENT,
        sidebar_title=panel_title(hass.config.language),
        sidebar_icon=PANEL_ICON,
        module_url=f"{FRONTEND_URL}/{FRONTEND_MODULE}?v={integration.version}",
        config=config,
        require_admin=False,
    )

    def _remove() -> None:
        frontend.async_remove_panel(hass, PANEL_URL_PATH, warn_if_unknown=False)

    entry.async_on_unload(_remove)
