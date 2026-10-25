"""Admin-only websocket commands backing the Z-Wave Alarm configuration panel.

Every command is gated by `require_admin`. Alarm codes are write-only: they are accepted by
`user/create` and `user/set_code` and are never echoed back, only `hasCode` is exposed.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable
from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession

import zwave_alarm_client as api

from .const import CONF_SSL, DOMAIN
from .fault_state import faulted_sensors
from .panel_state import map_panel_mode

_LOGGER = logging.getLogger(__name__)

# Codes are checked in `_command`, not by the schema: HA echoes a failing value in the error message and
# logs it, which would leak (partial) codes. The schema therefore accepts any object.
CODE_SCHEMA = object
_CODE_RE = re.compile(r"^\d{4,12}$")
ROLE_SCHEMA = vol.In(["administrator", "member", "guest"])
CATEGORY_SCHEMA = vol.In(["intrusion", "life-safety"])

class LockNotEnrolled(api.NotFound):
    """The lock is unknown to, or not enrolled in, the alarm system: nothing may be done to it from the panel."""


class LockUnsupported(api.BadRequest):
    """The lock's model or firmware lacks the capability the command needs (e.g. year-day schedules on a BE469ZP)."""


class LockScheduleUnknown(api.BadRequest):
    """The lock has not yet reported whether it has slots for this schedule kind (capability `null`)."""


# Client exception -> websocket error code (most specific first; the panel maps codes to text).
_ERROR_CODES: list[tuple[type[Exception], str]] = [
    (LockNotEnrolled, "lock_not_enrolled"),
    (LockUnsupported, "lock_unsupported"),
    (LockScheduleUnknown, "lock_schedule_unknown"),
    (api.LockNotSecure, "lock_not_secure"),  # a Conflict subclass: must precede it
    (api.LockUnavailable, "lock_unavailable"),  # a CannotConnect subclass: must precede it
    (api.ScheduleKindUnsupported, "schedule_kind_unsupported"),  # a BadRequest subclass: must precede it
    (api.ZoneNotEmpty, "zone_not_empty"),
    (api.ZoneInUse, "zone_in_use"),
    (api.CodeInUse, "code_in_use"),
    (api.Conflict, "conflict"),
    (api.NotFound, "not_found"),
    (api.BadRequest, "invalid_request"),
    (api.InvalidAuth, "invalid_auth"),
    (api.Forbidden, "forbidden"),
    (api.AccountLocked, "account_locked"),
    (api.TooManyRequests, "too_many_requests"),
    (api.ServiceUnavailable, "service_unavailable"),  # a CannotConnect subclass: must precede it
    (api.CannotConnect, "cannot_connect"),
]


class _Call:
    """A resolved config entry plus the connection args the client's `async_*` functions take."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.entry = entry
        self.args = (
            async_get_clientsession(hass),
            entry.data[CONF_HOST],
            entry.data[CONF_PORT],
            None,
        )
        self.kwargs = {"secure": entry.data.get(CONF_SSL, False)}

    async def __call__(self, func: Callable[..., Awaitable[Any]], *args: Any, **kwargs: Any) -> Any:
        return await func(*self.args, *args, **kwargs, **self.kwargs)


def _resolve_entry(hass: HomeAssistant, entry_id: str | None) -> ConfigEntry | None:
    entries = [e for e in hass.config_entries.async_entries(DOMAIN) if e.state is ConfigEntryState.LOADED]
    if entry_id is not None:
        return next((e for e in entries if e.entry_id == entry_id), None)
    return entries[0] if len(entries) == 1 else None


def _command(schema: dict[Any, Any]) -> Callable[[Callable[..., Awaitable[Any]]], Callable[..., None]]:
    """Wrap `handler(call, msg) -> result` as an admin-only async websocket command with uniform error mapping."""

    def decorator(handler: Callable[..., Awaitable[Any]]) -> Callable[..., None]:
        @websocket_api.websocket_command({**schema, vol.Optional("entry_id"): str})
        @websocket_api.require_admin
        @websocket_api.async_response
        async def wrapper(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
            code = msg.get("code")
            if "code" in msg and not (isinstance(code, str) and _CODE_RE.match(code)):
                connection.send_error(msg["id"], "invalid_code", "The code must be 4 to 12 digits")
                return
            entry = _resolve_entry(hass, msg.get("entry_id"))
            if entry is None:
                connection.send_error(msg["id"], "entry_not_found", "No loaded Z-Wave Alarm entry (pass entry_id)")
                return
            try:
                result = await handler(hass, _Call(hass, entry), msg)
            except api.ZwaveAlarmError as err:
                error_code = next((c for exc, c in _ERROR_CODES if isinstance(err, exc)), "unknown")
                # str(err) is the service's message; request bodies (codes) are never part of it.
                connection.send_error(msg["id"], error_code, str(err) or error_code)
            else:
                connection.send_result(msg["id"], result)

        wrapper.__name__ = handler.__name__
        return wrapper

    return decorator


def _ha_people(hass: HomeAssistant) -> list[dict[str, Any]]:
    return [
        {"entity_id": s.entity_id, "name": s.name, "user_id": s.attributes.get("user_id")}
        for s in hass.states.async_all("person")
    ]


def _zwave_device_names(hass: HomeAssistant) -> dict[int, str]:
    """Z-Wave node id -> the name Home Assistant shows for its device (the user's rename wins).

    Z-Wave JS registers each node as a device with identifier ("zwave_js", "<home_id>-<node_id>"). Other
    integrations may register longer or malformed identifiers, so only well-formed ones are read, by their
    first two items.
    """
    names: dict[int, str] = {}
    for device in dr.async_get(hass).devices.values():
        for identifier in device.identifiers:
            if not isinstance(identifier, (tuple, list)) or len(identifier) < 2:
                continue
            domain, ident = identifier[:2]
            if domain != "zwave_js" or not isinstance(ident, str):
                continue
            node_id = ident.rpartition("-")[2]
            if node_id.isdigit() and (name := device.name_by_user or device.name):
                names[int(node_id)] = name
    return names


def _with_ha_names(zones: list[dict[str, Any]], discoverable: list[dict[str, Any]], names: dict[int, str]):
    """Attach `haName` to every discoverable node and assigned sensor whose Z-Wave device HA knows."""

    def tag(item: dict[str, Any]) -> dict[str, Any]:
        name = names.get(item.get("zwaveNodeId"))
        return {**item, "haName": name} if name else item

    return (
        [{**zone, "sensors": [tag(s) for s in zone.get("sensors", [])]} for zone in zones],
        [tag(d) for d in discoverable],
    )


def _panel_summary(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, Any] | None:
    """The alarm's live state from the coordinator (what the dashboard headlines), or `None` before the first snapshot."""
    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    panel = coordinator.data.panel if coordinator is not None and coordinator.data is not None else None
    if not panel:
        return None
    try:
        state = map_panel_mode(panel["mode"])
    except (KeyError, ValueError):
        state = None
    return {
        "state": state,
        "armed_mode": panel.get("armedMode"),
        "pending_delay_ends_at": panel.get("pendingDelayEndsAt"),
    }


def _keypads_summary(hass: HomeAssistant, entry: ConfigEntry) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """The keypads and keypad settings the coordinator last received; empty and `None` before a snapshot or on older services."""
    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    data = coordinator.data if coordinator is not None else None
    if data is None:
        return [], None
    return getattr(data, "keypads", []), getattr(data, "keypad_settings", None)


def _modes(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, dict[str, int]] | None:
    """Per-mode entry/exit delays the coordinator last received; `None` before a snapshot or on a service older than 3.0.0."""
    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    data = coordinator.data if coordinator is not None else None
    return getattr(data, "modes", None)


def _lock_view(lock: dict[str, Any]) -> dict[str, Any]:
    """An enrolled lock as the panel sees it: the service's summary plus the resolved capability flags."""
    return {**lock, "capabilities": api.lock_capabilities(lock)}


def _lock_summaries(hass: HomeAssistant, entry: ConfigEntry) -> list[dict[str, Any]]:
    """Enrolled locks from the coordinator (the service sends no others); empty before the first snapshot."""
    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if coordinator is None or coordinator.data is None:
        return []
    return [_lock_view(lock) for lock in getattr(coordinator.data, "locks", [])]


def _require_lock(hass: HomeAssistant, call: "_Call", node_id: int) -> dict[str, Any]:
    """The enrolled lock `node_id`, or `LockNotEnrolled`."""
    lock = next((k for k in _lock_summaries(hass, call.entry) if k["nodeId"] == node_id), None)
    if lock is None:
        raise LockNotEnrolled(f"Lock {node_id} is not enrolled in the alarm system.")
    return lock


def _require_secure(lock: dict[str, Any]) -> None:
    """User codes and schedules need S0/S2; `secure` is `None` while unknown, which the service itself judges."""
    if lock["capabilities"].get("secure") is False:
        raise api.LockNotSecure(f"Lock {lock['nodeId']} was included without S0/S2: exclude it and include it again securely.")


def _require_user_codes(hass: HomeAssistant, call: "_Call", node_id: int) -> dict[str, Any]:
    lock = _require_lock(hass, call, node_id)
    if not lock["capabilities"].get("userCodes"):
        raise LockUnsupported(f"Lock {node_id} ({lock.get('model')}) does not support user codes.")
    _require_secure(lock)
    return lock


def _require_schedule_kind(hass: HomeAssistant, call: "_Call", node_id: int, kind: str) -> dict[str, Any]:
    """The lock, if `kind` schedules are supported (`True`); `False` is unsupported, `None` is not reported yet."""
    lock = _require_lock(hass, call, node_id)
    supported = api.lock_supports_schedule(lock, kind)
    if supported is False:
        raise LockUnsupported(f"Lock {node_id} ({lock.get('model')}) has no {kind} schedule slots.")
    if supported is None:
        raise LockScheduleUnknown(f"Lock {node_id} has not reported its {kind} schedule slots yet; refresh the lock and retry.")
    _require_secure(lock)
    return lock


def _fault_summary(zones: list[dict[str, Any]]) -> dict[str, int]:
    """Counts of faulted sensors overall and by reason, for the dashboard's health card."""
    faults = faulted_sensors(zones)
    return {
        "fault_count": len(faults),
        "offline": sum("offline" in f["reasons"] for f in faults),
        "low_battery": sum("low_battery" in f["reasons"] for f in faults),
    }


async def _ha_users(hass: HomeAssistant) -> list[dict[str, Any]]:
    return [
        {"id": u.id, "name": u.name, "is_admin": u.is_admin}
        for u in await hass.auth.async_get_users()
        if u.is_active and not u.system_generated
    ]


@_command({vol.Required("type"): "zwave_alarm/overview"})
async def ws_overview(hass: HomeAssistant, call: _Call, msg: dict[str, Any]) -> dict[str, Any]:
    """Everything the panel renders, in one round trip."""
    zones = await call(api.async_get_zones)
    # Discovery needs the zwave-js driver, which can lag behind the service: show everything else
    # and report only discovery as unavailable.
    try:
        discoverable, discoverable_error = await call(api.async_list_discoverable_sensors), None
    except api.ServiceUnavailable as err:
        discoverable, discoverable_error = [], {"code": "service_unavailable", "message": str(err)}
    faults = _fault_summary(zones)
    keypads, keypad_settings = _keypads_summary(hass, call.entry)
    # Paired-but-not-enrolled locks (admin-only `GET /locks/available`) are only ever offered for enrolment, never
    # made devices; an older service without the endpoint simply has none to offer.
    try:
        available_locks, available_locks_error = await call(api.async_list_discoverable_locks), None
    except api.ZwaveAlarmError as err:
        available_locks = []
        available_locks_error = None if isinstance(err, api.NotFound) else {"code": "service_unavailable", "message": str(err)}
    zones, discoverable = _with_ha_names(zones, discoverable, _zwave_device_names(hass))
    return {
        "panel": _panel_summary(hass, call.entry),
        "fault_count": faults["fault_count"],
        "faults": {"offline": faults["offline"], "low_battery": faults["low_battery"]},
        "zones": zones,
        "discoverable": discoverable,
        "discoverable_error": discoverable_error,
        "users": await call(api.async_list_users),
        "ha_people": _ha_people(hass),
        "ha_users": await _ha_users(hass),
        "keypads": keypads,
        "keypad_settings": keypad_settings,
        "modes": _modes(hass, call.entry),
        "locks": _lock_summaries(hass, call.entry),
        "discoverable_locks": available_locks,
        "discoverable_locks_error": available_locks_error,
    }


# --- Zones ------------------------------------------------------------------


@_command({vol.Required("type"): "zwave_alarm/zone/create", vol.Required("name"): vol.All(str, vol.Length(min=1)),
           vol.Optional("description"): vol.Any(str, None)})
async def ws_zone_create(hass: HomeAssistant, call: _Call, msg: dict[str, Any]) -> Any:
    zone = await call(api.async_create_zone, msg["name"])
    if msg.get("description"):
        zone = await call(api.async_update_zone, zone["id"], {"description": msg["description"]})
    return zone


@_command({vol.Required("type"): "zwave_alarm/zone/update", vol.Required("zone_id"): str,
           vol.Optional("name"): vol.All(str, vol.Length(min=1)), vol.Optional("description"): vol.Any(str, None)})
async def ws_zone_update(hass: HomeAssistant, call: _Call, msg: dict[str, Any]) -> Any:
    update = {k: msg[k] for k in ("name", "description") if k in msg}
    return await call(api.async_update_zone, msg["zone_id"], update)


@_command({vol.Required("type"): "zwave_alarm/zone/delete", vol.Required("zone_id"): str,
           vol.Optional("force", default=False): bool})
async def ws_zone_delete(hass: HomeAssistant, call: _Call, msg: dict[str, Any]) -> None:
    await call(api.async_delete_zone, msg["zone_id"], force=msg["force"])


# --- Sensors ----------------------------------------------------------------


PLACEMENT_SCHEMA = vol.In(["MAIN_DOOR", "SECONDARY_DOOR", "WINDOW", "ENTRYWAY", "ROOM", "GLASS_BREAK"])
ARMED_SCHEMA = vol.All(
    vol.Schema({vol.Optional("home"): bool, vol.Optional("away"): bool}), vol.Length(min=1)
)
DELAY_SCHEMA = vol.All(int, vol.Range(min=0, max=180))
_MODE_DELAYS_SCHEMA = vol.All(
    vol.Schema({vol.Optional("entryDelaySec"): DELAY_SCHEMA, vol.Optional("exitDelaySec"): DELAY_SCHEMA}),
    vol.Length(min=1),
)


@_command({vol.Required("type"): "zwave_alarm/sensor/assign", vol.Required("zone_id"): str,
           vol.Required("zwave_node_id"): int, vol.Required("name"): vol.All(str, vol.Length(min=1)),
           vol.Required("category"): CATEGORY_SCHEMA, vol.Optional("placement"): PLACEMENT_SCHEMA,
           vol.Optional("armed"): ARMED_SCHEMA, vol.Optional("alerts_only"): bool})
async def ws_sensor_assign(hass: HomeAssistant, call: _Call, msg: dict[str, Any]) -> Any:
    sensor = await call(api.async_assign_sensor, msg["zone_id"], msg["zwave_node_id"], msg["name"], msg["category"])
    # The service's POST also takes placement/armed/alertsOnly, but the client's assign call predates them: apply
    # them with the PATCH that does, so a new sensor lands configured in one panel action.
    extra = _placement_update(msg)
    return await call(api.async_update_sensor, sensor["id"], extra) if extra else sensor


def _placement_update(msg: dict[str, Any]) -> dict[str, Any]:
    update: dict[str, Any] = {}
    if "placement" in msg:
        update["placement"] = msg["placement"]
    if "armed" in msg:
        update["armed"] = msg["armed"]
    if "alerts_only" in msg:
        update["alertsOnly"] = msg["alerts_only"]
    return update


@_command({vol.Required("type"): "zwave_alarm/sensor/update", vol.Required("sensor_id"): str,
           vol.Optional("name"): vol.All(str, vol.Length(min=1)), vol.Optional("category"): CATEGORY_SCHEMA,
           vol.Optional("zone_id"): str, vol.Optional("placement"): PLACEMENT_SCHEMA,
           vol.Optional("armed"): ARMED_SCHEMA, vol.Optional("alerts_only"): bool})
async def ws_sensor_update(hass: HomeAssistant, call: _Call, msg: dict[str, Any]) -> Any:
    update = {"name": msg["name"]} if "name" in msg else {}
    update.update(_placement_update(msg))
    if "category" in msg:
        update["category"] = msg["category"]
    if "zone_id" in msg:
        update["zoneId"] = msg["zone_id"]
    return await call(api.async_update_sensor, msg["sensor_id"], update)


@_command({vol.Required("type"): "zwave_alarm/modes/update", vol.Optional("armed_home"): _MODE_DELAYS_SCHEMA,
           vol.Optional("armed_away"): _MODE_DELAYS_SCHEMA})
async def ws_modes_update(hass: HomeAssistant, call: _Call, msg: dict[str, Any]) -> Any:
    """Per-mode entry/exit delay (0-180 s); the new config is also pushed to the entities and the panel."""
    changes = {mode: msg[mode] for mode in ("armed_home", "armed_away") if mode in msg}
    if not changes:
        raise api.BadRequest("Pass armed_home and/or armed_away.")
    return await hass.data[DOMAIN][call.entry.entry_id].async_update_modes(changes)


@_command({vol.Required("type"): "zwave_alarm/sensor/unassign", vol.Required("sensor_id"): str})
async def ws_sensor_unassign(hass: HomeAssistant, call: _Call, msg: dict[str, Any]) -> None:
    await call(api.async_unassign_sensor, msg["sensor_id"])


# --- People and codes -------------------------------------------------------


@_command({vol.Required("type"): "zwave_alarm/user/create", vol.Required("name"): vol.All(str, vol.Length(min=1)),
           vol.Required("role"): ROLE_SCHEMA, vol.Optional("code"): CODE_SCHEMA,
           vol.Optional("ha_person_id"): vol.Any(str, None), vol.Optional("ha_user_id"): vol.Any(str, None),
           vol.Optional("guest_expires_at"): vol.Any(str, int, None), vol.Optional("guest_zone_id"): vol.Any(str, None)})
async def ws_user_create(hass: HomeAssistant, call: _Call, msg: dict[str, Any]) -> Any:
    return await call(
        api.async_create_user,
        msg["name"],
        msg["role"],
        msg.get("code"),
        guest_expires_at=msg.get("guest_expires_at"),
        guest_zone_id=msg.get("guest_zone_id"),
        ha_person_id=msg.get("ha_person_id"),
        ha_user_id=msg.get("ha_user_id"),
    )


_USER_FIELDS = {
    "name": "name", "role": "role", "ha_person_id": "haPersonId", "ha_user_id": "haUserId",
    "guest_expires_at": "guestExpiresAt", "guest_zone_id": "guestZoneId",
}


@_command({vol.Required("type"): "zwave_alarm/user/update", vol.Required("user_id"): str,
           vol.Optional("name"): vol.All(str, vol.Length(min=1)), vol.Optional("role"): ROLE_SCHEMA,
           vol.Optional("ha_person_id"): vol.Any(str, None), vol.Optional("ha_user_id"): vol.Any(str, None),
           vol.Optional("guest_expires_at"): vol.Any(str, int, None), vol.Optional("guest_zone_id"): vol.Any(str, None)})
async def ws_user_update(hass: HomeAssistant, call: _Call, msg: dict[str, Any]) -> Any:
    update = {wire: msg[key] for key, wire in _USER_FIELDS.items() if key in msg}
    return await call(api.async_update_user, msg["user_id"], update)


@_command({vol.Required("type"): "zwave_alarm/user/delete", vol.Required("user_id"): str})
async def ws_user_delete(hass: HomeAssistant, call: _Call, msg: dict[str, Any]) -> None:
    await call(api.async_delete_user, msg["user_id"])


@_command({vol.Required("type"): "zwave_alarm/user/set_code", vol.Required("user_id"): str,
           vol.Required("code"): CODE_SCHEMA})
async def ws_user_set_code(hass: HomeAssistant, call: _Call, msg: dict[str, Any]) -> None:
    await call(api.async_set_user_code, msg["user_id"], msg["code"])


@_command({vol.Required("type"): "zwave_alarm/user/clear_code", vol.Required("user_id"): str})
async def ws_user_clear_code(hass: HomeAssistant, call: _Call, msg: dict[str, Any]) -> None:
    await call(api.async_clear_user_code, msg["user_id"])


# --- Keypads ----------------------------------------------------------------


@_command({vol.Required("type"): "zwave_alarm/keypad_settings/update", vol.Required("require_code_to_arm"): bool})
async def ws_keypad_settings_update(hass: HomeAssistant, call: _Call, msg: dict[str, Any]) -> Any:
    return await call(api.async_update_keypad_settings, {"requireCodeToArm": msg["require_code_to_arm"]})


# --- Locks ------------------------------------------------------------------

SCHEDULE_KIND_SCHEMA = vol.In(["weekDay", "yearDay", "dailyRepeating"])
_SCHEDULE_KINDS = ("weekDay", "yearDay", "dailyRepeating")
USER_SLOT = vol.All(int, vol.Range(min=1, max=255))


@_command({vol.Required("type"): "zwave_alarm/lock/enroll", vol.Required("node_id"): int})
async def ws_lock_enroll(hass: HomeAssistant, call: _Call, msg: dict[str, Any]) -> Any:
    """Add a paired lock to the alarm system (idempotent); its device appears once the service pushes the lock."""
    return await call(api.async_enroll_lock, msg["node_id"])


@_command({vol.Required("type"): "zwave_alarm/lock/unenroll", vol.Required("node_id"): int})
async def ws_lock_unenroll(hass: HomeAssistant, call: _Call, msg: dict[str, Any]) -> dict[str, Any]:
    """Remove a lock from the alarm system (it stays paired); its device is removed when the service pushes that."""
    result = await call(api.async_unenroll_lock, msg["node_id"])
    # The service clears the lock's codes and schedules first; when it could not (an unreachable lock) it still
    # unenrols and reports `cleared: false` with the failures, which the panel shows.
    return {"node_id": result["nodeId"], "cleared": result["cleared"], "failures": result["failures"]}


@_command({vol.Required("type"): "zwave_alarm/lock/refresh", vol.Required("node_id"): int})
async def ws_lock_refresh(hass: HomeAssistant, call: _Call, msg: dict[str, Any]) -> Any:
    _require_lock(hass, call, msg["node_id"])
    return _lock_view(await call(api.async_refresh_lock, msg["node_id"]))


@_command({vol.Required("type"): "zwave_alarm/lock/settings", vol.Required("node_id"): int,
           vol.Required("settings"): dict})
async def ws_lock_settings(hass: HomeAssistant, call: _Call, msg: dict[str, Any]) -> Any:
    lock = _require_lock(hass, call, msg["node_id"])
    unsupported = sorted(set(msg["settings"]) - set(lock.get("supportedSettings", [])))
    if unsupported:
        raise LockUnsupported(f"Lock {msg['node_id']} does not support: {', '.join(unsupported)}")
    return _lock_view(await call(api.async_update_lock_settings, msg["node_id"], msg["settings"]))


@_command({vol.Required("type"): "zwave_alarm/lock/users", vol.Required("node_id"): int})
async def ws_lock_users(hass: HomeAssistant, call: _Call, msg: dict[str, Any]) -> Any:
    _require_user_codes(hass, call, msg["node_id"])
    return await call(api.async_list_lock_users, msg["node_id"])


@_command({vol.Required("type"): "zwave_alarm/lock/user/set_code", vol.Required("node_id"): int,
           vol.Required("user_id"): USER_SLOT, vol.Required("code"): CODE_SCHEMA,
           vol.Optional("status"): vol.In(["enabled", "disabled"])})
async def ws_lock_user_set_code(hass: HomeAssistant, call: _Call, msg: dict[str, Any]) -> Any:
    lock = _require_user_codes(hass, call, msg["node_id"])
    if msg["user_id"] > lock["capabilities"]["userSlots"]:
        raise LockUnsupported(f"Lock {msg['node_id']} has only {lock['capabilities']['userSlots']} user slots.")
    return await call(
        api.async_set_lock_user_code, msg["node_id"], msg["user_id"], msg["code"],
        status=msg.get("status"), pin_length=(lock.get("settings") or {}).get("pinLength"),
    )


@_command({vol.Required("type"): "zwave_alarm/lock/user/clear_code", vol.Required("node_id"): int,
           vol.Required("user_id"): USER_SLOT})
async def ws_lock_user_clear_code(hass: HomeAssistant, call: _Call, msg: dict[str, Any]) -> None:
    _require_user_codes(hass, call, msg["node_id"])
    await call(api.async_clear_lock_user_code, msg["node_id"], msg["user_id"])


@_command({vol.Required("type"): "zwave_alarm/lock/schedules", vol.Required("node_id"): int,
           vol.Required("user_id"): USER_SLOT})
async def ws_lock_schedules(hass: HomeAssistant, call: _Call, msg: dict[str, Any]) -> Any:
    """Every schedule slot of one user, for the kinds this lock supports.

    Read one slot at a time: a battery lock answers slowly and drops bursts of Z-Wave traffic.
    """
    lock = _require_lock(hass, call, msg["node_id"])
    flags = {kind: api.lock_supports_schedule(lock, kind) for kind in _SCHEDULE_KINDS}
    if not any(flag is not False for flag in flags.values()):
        raise LockUnsupported(f"Lock {msg['node_id']} ({lock.get('model')}) does not support schedules.")
    _require_secure(lock)
    kinds: dict[str, list[dict[str, Any]]] = {}
    for kind, flag in flags.items():
        if flag is not True:
            continue
        slots = []
        for slot_id in range(1, int((lock.get("scheduleSlots") or {}).get(kind) or 0) + 1):
            slot = await call(api.async_get_lock_schedule, msg["node_id"], msg["user_id"], kind, slot_id)
            slots.append({"slot_id": slot_id, "schedule": slot["schedule"]})
        kinds[kind] = slots
    # Kinds the lock has not reported yet are named, so the panel can say "not reported yet" instead of hiding them.
    return {"user_id": msg["user_id"], "kinds": kinds, "unknown": [k for k, flag in flags.items() if flag is None]}


@_command({vol.Required("type"): "zwave_alarm/lock/schedule/set", vol.Required("node_id"): int,
           vol.Required("user_id"): USER_SLOT, vol.Required("kind"): SCHEDULE_KIND_SCHEMA,
           vol.Required("slot_id"): vol.All(int, vol.Range(min=1)), vol.Required("schedule"): dict})
async def ws_lock_schedule_set(hass: HomeAssistant, call: _Call, msg: dict[str, Any]) -> None:
    lock = _require_schedule_kind(hass, call, msg["node_id"], msg["kind"])
    slots = int((lock.get("scheduleSlots") or {}).get(msg["kind"]) or 0)
    if msg["slot_id"] > slots:
        raise LockUnsupported(f"Lock {msg['node_id']} has only {slots} {msg['kind']} slots.")
    await call(api.async_set_lock_schedule, msg["node_id"], msg["user_id"], msg["kind"], msg["slot_id"], msg["schedule"])


@_command({vol.Required("type"): "zwave_alarm/lock/schedule/clear", vol.Required("node_id"): int,
           vol.Required("user_id"): USER_SLOT, vol.Required("kind"): SCHEDULE_KIND_SCHEMA,
           vol.Required("slot_id"): vol.All(int, vol.Range(min=1))})
async def ws_lock_schedule_clear(hass: HomeAssistant, call: _Call, msg: dict[str, Any]) -> None:
    _require_schedule_kind(hass, call, msg["node_id"], msg["kind"])
    await call(api.async_clear_lock_schedule, msg["node_id"], msg["user_id"], msg["kind"], msg["slot_id"])


@_command({vol.Required("type"): "zwave_alarm/lock/schedule/enabled", vol.Required("node_id"): int,
           vol.Required("user_id"): USER_SLOT, vol.Required("enabled"): bool})
async def ws_lock_schedule_enabled(hass: HomeAssistant, call: _Call, msg: dict[str, Any]) -> None:
    lock = _require_lock(hass, call, msg["node_id"])
    if all(api.lock_supports_schedule(lock, kind) is False for kind in _SCHEDULE_KINDS):
        raise LockUnsupported(f"Lock {msg['node_id']} ({lock.get('model')}) does not support schedules.")
    _require_secure(lock)
    await call(api.async_set_lock_schedules_enabled, msg["node_id"], msg["user_id"], msg["enabled"])


COMMANDS = (
    ws_overview, ws_zone_create, ws_zone_update, ws_zone_delete,
    ws_sensor_assign, ws_sensor_update, ws_sensor_unassign,
    ws_user_create, ws_user_update, ws_user_delete, ws_user_set_code, ws_user_clear_code,
    ws_keypad_settings_update,
    ws_lock_enroll, ws_lock_unenroll, ws_lock_refresh, ws_lock_settings, ws_lock_users,
    ws_lock_user_set_code, ws_lock_user_clear_code,
    ws_lock_schedules, ws_lock_schedule_set, ws_lock_schedule_clear, ws_lock_schedule_enabled,
)


def async_register_commands(hass: HomeAssistant) -> None:
    for command in COMMANDS:
        websocket_api.async_register_command(hass, command)
