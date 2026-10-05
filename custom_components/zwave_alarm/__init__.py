"""The Z-Wave Alarm integration (T035).

Consumes this repo's REST/WebSocket API (contracts/ha-custom-component.md) to
expose alarm-domain entities (panel, zones, fault count) to Home Assistant.
This is separate from the raw Z-Wave device entities, which Home Assistant's
own built-in "Z-Wave JS" integration gets directly from `zwave-js-server`
(T010/T033) -- no custom code needed for those (research.md section 6).

As of T039, a `ZwaveAlarmCoordinator` per config entry owns the persistent
WebSocket connection to `wss://<host>/api/v1/stream` and is stored in
`hass.data[DOMAIN]` alongside the platforms, which read it back in their own
`async_setup_entry` to build push-updated entities.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ACCESS_TOKEN, CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .const import CONF_SHOW_IN_SIDEBAR, CONF_SSL, DOMAIN
from .coordinator import ZwaveAlarmCoordinator
from .panel import async_register_panel, async_remove_panel
from .websocket_api import async_register_commands

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

PLATFORMS: list[str] = ["alarm_control_panel", "binary_sensor", "event", "sensor"]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the admin-only websocket commands used by the configuration panel."""
    async_register_commands(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Z-Wave Alarm from a config entry."""
    session = async_get_clientsession(hass)
    coordinator = ZwaveAlarmCoordinator(
        hass,
        entry,
        session,
        entry.data[CONF_HOST],
        entry.data[CONF_PORT],
        entry.data[CONF_ACCESS_TOKEN],
        entry.data.get(CONF_SSL, False),
    )
    coordinator.async_start(entry)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await async_register_panel(hass, show_in_sidebar=entry.options.get(CONF_SHOW_IN_SIDEBAR, True))
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    return True


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        coordinator: ZwaveAlarmCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.async_shutdown()
        if not hass.data[DOMAIN]:
            async_remove_panel(hass)

    return unload_ok
