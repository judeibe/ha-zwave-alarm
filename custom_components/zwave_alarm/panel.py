"""Registers the Z-Wave Alarm configuration panel (admin-only sidebar entry served from `frontend/`)."""

from __future__ import annotations

from pathlib import Path

from homeassistant.components import frontend, panel_custom
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant

from .const import DOMAIN

PANEL_URL_PATH = "zwave-alarm"
PANEL_ELEMENT = "zwave-alarm-panel"
STATIC_URL = f"/{DOMAIN}_static"
_FRONTEND_DIR = Path(__file__).parent / "frontend"
_STATIC_REGISTERED = f"{DOMAIN}_panel_static"
_PANEL_REGISTERED = f"{DOMAIN}_panel_registered"


async def async_register_panel(hass: HomeAssistant, *, show_in_sidebar: bool = True) -> None:
    """Serve the panel's JS and register it; `require_admin` hides it from, and blocks it for, non-admins."""
    if not hass.data.get(_STATIC_REGISTERED):
        await hass.http.async_register_static_paths([StaticPathConfig(STATIC_URL, str(_FRONTEND_DIR), False)])
        hass.data[_STATIC_REGISTERED] = True
    if hass.data.get(_PANEL_REGISTERED):
        return  # another config entry already registered it
    await panel_custom.async_register_panel(
        hass,
        webcomponent_name=PANEL_ELEMENT,
        frontend_url_path=PANEL_URL_PATH,
        module_url=f"{STATIC_URL}/{PANEL_ELEMENT}.js",
        sidebar_title="Z-Wave Alarm" if show_in_sidebar else None,
        sidebar_icon="mdi:shield-home" if show_in_sidebar else None,
        require_admin=True,
        config={},
    )
    hass.data[_PANEL_REGISTERED] = True


def async_remove_panel(hass: HomeAssistant) -> None:
    if hass.data.pop(_PANEL_REGISTERED, False):
        frontend.async_remove_panel(hass, PANEL_URL_PATH)
