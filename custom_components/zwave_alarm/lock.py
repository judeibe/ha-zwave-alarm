"""The `lock.<lock>` entity: the bolt of an enrolled Schlage lock (lock and unlock).

State comes from `LockSummary.locked` (True: bolt thrown, False: retracted, None: not reported yet, which Home
Assistant shows as `unknown`). Commands go to `PUT /locks/{nodeId}/state`; the bolt moves after the lock answers, so
the entity doesn't assume the new state, it waits for the `lock.changed` the service pushes.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.lock import LockEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import ZwaveAlarmCoordinator
from .lock_state import lock_is_locked
from .schlage import ZwaveAlarmLockEntity, async_add_lock_entities


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    """Create one lock entity per lock the service reports, including locks enrolled later."""
    coordinator: ZwaveAlarmCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_lock_entities(coordinator, entry, async_add_entities, lambda c, e, lock: [ZwaveAlarmDoorLock(c, e, lock)])


class ZwaveAlarmDoorLock(ZwaveAlarmLockEntity, LockEntity):
    """The lock's bolt. It takes the device's name, so it is `lock.<lock name>`."""

    _attr_name = None

    def __init__(self, coordinator: ZwaveAlarmCoordinator, entry: ConfigEntry, lock: dict[str, Any]) -> None:
        super().__init__(coordinator, entry, lock, "lock")

    @property
    def is_locked(self) -> bool | None:
        lock = self._lock()
        return lock_is_locked(lock) if lock is not None else None

    async def async_lock(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_locked(self._node_id, True)

    async def async_unlock(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_locked(self._node_id, False)
