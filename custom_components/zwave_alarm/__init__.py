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

from collections.abc import Callable
from typing import Any

import voluptuous as vol
import zwave_alarm_client as api
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_DEVICE_ID, ATTR_ENTITY_ID, CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .const import CAPABILITY_CHIME, CONF_SHOW_IN_SIDEBAR, CONF_SSL, DOMAIN
from .coordinator import ZwaveAlarmCoordinator
from .keypad import keypad_device_identifier
from .lock_state import (
    CLIENT_SCHEDULE_KINDS,
    SCHEDULE_KINDS,
    WEEKDAYS,
    schedule_from_service,
    schedule_slot_count,
)
from .panel import async_register_panel, async_remove_panel
from .schlage import async_can_remove_lock_device, async_setup_lock_lifecycle, lock_device_identifier
from .websocket_api import async_register_commands

PLATFORMS: list[str] = ["alarm_control_panel", "binary_sensor", "event", "lock", "number", "select", "sensor", "switch"]

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

SERVICE_SET_LOCK_SCHEDULE = "set_lock_schedule"
SERVICE_CLEAR_LOCK_SCHEDULE = "clear_lock_schedule"
SERVICE_SET_LOCK_SCHEDULES_ENABLED = "set_lock_schedules_enabled"
SERVICE_GET_LOCK_SCHEDULE = "get_lock_schedule"
ATTR_USER_ID = "user_id"
ATTR_SLOT = "slot"
ATTR_SCHEDULE_TYPE = "schedule_type"
ATTR_ENABLED = "enabled"
_USER_ID = vol.All(vol.Coerce(int), vol.Range(min=1, max=30))  # the lock has 30 user slots
_SLOT = vol.All(vol.Coerce(int), vol.Range(min=1, max=255))
_SCHEDULE_TYPE = vol.In(SCHEDULE_KINDS)
_DEVICE_TARGET = {vol.Required(ATTR_DEVICE_ID): vol.All(cv.ensure_list, [cv.string])}
SET_LOCK_SCHEDULE_SCHEMA = vol.Schema(
    {
        **_DEVICE_TARGET,
        vol.Required(ATTR_USER_ID): _USER_ID,
        vol.Required(ATTR_SLOT): _SLOT,
        vol.Required(ATTR_SCHEDULE_TYPE): _SCHEDULE_TYPE,
        vol.Optional("weekday"): vol.In(WEEKDAYS),
        vol.Optional("weekdays"): vol.All(cv.ensure_list, [vol.In(WEEKDAYS)]),
        vol.Optional("start_time"): cv.time,
        vol.Optional("end_time"): cv.time,
        vol.Optional("start"): cv.datetime,
        vol.Optional("end"): cv.datetime,
        vol.Optional("duration"): cv.positive_time_period,
    }
)
CLEAR_LOCK_SCHEDULE_SCHEMA = vol.Schema(
    {**_DEVICE_TARGET, vol.Required(ATTR_USER_ID): _USER_ID, vol.Required(ATTR_SLOT): _SLOT, vol.Required(ATTR_SCHEDULE_TYPE): _SCHEDULE_TYPE}
)
SET_LOCK_SCHEDULES_ENABLED_SCHEMA = vol.Schema(
    {**_DEVICE_TARGET, vol.Required(ATTR_USER_ID): _USER_ID, vol.Required(ATTR_ENABLED): cv.boolean}
)
GET_LOCK_SCHEDULE_SCHEMA = CLEAR_LOCK_SCHEDULE_SCHEMA


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the domain-wide services (they must exist whether or not an entry is loaded)."""

    def _targets(
        call: ServiceCall, collection: str, identifier: Callable[[str, int], tuple[str, str]], not_found_key: str
    ) -> list[tuple[ZwaveAlarmCoordinator, dict[str, Any]]]:
        # Targets are a node's device, or any of its entities (area/label targets aren't resolved).
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
                for node in getattr(coordinator.data, collection) if coordinator.data else []:
                    if identifier(coordinator.config_entry.entry_id, node["nodeId"]) in device.identifiers:
                        targets.append((coordinator, node))
        if not targets:
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key=not_found_key)
        return targets

    async def _keypad_chime(call: ServiceCall) -> None:
        targets = _targets(call, "keypads", keypad_device_identifier, "keypad_not_found")

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

    def _lock_targets(call: ServiceCall) -> list[tuple[ZwaveAlarmCoordinator, dict[str, Any]]]:
        return _targets(call, "locks", lock_device_identifier, "lock_not_found")

    def _lock_name(lock: dict[str, Any]) -> str:
        return lock.get("label") or f"Lock {lock['nodeId']}"

    def _check_slot(lock: dict[str, Any], kind: str, slot: int) -> None:
        supported = api.lock_supports_schedule(lock, CLIENT_SCHEDULE_KINDS[kind])
        if supported is not True:  # False: the lock has no slots for this kind; None: it hasn't reported them yet
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="schedule_unsupported" if supported is False else "schedule_not_reported",
                translation_placeholders={"lock": _lock_name(lock), "kind": kind},
            )
        slots = schedule_slot_count(lock, kind) or 0
        if slot > slots:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="schedule_slot_out_of_range",
                translation_placeholders={"lock": _lock_name(lock), "slot": str(slot), "slots": str(slots)},
            )

    async def _set_lock_schedule(call: ServiceCall) -> None:
        kind = call.data[ATTR_SCHEDULE_TYPE]
        try:
            schedule = schedule_from_service(kind, call.data)
        except vol.Invalid as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="schedule_invalid", translation_placeholders={"error": str(err)}
            ) from err
        targets = _lock_targets(call)
        for _, lock in targets:  # validate every target before sending anything
            _check_slot(lock, kind, call.data[ATTR_SLOT])
        for coordinator, lock in targets:
            await coordinator.async_set_lock_schedule(
                lock["nodeId"], call.data[ATTR_USER_ID], CLIENT_SCHEDULE_KINDS[kind], call.data[ATTR_SLOT], schedule
            )

    async def _clear_lock_schedule(call: ServiceCall) -> None:
        kind = call.data[ATTR_SCHEDULE_TYPE]
        targets = _lock_targets(call)
        for _, lock in targets:
            _check_slot(lock, kind, call.data[ATTR_SLOT])
        for coordinator, lock in targets:
            await coordinator.async_clear_lock_schedule(
                lock["nodeId"], call.data[ATTR_USER_ID], CLIENT_SCHEDULE_KINDS[kind], call.data[ATTR_SLOT]
            )

    async def _set_lock_schedules_enabled(call: ServiceCall) -> None:
        for coordinator, lock in _lock_targets(call):
            await coordinator.async_set_lock_schedules_enabled(lock["nodeId"], call.data[ATTR_USER_ID], call.data[ATTR_ENABLED])

    async def _get_lock_schedule(call: ServiceCall) -> ServiceResponse:
        kind = call.data[ATTR_SCHEDULE_TYPE]
        targets = _lock_targets(call)
        for _, lock in targets:
            _check_slot(lock, kind, call.data[ATTR_SLOT])
        return {
            _lock_name(lock): await coordinator.async_get_lock_schedule(
                lock["nodeId"], call.data[ATTR_USER_ID], CLIENT_SCHEDULE_KINDS[kind], call.data[ATTR_SLOT]
            )
            for coordinator, lock in targets
        }

    hass.services.async_register(DOMAIN, SERVICE_KEYPAD_CHIME, _keypad_chime, schema=KEYPAD_CHIME_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_SET_LOCK_SCHEDULE, _set_lock_schedule, schema=SET_LOCK_SCHEDULE_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_CLEAR_LOCK_SCHEDULE, _clear_lock_schedule, schema=CLEAR_LOCK_SCHEDULE_SCHEMA)
    hass.services.async_register(
        DOMAIN, SERVICE_SET_LOCK_SCHEDULES_ENABLED, _set_lock_schedules_enabled, schema=SET_LOCK_SCHEDULES_ENABLED_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_GET_LOCK_SCHEDULE, _get_lock_schedule, schema=GET_LOCK_SCHEDULE_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
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
    async_setup_lock_lifecycle(hass, entry, coordinator)  # lock devices exist only while the service reports the lock
    await async_register_panel(hass, show_in_sidebar=entry.options.get(CONF_SHOW_IN_SIDEBAR, True))
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    return True


async def async_remove_config_entry_device(hass: HomeAssistant, entry: ConfigEntry, device: dr.DeviceEntry) -> bool:
    """Let the user delete a stale lock device by hand, but never one that is still enrolled in the alarm system."""
    return async_can_remove_lock_device(entry, hass.data.get(DOMAIN, {}).get(entry.entry_id), device)


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
