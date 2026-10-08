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

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_DEVICE_ID, ATTR_ENTITY_ID, CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .const import CAPABILITY_CHIME, CONF_SHOW_IN_SIDEBAR, CONF_SSL, DOMAIN
from .coordinator import ZwaveAlarmCoordinator
from .keypad import keypad_device_identifier
from .panel import async_register_panel, async_remove_panel
from .websocket_api import async_register_commands

PLATFORMS: list[str] = ["alarm_control_panel", "binary_sensor", "event", "sensor"]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

SERVICE_KEYPAD_CHIME = "keypad_chime"
ATTR_SOUND = "sound"
ATTR_VOLUME = "volume"
KEYPAD_CHIME_SCHEMA = cv.make_entity_service_schema(
    {
        vol.Required(ATTR_SOUND): cv.string,
        vol.Optional(ATTR_VOLUME): vol.All(vol.Coerce(int), vol.Range(min=0, max=99)),
    }
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the domain-wide services (they must exist whether or not an entry is loaded)."""

    async def _keypad_chime(call: ServiceCall) -> None:
        # Targets are a keypad's device, or any of its entities (area/label targets aren't resolved).
        entity_registry = er.async_get(hass)
        device_ids = set(cv.ensure_list(call.data.get(ATTR_DEVICE_ID)))
        for entity_id in cv.ensure_list(call.data.get(ATTR_ENTITY_ID)):
            if (entity := entity_registry.async_get(entity_id)) is not None and entity.device_id:
                device_ids.add(entity.device_id)

        targets = []
        device_registry = dr.async_get(hass)
        for device_id in sorted(device_ids):
            device = device_registry.async_get(device_id)
            if device is None:
                continue
            for coordinator in _coordinators(hass):
                for keypad in coordinator.data.keypads if coordinator.data else []:
                    if keypad_device_identifier(coordinator.config_entry.entry_id, keypad["nodeId"]) in device.identifiers:
                        targets.append((coordinator, keypad))
        if not targets:
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="keypad_not_found")

        sound = call.data[ATTR_SOUND]
        # Validate every target before sending anything, so a bad one doesn't leave a partial chime.
        for _, keypad in targets:
            name = keypad.get("label") or f"Keypad {keypad['nodeId']}"
            if CAPABILITY_CHIME not in keypad.get("capabilities", []):
                raise ServiceValidationError(
                    translation_domain=DOMAIN, translation_key="chime_unsupported", translation_placeholders={"keypad": name}
                )
            if sound not in keypad.get("chimeSounds", []):
                raise ServiceValidationError(
                    translation_domain=DOMAIN,
                    translation_key="chime_sound_unsupported",
                    translation_placeholders={"keypad": name, "sound": sound},
                )
        for coordinator, keypad in targets:
            await coordinator.async_chime_keypad(keypad["nodeId"], sound, call.data.get(ATTR_VOLUME))

    hass.services.async_register(DOMAIN, SERVICE_KEYPAD_CHIME, _keypad_chime, schema=KEYPAD_CHIME_SCHEMA)
    async_register_commands(hass)  # admin-only websocket API for the configuration panel
    return True


def _coordinators(hass: HomeAssistant) -> list[ZwaveAlarmCoordinator]:
    return list(hass.data.get(DOMAIN, {}).values())


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Drop the API token stored by v1 entries: the service no longer needs authentication."""
    if entry.version == 1:
        data = {k: v for k, v in entry.data.items() if k != "access_token"}
        hass.config_entries.async_update_entry(entry, data=data, version=2)
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
