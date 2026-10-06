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
from homeassistant.const import CONF_ACCESS_TOKEN, CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

import zwave_alarm_client as api

from .const import CONF_SSL, DOMAIN

_LOGGER = logging.getLogger(__name__)

# Codes are checked in `_command`, not by the schema: HA echoes a failing value in the error message and
# logs it, which would leak (partial) codes. The schema therefore accepts any object.
CODE_SCHEMA = object
_CODE_RE = re.compile(r"^\d{4,12}$")
ROLE_SCHEMA = vol.In(["administrator", "member", "guest"])
CATEGORY_SCHEMA = vol.In(["intrusion", "life-safety"])

# Client exception -> websocket error code (most specific first; the panel maps codes to text).
_ERROR_CODES: list[tuple[type[Exception], str]] = [
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
    (api.CannotConnect, "cannot_connect"),
]


class _Call:
    """A resolved config entry plus the connection args the client's `async_*` functions take."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.args = (
            async_get_clientsession(hass),
            entry.data[CONF_HOST],
            entry.data[CONF_PORT],
            entry.data[CONF_ACCESS_TOKEN],
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


async def _ha_users(hass: HomeAssistant) -> list[dict[str, Any]]:
    return [
        {"id": u.id, "name": u.name, "is_admin": u.is_admin}
        for u in await hass.auth.async_get_users()
        if u.is_active and not u.system_generated
    ]


@_command({vol.Required("type"): "zwave_alarm/overview"})
async def ws_overview(hass: HomeAssistant, call: _Call, msg: dict[str, Any]) -> dict[str, Any]:
    """Everything the panel renders, in one round trip."""
    return {
        "zones": await call(api.async_get_zones),
        "discoverable": await call(api.async_list_discoverable_sensors),
        "users": await call(api.async_list_users),
        "ha_people": _ha_people(hass),
        "ha_users": await _ha_users(hass),
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


@_command({vol.Required("type"): "zwave_alarm/sensor/assign", vol.Required("zone_id"): str,
           vol.Required("zwave_node_id"): int, vol.Required("name"): vol.All(str, vol.Length(min=1)),
           vol.Required("category"): CATEGORY_SCHEMA})
async def ws_sensor_assign(hass: HomeAssistant, call: _Call, msg: dict[str, Any]) -> Any:
    return await call(api.async_assign_sensor, msg["zone_id"], msg["zwave_node_id"], msg["name"], msg["category"])


@_command({vol.Required("type"): "zwave_alarm/sensor/update", vol.Required("sensor_id"): str,
           vol.Optional("name"): vol.All(str, vol.Length(min=1)), vol.Optional("category"): CATEGORY_SCHEMA,
           vol.Optional("zone_id"): str})
async def ws_sensor_update(hass: HomeAssistant, call: _Call, msg: dict[str, Any]) -> Any:
    update = {"name": msg["name"]} if "name" in msg else {}
    if "category" in msg:
        update["category"] = msg["category"]
    if "zone_id" in msg:
        update["zoneId"] = msg["zone_id"]
    return await call(api.async_update_sensor, msg["sensor_id"], update)


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


COMMANDS = (
    ws_overview, ws_zone_create, ws_zone_update, ws_zone_delete,
    ws_sensor_assign, ws_sensor_update, ws_sensor_unassign,
    ws_user_create, ws_user_update, ws_user_delete, ws_user_set_code, ws_user_clear_code,
)


def async_register_commands(hass: HomeAssistant) -> None:
    for command in COMMANDS:
        websocket_api.async_register_command(hass, command)
