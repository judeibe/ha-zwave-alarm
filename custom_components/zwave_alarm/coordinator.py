"""Persistent WebSocket coordinator driving push updates for the T036-T038 entities (T039).

Subclasses Home Assistant's `DataUpdateCoordinator` but never polls
(`update_interval` is left unset, so `_schedule_refresh` is always a no-op):
`async_set_updated_data`/`async_set_update_error` are instead driven directly
by messages read off a persistent connection to
`wss://<host>/api/v1/stream` (contracts/websocket-events.md). This gets
`CoordinatorEntity`'s standard `should_poll = False` / `available`
(`last_update_success`) wiring for free on every T036-T038 entity built
against it, instead of each one polling independently.

The event-application and backoff-delay logic lives in coordinator_state.py
so it's unit-testable without Home Assistant installed; this module itself
is only verifiable here via `py_compile`/wheel-source inspection (see
the README's "Testing" note for why `homeassistant` can't be imported in this
environment).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import replace
from typing import Any, TypeVar

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

import zwave_alarm_client as api
from .coordinator_state import (
    RECONNECT_BASE_DELAY,
    RECONNECT_MAX_DELAY,
    StreamState,
    apply_event,
    next_backoff,
    references_unknown_sensor,
    security_event_payload,
)
from .keypad_state import keypad_event_payload
from .lock_mode_state import lock_event_payload

_LOGGER = logging.getLogger(__name__)

T = TypeVar("T")


class ZwaveAlarmCoordinator(DataUpdateCoordinator[StreamState]):
    """Owns the WebSocket connection and the latest snapshot+incremental state pushed over it."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        session: aiohttp.ClientSession,
        host: str,
        port: int,
        secure: bool = False,
    ) -> None:
        super().__init__(hass, _LOGGER, config_entry=entry, name="Z-Wave Alarm stream")
        # DataUpdateCoordinator otherwise starts `last_update_success = True`
        # (it assumes the first poll just hasn't run yet); for a push
        # connection that means every entity would report `available` before
        # a single `snapshot` has ever arrived -- exactly the stale/assumed
        # state contracts/ha-custom-component.md's "Failure handling"
        # section forbids (FR-006).
        self.last_update_success = False
        self._session = session
        self._host = host
        self._port = port
        self._secure = secure
        self._event_listeners: list[Callable[[str, dict[str, Any]], None]] = []
        self._keypad_event_listeners: list[Callable[[int, str, dict[str, Any]], None]] = []
        self._lock_event_listeners: list[Callable[[int, str, dict[str, Any]], None]] = []

    @callback
    def async_add_security_event_listener(
        self, listener: Callable[[str, dict[str, Any]], None]
    ) -> CALLBACK_TYPE:
        """Register `listener(event_type, attributes)` for every `event.recorded`; returns an unsubscribe callback."""
        self._event_listeners.append(listener)

        @callback
        def _remove() -> None:
            self._event_listeners.remove(listener)

        return _remove

    @callback
    def async_add_keypad_event_listener(
        self, listener: Callable[[int, str, dict[str, Any]], None]
    ) -> CALLBACK_TYPE:
        """Register `listener(node_id, event_type, attributes)` for every `keypad.event`; returns an unsubscribe callback."""
        self._keypad_event_listeners.append(listener)

        @callback
        def _remove() -> None:
            self._keypad_event_listeners.remove(listener)

        return _remove

    @callback
    def async_add_lock_event_listener(self, listener: Callable[[int, str, dict[str, Any]], None]) -> CALLBACK_TYPE:
        """Register `listener(node_id, kind, attributes)` for every `lock.event`; returns an unsubscribe callback."""
        self._lock_event_listeners.append(listener)

        @callback
        def _remove() -> None:
            self._lock_event_listeners.remove(listener)

        return _remove

    async def _call_client(self, call: Awaitable[T], what: str) -> T:
        """Await a client call, mapping its errors to Home Assistant ones (`what` names the rejected action)."""
        try:
            return await call
        except api.NotFound as err:
            raise ServiceValidationError(f"The Z-Wave Alarm service could not find the target: {err}") from err
        except api.BadRequest as err:
            raise ServiceValidationError(f"The Z-Wave Alarm service rejected the {what}: {err}") from err
        except api.Forbidden as err:
            raise HomeAssistantError(
                f"The Z-Wave Alarm service only lets an administrator or installer make this {what} change."
            ) from err
        except api.ScheduleConflict as err:  # a Conflict subclass: must precede the generic handler
            other = f" ({err.conflicts_with})" if err.conflicts_with else ""
            raise ServiceValidationError(f"Another enabled schedule{other} would run at the same time. Change the time or days, or turn the other off.") from err
        except api.CodeInUse as err:  # Conflict subclasses: must precede the generic handler below
            raise ServiceValidationError("Another person already uses that code. Choose a different one.") from err
        except api.CodeLimit as err:
            raise ServiceValidationError("The alarm already holds the most codes it allows (256, duress codes included).") from err
        except api.TooManyRequests as err:
            raise HomeAssistantError("The Z-Wave Alarm service is rate limiting requests. Try again shortly.") from err
        except api.InvalidAuth as err:
            raise HomeAssistantError("The Z-Wave Alarm service refused the request.") from err
        except api.LockUnavailable as err:  # a CannotConnect subclass, so it has to come first
            raise HomeAssistantError(f"The lock did not respond to the {what}: {err}") from err
        except api.CannotConnect as err:
            raise HomeAssistantError("Could not reach the Z-Wave Alarm service.") from err
        except api.ZwaveAlarmError as err:
            raise HomeAssistantError(f"The Z-Wave Alarm service rejected the request: {err}") from err

    async def async_chime_keypad(self, node_id: int, sound: str, volume: int | None = None) -> None:
        """Play a chime on one keypad via `POST /api/v1/keypads/{nodeId}/chime`, mapping client errors to HA errors."""
        await self._call_client(
            api.async_chime_keypad(
                self._session, self._host, self._port, None, node_id, sound, volume=volume, secure=self._secure
            ),
            "chime",
        )

    async def async_update_keypad_settings(self, **changes: Any) -> None:
        """Write keypad settings via `PATCH /api/v1/keypad-settings` and publish the returned settings at once."""
        settings = await self._call_client(
            api.async_update_keypad_settings(self._session, self._host, self._port, None, changes, secure=self._secure),
            "setting",
        )
        current = self.data if self.data is not None else StreamState(panel=None, zones=[])
        self.async_set_updated_data(apply_event(current, {"type": "keypad.settings", "settings": settings}))

    @callback
    def _publish_alarm_event(self, event: dict[str, Any]) -> None:
        current = self.data if self.data is not None else StreamState(panel=None, zones=[])
        self.async_set_updated_data(apply_event(current, {"type": "alarm.event", "event": event}))

    async def async_panic(self, kind: str, service: str | None = None) -> dict[str, Any]:
        """Raise a PANIC, FIRE, MEDICAL or SOS alarm via `POST /api/v1/panel/panic` and publish the new event at once."""
        event = await self._call_client(
            api.async_panic(self._session, self._host, self._port, None, kind, service, secure=self._secure), "panic"
        )
        self._publish_alarm_event(event)
        return event

    async def async_silence(self) -> list[dict[str, Any]]:
        """Mute every sounding siren via `POST /api/v1/panel/silence`; the alarm stays open. Refused when nothing sounds."""
        result = await self._call_client(
            api.async_silence(self._session, self._host, self._port, None, secure=self._secure), "silence"
        )
        silenced = result["silenced"]
        for event in silenced:
            self._publish_alarm_event(event)
        return silenced

    async def async_put_siren(
        self, node_id: int, kind: str, name: str | None = None, duration_sec: int | None = None
    ) -> dict[str, Any]:
        """Enroll or update a siren via `PUT /api/v1/sirens/{nodeId}` (administrator) and publish it at once."""
        siren = await self._call_client(
            api.async_put_siren(
                self._session, self._host, self._port, None, node_id, kind, name, duration_sec, secure=self._secure
            ),
            "siren",
        )
        current = self.data if self.data is not None else StreamState(panel=None, zones=[])
        self.async_set_updated_data(apply_event(current, {"type": "siren.changed", "siren": siren}))
        return siren

    async def async_delete_siren(self, node_id: int) -> None:
        """Remove an enrolled siren via `DELETE /api/v1/sirens/{nodeId}`."""
        await self._call_client(
            api.async_delete_siren(self._session, self._host, self._port, None, node_id, secure=self._secure), "siren"
        )
        current = self.data if self.data is not None else StreamState(panel=None, zones=[])
        self.async_set_updated_data(apply_event(current, {"type": "siren.removed", "nodeId": node_id}))

    # Codes below are passed straight to the service and are never logged, stored or put in an error message: the
    # client's errors carry the service's message, which never contains a code.

    async def async_set_user_code(self, user_id: str, code: str, confirm_code: str | None) -> list[dict[str, Any]]:
        """Set or replace a user's code via `PUT /api/v1/users/{id}/code`; returns each lock's sync result (3.7.0+, else `[]`)."""
        return await self._call_client(
            api.async_set_user_code(self._session, self._host, self._port, None, user_id, code, confirm_code, secure=self._secure),
            "code",
        )

    async def async_clear_user_code(self, user_id: str) -> list[dict[str, Any]]:
        return await self._call_client(
            api.async_clear_user_code(self._session, self._host, self._port, None, user_id, secure=self._secure), "code"
        )

    async def async_set_duress_code(self, user_id: str, code: str, confirm_code: str | None) -> None:
        """Set a user's duress code via `PUT /api/v1/users/{id}/duress-code` (the user must be an administrator)."""
        await self._call_client(
            api.async_set_duress_code(self._session, self._host, self._port, None, user_id, code, confirm_code, secure=self._secure),
            "duress code",
        )

    async def async_delete_duress_code(self, user_id: str) -> None:
        await self._call_client(
            api.async_delete_duress_code(self._session, self._host, self._port, None, user_id, secure=self._secure),
            "duress code",
        )

    async def async_create_installer(self, name: str, code: str, confirm_code: str | None) -> dict[str, Any]:
        """Create an installer user; the service gives it 48 hours of access (`guestExpiresAt`)."""
        return await self._call_client(
            api.async_create_user(
                self._session, self._host, self._port, None, name, "installer", code,
                confirm_code=confirm_code, secure=self._secure,
            ),
            "user",
        )

    async def async_get_guest_schedules(self, user_id: str) -> list[dict[str, Any]]:
        return await self._call_client(
            api.async_get_guest_schedules(self._session, self._host, self._port, None, user_id, secure=self._secure),
            "schedule request",
        )

    async def async_create_guest_schedule(self, user_id: str, name: str, days: list[str], **fields: Any) -> dict[str, Any]:
        """Add a keypad schedule for a guest; `time_zone` defaults to Home Assistant's, because the service may run in UTC."""
        fields.setdefault("time_zone", self.hass.config.time_zone)
        return await self._call_client(
            api.async_create_guest_schedule(
                self._session, self._host, self._port, None, user_id, name, days, secure=self._secure, **fields
            ),
            "schedule",
        )

    async def async_update_guest_schedule(self, user_id: str, schedule_id: str, **fields: Any) -> dict[str, Any]:
        return await self._call_client(
            api.async_update_guest_schedule(
                self._session, self._host, self._port, None, user_id, schedule_id, secure=self._secure, **fields
            ),
            "schedule",
        )

    async def async_delete_guest_schedule(self, user_id: str, schedule_id: str) -> None:
        await self._call_client(
            api.async_delete_guest_schedule(self._session, self._host, self._port, None, user_id, schedule_id, secure=self._secure),
            "schedule",
        )

    async def async_get_events(self, **filters: Any) -> list[dict[str, Any]]:
        """History via `GET /api/v1/events`; filters are the client's (type, device_id, user_id, since, until, before, limit)."""
        return await self._call_client(
            api.async_get_events(self._session, self._host, self._port, None, secure=self._secure, **filters), "history request"
        )

    async def async_get_mode_schedules(self) -> list[dict[str, Any]]:
        return await self._call_client(
            api.async_get_mode_schedules(self._session, self._host, self._port, None, secure=self._secure), "schedule request"
        )

    @callback
    def _publish_mode_schedule(self, schedule: dict[str, Any]) -> None:
        current = self.data if self.data is not None else StreamState(panel=None, zones=[])
        self.async_set_updated_data(apply_event(current, {"type": "mode-schedule.changed", "schedule": schedule}))

    async def async_create_mode_schedule(
        self, name: str, mode: str, time: str, days: list[str], enabled: bool | None = None, time_zone: str | None = None
    ) -> dict[str, Any]:
        """Add a mode schedule; `time_zone` defaults to Home Assistant's, because the service runs in UTC."""
        schedule = await self._call_client(
            api.async_create_mode_schedule(
                self._session, self._host, self._port, None, name, mode, time, days, enabled,
                time_zone or self.hass.config.time_zone, secure=self._secure,
            ),
            "schedule",
        )
        self._publish_mode_schedule(schedule)
        return schedule

    async def async_update_mode_schedule(self, schedule_id: str, **fields: Any) -> dict[str, Any]:
        schedule = await self._call_client(
            api.async_update_mode_schedule(
                self._session, self._host, self._port, None, schedule_id, secure=self._secure, **fields
            ),
            "schedule",
        )
        self._publish_mode_schedule(schedule)
        return schedule

    async def async_delete_mode_schedule(self, schedule_id: str) -> None:
        await self._call_client(
            api.async_delete_mode_schedule(self._session, self._host, self._port, None, schedule_id, secure=self._secure),
            "schedule",
        )
        current = self.data if self.data is not None else StreamState(panel=None, zones=[])
        self.async_set_updated_data(apply_event(current, {"type": "mode-schedule.removed", "id": schedule_id}))

    async def async_update_modes(self, changes: dict[str, dict[str, int]]) -> dict[str, dict[str, int]]:
        """Write per-mode entry/exit delays via `PATCH /api/v1/modes` (0-180 s) and publish the returned config at once."""
        modes = await self._call_client(
            api.async_update_modes(self._session, self._host, self._port, None, changes, secure=self._secure),
            "delay",
        )
        current = self.data if self.data is not None else StreamState(panel=None, zones=[])
        self.async_set_updated_data(replace(current, modes=modes))
        return modes

    def lock_names(self) -> dict[int, str]:
        """Display names of the enrolled locks, by node id, for describing a sync result."""
        locks = self.data.locks if self.data is not None else []
        return {lk["nodeId"]: lk.get("label") or f"Lock {lk['nodeId']}" for lk in locks}

    async def async_put_lock_mode_settings(self, node_id: int, **fields: Any) -> dict[str, Any]:
        """Change a lock's alarm automation via `PUT /api/v1/locks/{nodeId}/mode-settings` (administrator or installer)."""
        settings = await self._call_client(
            api.async_put_lock_mode_settings(self._session, self._host, self._port, None, node_id, secure=self._secure, **fields),
            "lock automation",
        )
        current = self.data if self.data is not None else StreamState(panel=None, zones=[])
        lock = next((lk for lk in current.locks if lk["nodeId"] == node_id), None)
        if lock is not None:
            self.async_set_updated_data(apply_event(current, {"type": "lock.changed", "lock": {**lock, "modeSettings": settings}}))
        return settings

    async def async_update_lock_settings(self, node_id: int, **changes: Any) -> None:
        """Write lock settings via `PATCH /api/v1/locks/{nodeId}/settings` and publish the returned lock at once."""
        lock = await self._call_client(
            api.async_update_lock_settings(
                self._session, self._host, self._port, None, node_id, changes, secure=self._secure
            ),
            "setting",
        )
        current = self.data if self.data is not None else StreamState(panel=None, zones=[])
        self.async_set_updated_data(apply_event(current, {"type": "lock.changed", "lock": lock}))

    async def async_set_locked(self, node_id: int, locked: bool) -> None:
        """Throw or retract the bolt via `PUT /api/v1/locks/{nodeId}/state`.

        The bolt moves after the lock answers, so the response may still show the old state and is deliberately not
        applied: the real state arrives as `lock.changed` through the stream.
        """
        await self._call_client(
            api.async_set_locked(self._session, self._host, self._port, None, node_id, locked, secure=self._secure),
            "lock" if locked else "unlock",
        )

    async def async_get_lock_schedule(self, node_id: int, user_id: int, kind: str, slot_id: int) -> dict[str, Any]:
        return await self._call_client(
            api.async_get_lock_schedule(
                self._session, self._host, self._port, None, node_id, user_id, kind, slot_id, secure=self._secure
            ),
            "schedule request",
        )

    async def async_set_lock_schedule(
        self, node_id: int, user_id: int, kind: str, slot_id: int, schedule: dict[str, Any]
    ) -> None:
        await self._call_client(
            api.async_set_lock_schedule(
                self._session, self._host, self._port, None, node_id, user_id, kind, slot_id, schedule, secure=self._secure
            ),
            "schedule",
        )

    async def async_clear_lock_schedule(self, node_id: int, user_id: int, kind: str, slot_id: int) -> None:
        await self._call_client(
            api.async_clear_lock_schedule(
                self._session, self._host, self._port, None, node_id, user_id, kind, slot_id, secure=self._secure
            ),
            "schedule",
        )

    async def async_set_lock_schedules_enabled(self, node_id: int, user_id: int, enabled: bool) -> None:
        await self._call_client(
            api.async_set_lock_schedules_enabled(
                self._session, self._host, self._port, None, node_id, user_id, enabled, secure=self._secure
            ),
            "schedule setting",
        )

    def async_start(self, entry: ConfigEntry) -> None:
        """Start the persistent connect/read loop as a config-entry-scoped background task.

        `ConfigEntry.async_create_background_task` cancels this task
        automatically on unload, so `_run`'s `asyncio.CancelledError`
        propagation is all the shutdown coordination this needs.
        """
        entry.async_create_background_task(self.hass, self._run(), "zwave_alarm_stream")

    async def _run(self) -> None:
        """Connect, stream events, and reconnect with backoff until cancelled.

        A reconnect is, from this client's point of view, indistinguishable
        from a first connect: it always opens a brand-new WebSocket, and the
        server always sends a fresh `snapshot` as the first message on any
        new connection (T034's resync guarantee), so no separate "request a
        snapshot" step is needed here beyond simply reconnecting.
        """
        attempt = 0
        while True:
            try:
                async for event in api.async_stream_events(
                    self._session, self._host, self._port, None, secure=self._secure
                ):
                    if event["type"] == "snapshot":
                        attempt = 0
                    await self._handle_event(event)
            except asyncio.CancelledError:
                raise
            except (api.InvalidAuth, api.CannotConnect) as err:
                _LOGGER.debug("Z-Wave Alarm stream connection error: %s", err)

            # The connection just ended (error, or the server/network closed
            # it cleanly) -- per the contract's "Failure handling" section,
            # entities must sit at `unavailable` for the entire outage, not
            # just once backoff eventually gives up.
            self.async_set_update_error(ConnectionError("Z-Wave Alarm stream disconnected"))
            delay = next_backoff(attempt, RECONNECT_BASE_DELAY, RECONNECT_MAX_DELAY)
            attempt += 1
            await asyncio.sleep(delay)

    async def _handle_event(self, event: dict[str, Any]) -> None:
        """Fold one server->client event into `self.data`, forwarding security events to listeners."""
        if event["type"] == "event.recorded":
            event_type, attributes = security_event_payload(event)
            for listener in list(self._event_listeners):
                listener(event_type, attributes)
            return

        if event["type"] == "lock.event":
            lock_payload = lock_event_payload(event)
            if lock_payload is not None:
                for lock_listener in list(self._lock_event_listeners):
                    lock_listener(*lock_payload)
            return

        if event["type"] == "keypad.event":
            payload = keypad_event_payload(event)
            if payload is not None:
                for keypad_listener in list(self._keypad_event_listeners):
                    keypad_listener(*payload)
            return

        current = self.data if self.data is not None else StreamState(panel=None, zones=[])
        if references_unknown_sensor(current, event):
            # A sensor/zone was added after the last snapshot: re-fetch the
            # zone list so the new entities can appear, then apply the event.
            try:
                zones = await api.async_get_zones(
                    self._session, self._host, self._port, None, secure=self._secure
                )
            except api.ZwaveAlarmError as err:
                _LOGGER.debug("Could not refresh zones after unknown sensor event: %s", err)
            else:
                current = replace(current, zones=zones)
        self.async_set_updated_data(apply_event(current, event))
