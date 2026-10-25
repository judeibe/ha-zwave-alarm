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

import re
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
from homeassistant.helpers.service import async_register_admin_service
from homeassistant.helpers.typing import ConfigType
from homeassistant.util import dt as dt_util

from .const import CAPABILITY_CHIME, CONF_SHOW_IN_SIDEBAR, CONF_SSL, DOMAIN
from .coordinator import ZwaveAlarmCoordinator
from .guest_schedule_state import (
    GUEST_WEEKDAYS,
    InvalidSchedule,
    check_mode_schedule,
    check_schedule,
    schedule_fields,
)
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

SERVICE_SET_USER_CODE = "set_user_code"
SERVICE_CLEAR_USER_CODE = "clear_user_code"
SERVICE_SET_DURESS_CODE = "set_duress_code"
SERVICE_CLEAR_DURESS_CODE = "clear_duress_code"
SERVICE_CREATE_INSTALLER = "create_installer"
ATTR_CODE = "code"
ATTR_CONFIRM_CODE = "confirm_code"
ATTR_NAME = "name"
_FOUR_DIGITS = re.compile(r"^\d{4}$")
# The code schemas are plain strings: a regex in the schema would echo a bad code in its error (and the log).
SET_USER_CODE_SCHEMA = vol.Schema(
    {vol.Required("user_id"): cv.string, vol.Required(ATTR_CODE): cv.string, vol.Optional(ATTR_CONFIRM_CODE): cv.string}
)
USER_ID_SCHEMA = vol.Schema({vol.Required("user_id"): cv.string})
CREATE_INSTALLER_SCHEMA = vol.Schema(
    {vol.Required(ATTR_NAME): cv.string, vol.Required(ATTR_CODE): cv.string, vol.Optional(ATTR_CONFIRM_CODE): cv.string}
)

SERVICE_LIST_GUEST_SCHEDULES = "list_guest_schedules"
SERVICE_ADD_GUEST_SCHEDULE = "add_guest_schedule"
SERVICE_UPDATE_GUEST_SCHEDULE = "update_guest_schedule"
SERVICE_REMOVE_GUEST_SCHEDULE = "remove_guest_schedule"
_GUEST_DAYS = vol.All(cv.ensure_list, [vol.In(GUEST_WEEKDAYS)])
_TIME_OF_DAY = vol.Any(cv.time, None)
ADD_GUEST_SCHEDULE_SCHEMA = vol.Schema(
    {
        vol.Required("user_id"): cv.string,
        vol.Required("name"): cv.string,
        vol.Required("days"): _GUEST_DAYS,
        vol.Optional("all_day"): cv.boolean,
        vol.Optional("start"): _TIME_OF_DAY,
        vol.Optional("end"): _TIME_OF_DAY,
        vol.Optional("time_zone"): cv.string,
    }
)
UPDATE_GUEST_SCHEDULE_SCHEMA = vol.Schema(
    {
        vol.Required("user_id"): cv.string,
        vol.Required("schedule_id"): cv.string,
        vol.Optional("name"): cv.string,
        vol.Optional("days"): _GUEST_DAYS,
        vol.Optional("all_day"): cv.boolean,
        vol.Optional("start"): _TIME_OF_DAY,
        vol.Optional("end"): _TIME_OF_DAY,
        vol.Optional("time_zone"): cv.string,
    }
)
GUEST_SCHEDULE_ID_SCHEMA = vol.Schema({vol.Required("user_id"): cv.string, vol.Required("schedule_id"): cv.string})

SERVICE_GET_HISTORY = "get_history"
SERVICE_LIST_MODE_SCHEDULES = "list_mode_schedules"
SERVICE_ADD_MODE_SCHEDULE = "add_mode_schedule"
SERVICE_UPDATE_MODE_SCHEDULE = "update_mode_schedule"
SERVICE_REMOVE_MODE_SCHEDULE = "remove_mode_schedule"
_MODE = vol.In(["disarmed", "armed_home", "armed_away"])
_MODE_SCHEDULE_FIELDS = {
    vol.Optional("name"): cv.string,
    vol.Optional("mode"): _MODE,
    vol.Optional("time"): cv.time,
    vol.Optional("days"): _GUEST_DAYS,
    vol.Optional("enabled"): cv.boolean,
    vol.Optional("time_zone"): cv.string,
}
ADD_MODE_SCHEDULE_SCHEMA = vol.Schema(
    {**_MODE_SCHEDULE_FIELDS, vol.Required("name"): cv.string, vol.Required("mode"): _MODE, vol.Required("time"): cv.time, vol.Required("days"): _GUEST_DAYS}
)
UPDATE_MODE_SCHEDULE_SCHEMA = vol.Schema({**_MODE_SCHEDULE_FIELDS, vol.Required("schedule_id"): cv.string})
REMOVE_MODE_SCHEDULE_SCHEMA = vol.Schema({vol.Required("schedule_id"): cv.string})
GET_HISTORY_SCHEMA = vol.Schema(
    {
        vol.Optional("event_type"): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional("device_id"): cv.string,
        vol.Optional("user_id"): cv.string,
        vol.Optional("since"): cv.datetime,
        vol.Optional("until"): cv.datetime,
        vol.Optional("before"): cv.string,
        vol.Optional("limit"): vol.All(vol.Coerce(int), vol.Range(min=1, max=500)),
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

    def _only_coordinator() -> ZwaveAlarmCoordinator:
        coordinators = _coordinators(hass)
        if len(coordinators) != 1:
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="no_single_entry")
        return coordinators[0]

    def _check_codes(call: ServiceCall) -> None:
        # Never echo the value: a bad code is only ever described, not quoted.
        for key in (ATTR_CODE, ATTR_CONFIRM_CODE):
            if key in call.data and not _FOUR_DIGITS.match(call.data[key]):
                raise ServiceValidationError(translation_domain=DOMAIN, translation_key="code_not_four_digits")

    async def _set_user_code(call: ServiceCall) -> None:
        _check_codes(call)
        await _only_coordinator().async_set_user_code(call.data["user_id"], call.data[ATTR_CODE], call.data.get(ATTR_CONFIRM_CODE))

    async def _clear_user_code(call: ServiceCall) -> None:
        await _only_coordinator().async_clear_user_code(call.data["user_id"])

    async def _set_duress_code(call: ServiceCall) -> None:
        _check_codes(call)
        await _only_coordinator().async_set_duress_code(call.data["user_id"], call.data[ATTR_CODE], call.data.get(ATTR_CONFIRM_CODE))

    async def _clear_duress_code(call: ServiceCall) -> None:
        await _only_coordinator().async_delete_duress_code(call.data["user_id"])

    async def _create_installer(call: ServiceCall) -> dict[str, Any]:
        _check_codes(call)
        user = await _only_coordinator().async_create_installer(call.data[ATTR_NAME], call.data[ATTR_CODE], call.data.get(ATTR_CONFIRM_CODE))
        # Never the code: the id to manage the user with, and when the 48 hours of access end.
        return {"user_id": user["id"], "name": user["name"], "role": user["role"], "expires_at": user.get("guestExpiresAt")}

    def _schedule_fields(call: ServiceCall, *, partial: bool) -> dict[str, Any]:
        """The client's fields from an action call; a clear error for a schedule the service would refuse."""
        data = {k: (v.strftime("%H:%M") if k in ("start", "end") and v is not None else v) for k, v in call.data.items()
                if k in ("name", "days", "all_day", "start", "end", "time_zone")}
        try:
            fields = schedule_fields(data)
            if partial:
                check_schedule(fields.get("days"), True, None, None)
                if fields.get("start") is not None and fields.get("start") == fields.get("end"):
                    raise InvalidSchedule("The start and end time must differ.")
            else:
                check_schedule(fields["days"], fields.get("all_day", False), fields.get("start"), fields.get("end"))
        except InvalidSchedule as err:
            raise ServiceValidationError(str(err)) from err
        return fields

    async def _list_guest_schedules(call: ServiceCall) -> ServiceResponse:
        return {"schedules": await _only_coordinator().async_get_guest_schedules(call.data["user_id"])}

    async def _add_guest_schedule(call: ServiceCall) -> ServiceResponse:
        fields = _schedule_fields(call, partial=False)
        name, days = fields.pop("name"), fields.pop("days")
        return await _only_coordinator().async_create_guest_schedule(call.data["user_id"], name, days, **fields)

    async def _update_guest_schedule(call: ServiceCall) -> ServiceResponse:
        fields = _schedule_fields(call, partial=True)
        if not fields:
            raise ServiceValidationError("Change at least one field.")
        return await _only_coordinator().async_update_guest_schedule(call.data["user_id"], call.data["schedule_id"], **fields)

    async def _remove_guest_schedule(call: ServiceCall) -> None:
        await _only_coordinator().async_delete_guest_schedule(call.data["user_id"], call.data["schedule_id"])

    def _mode_schedule_fields(call: ServiceCall) -> dict[str, Any]:
        fields = {k: v for k, v in call.data.items() if k in ("name", "mode", "time", "days", "enabled", "time_zone")}
        if "time" in fields:
            fields["time"] = fields["time"].strftime("%H:%M")
        try:
            check_mode_schedule(fields.get("mode"), fields.get("time"), fields.get("days"))
        except InvalidSchedule as err:
            raise ServiceValidationError(str(err)) from err
        return fields

    async def _get_history(call: ServiceCall) -> ServiceResponse:
        filters: dict[str, Any] = {k: call.data[k] for k in ("device_id", "user_id", "before", "limit") if k in call.data}
        if "event_type" in call.data:
            filters["type"] = call.data["event_type"]
        for key in ("since", "until"):
            if key in call.data:
                filters[key] = int(dt_util.as_utc(call.data[key]).timestamp() * 1000)
        return {"events": await _only_coordinator().async_get_events(**filters)}

    async def _list_mode_schedules(call: ServiceCall) -> ServiceResponse:
        return {"schedules": await _only_coordinator().async_get_mode_schedules()}

    async def _add_mode_schedule(call: ServiceCall) -> ServiceResponse:
        f = _mode_schedule_fields(call)
        return await _only_coordinator().async_create_mode_schedule(
            f["name"], f["mode"], f["time"], f["days"], f.get("enabled"), f.get("time_zone")
        )

    async def _update_mode_schedule(call: ServiceCall) -> ServiceResponse:
        fields = _mode_schedule_fields(call)
        if not fields:
            raise ServiceValidationError("Change at least one field.")
        return await _only_coordinator().async_update_mode_schedule(call.data["schedule_id"], **fields)

    async def _remove_mode_schedule(call: ServiceCall) -> None:
        await _only_coordinator().async_delete_mode_schedule(call.data["schedule_id"])

    hass.services.async_register(DOMAIN, SERVICE_KEYPAD_CHIME, _keypad_chime, schema=KEYPAD_CHIME_SCHEMA)
    async_register_admin_service(
        hass, DOMAIN, SERVICE_GET_HISTORY, _get_history, GET_HISTORY_SCHEMA, supports_response=SupportsResponse.ONLY
    )
    async_register_admin_service(
        hass, DOMAIN, SERVICE_LIST_MODE_SCHEDULES, _list_mode_schedules, vol.Schema({}), supports_response=SupportsResponse.ONLY
    )
    async_register_admin_service(
        hass, DOMAIN, SERVICE_ADD_MODE_SCHEDULE, _add_mode_schedule, ADD_MODE_SCHEDULE_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    async_register_admin_service(
        hass, DOMAIN, SERVICE_UPDATE_MODE_SCHEDULE, _update_mode_schedule, UPDATE_MODE_SCHEDULE_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    async_register_admin_service(hass, DOMAIN, SERVICE_REMOVE_MODE_SCHEDULE, _remove_mode_schedule, REMOVE_MODE_SCHEDULE_SCHEMA)
    async_register_admin_service(
        hass, DOMAIN, SERVICE_LIST_GUEST_SCHEDULES, _list_guest_schedules, USER_ID_SCHEMA, supports_response=SupportsResponse.ONLY
    )
    async_register_admin_service(
        hass, DOMAIN, SERVICE_ADD_GUEST_SCHEDULE, _add_guest_schedule, ADD_GUEST_SCHEDULE_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    async_register_admin_service(
        hass, DOMAIN, SERVICE_UPDATE_GUEST_SCHEDULE, _update_guest_schedule, UPDATE_GUEST_SCHEDULE_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    async_register_admin_service(hass, DOMAIN, SERVICE_REMOVE_GUEST_SCHEDULE, _remove_guest_schedule, GUEST_SCHEDULE_ID_SCHEMA)
    # Codes and users are administrator-only, like the panel's websocket commands.
    async_register_admin_service(hass, DOMAIN, SERVICE_SET_USER_CODE, _set_user_code, SET_USER_CODE_SCHEMA)
    async_register_admin_service(hass, DOMAIN, SERVICE_CLEAR_USER_CODE, _clear_user_code, USER_ID_SCHEMA)
    async_register_admin_service(hass, DOMAIN, SERVICE_SET_DURESS_CODE, _set_duress_code, SET_USER_CODE_SCHEMA)
    async_register_admin_service(hass, DOMAIN, SERVICE_CLEAR_DURESS_CODE, _clear_duress_code, USER_ID_SCHEMA)
    async_register_admin_service(
        hass, DOMAIN, SERVICE_CREATE_INSTALLER, _create_installer, CREATE_INSTALLER_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
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
