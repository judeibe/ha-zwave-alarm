"""The `lock.<lock>` entity: the bolt of an enrolled Schlage lock (lock and unlock).

State comes from `LockSummary.locked` (True: bolt thrown, False: retracted, None: not reported yet, which Home
Assistant shows as `unknown`). Commands go to `PUT /locks/{nodeId}/state`; the bolt moves after the lock answers, so
the entity doesn't assume the new state, it waits for the `lock.changed` the service pushes.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.lock import LockEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import ZwaveAlarmCoordinator
from .lock_state import lock_is_locked
from .schlage import ZwaveAlarmLockEntity, async_add_lock_entities


# How long `locking`/`unlocking` may last. The BE469ZP can be slow (zwave-js allows a lock 10 s to report), so allow
# three times that before giving up and showing the last reported state.
LOCK_PENDING_TIMEOUT = 30


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    """Create one lock entity per lock the service reports, including locks enrolled later."""
    coordinator: ZwaveAlarmCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_lock_entities(coordinator, entry, async_add_entities, lambda c, e, lock: [ZwaveAlarmDoorLock(c, e, lock)])


class ZwaveAlarmDoorLock(ZwaveAlarmLockEntity, LockEntity):
    """The lock's bolt. It takes the device's name, so it is `lock.<lock name>`."""

    _attr_name = None

    def __init__(self, coordinator: ZwaveAlarmCoordinator, entry: ConfigEntry, lock: dict[str, Any]) -> None:
        super().__init__(coordinator, entry, lock, "lock")

    _pending: bool | None = None  # the `locked` value a command asked for, until the lock reports it (or the timeout)
    _cancel_timeout: CALLBACK_TYPE | None = None

    @property
    def is_locked(self) -> bool | None:
        lock = self._lock()
        return lock_is_locked(lock) if lock is not None else None

    @property
    def is_locking(self) -> bool:
        return self._pending is True

    @property
    def is_unlocking(self) -> bool:
        return self._pending is False

    @callback
    def _clear_pending(self) -> None:
        self._pending = None
        if self._cancel_timeout is not None:
            self._cancel_timeout()
            self._cancel_timeout = None

    @callback
    def _expire_pending(self, _now: datetime) -> None:
        self._cancel_timeout = None
        self._clear_pending()
        self.async_write_ha_state()  # fall back to the last state the lock reported

    @callback
    def _handle_coordinator_update(self) -> None:
        # Settled once the lock reports the requested value; gone once the lock is no longer reported.
        if self._pending is not None and (self._lock() is None or self.is_locked is self._pending):
            self._clear_pending()
        super()._handle_coordinator_update()

    async def _async_command(self, locked: bool) -> None:
        self._clear_pending()
        # Set before awaiting: the lock's `lock.changed` can arrive before the HTTP reply, and the UI shouldn't lag.
        # Nothing to wait for when the lock already reports the requested state.
        if self.is_locked is not locked:
            self._pending = locked
            self._cancel_timeout = async_call_later(self.hass, LOCK_PENDING_TIMEOUT, self._expire_pending)
            self.async_write_ha_state()
        try:
            await self.coordinator.async_set_locked(self._node_id, locked)  # the reply is not the new state
        except BaseException:  # LockUnavailable / NotFound arrive mapped to Home Assistant errors; clear on anything
            self._clear_pending()
            self.async_write_ha_state()
            raise

    async def async_lock(self, **kwargs: Any) -> None:
        await self._async_command(True)

    async def async_unlock(self, **kwargs: Any) -> None:
        await self._async_command(False)

    async def async_will_remove_from_hass(self) -> None:
        """Cancel the pending timer when the entity is removed (the lock was unenrolled, or the entry unloads)."""
        self._clear_pending()
        await super().async_will_remove_from_hass()
