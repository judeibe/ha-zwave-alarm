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

    async def _call_client(self, call: Awaitable[T], what: str) -> T:
        """Await a client call, mapping its errors to Home Assistant ones (`what` names the rejected action)."""
        try:
            return await call
        except api.NotFound as err:
            raise ServiceValidationError(f"The Z-Wave Alarm service could not find the target: {err}") from err
        except api.BadRequest as err:
            raise ServiceValidationError(f"The Z-Wave Alarm service rejected the {what}: {err}") from err
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

    async def async_update_modes(self, changes: dict[str, dict[str, int]]) -> dict[str, dict[str, int]]:
        """Write per-mode entry/exit delays via `PATCH /api/v1/modes` (0-180 s) and publish the returned config at once."""
        modes = await self._call_client(
            api.async_update_modes(self._session, self._host, self._port, None, changes, secure=self._secure),
            "delay",
        )
        current = self.data if self.data is not None else StreamState(panel=None, zones=[])
        self.async_set_updated_data(replace(current, modes=modes))
        return modes

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
