"""Shared plumbing for the per-lock entities (Schlage BE469 / BE468).

Each lock the service reports becomes its own Home Assistant device, with its
configuration switches/selects/number and diagnostic sensors hung off it. The
BE469-only parameters (alarm mode, sensitivities, local controls) are only
created for locks that advertise the `alarm_config` capability.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import callback
from homeassistant.helpers.entity import DeviceInfo, Entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import ZwaveAlarmCoordinator
from .lock_state import lock_config
from .nodes import async_add_node_entities


def lock_device_identifier(entry_id: str, node_id: int) -> tuple[str, str]:
    return (DOMAIN, f"{entry_id}_lock_{node_id}")


def lock_device_info(entry: ConfigEntry, lock: dict[str, Any]) -> DeviceInfo:
    return DeviceInfo(
        identifiers={lock_device_identifier(entry.entry_id, lock["nodeId"])},
        name=lock.get("label") or f"Lock {lock['nodeId']}",
        manufacturer="Schlage",
        model=lock.get("model") or lock.get("adapterId"),
        via_device=(DOMAIN, entry.entry_id),
    )


@callback
def async_add_lock_entities(
    coordinator: ZwaveAlarmCoordinator,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
    factory: Callable[[ZwaveAlarmCoordinator, ConfigEntry, dict[str, Any]], list[Entity]],
) -> None:
    """Add `factory(coordinator, entry, lock)` entities for every lock, now and as new ones are discovered."""
    async_add_node_entities(coordinator, entry, async_add_entities, "locks", factory)


class ZwaveAlarmLockEntity(CoordinatorEntity[ZwaveAlarmCoordinator]):
    """Base for entities that read one lock's latest summary from the coordinator."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: ZwaveAlarmCoordinator, entry: ConfigEntry, lock: dict[str, Any], key: str) -> None:
        super().__init__(coordinator)
        self._node_id: int = lock["nodeId"]
        self._attr_unique_id = f"{entry.entry_id}_lock_{self._node_id}_{key}"
        self._attr_device_info = lock_device_info(entry, lock)

    def _lock(self) -> dict[str, Any] | None:
        if self.coordinator.data is None:
            return None
        return next((lk for lk in self.coordinator.data.locks if lk["nodeId"] == self._node_id), None)

    def _config_value(self, key: str) -> Any:
        lock = self._lock()
        return lock_config(lock).get(key) if lock is not None else None

    @property
    def available(self) -> bool:
        return super().available and self._lock() is not None


class ZwaveAlarmLockConfigEntity(ZwaveAlarmLockEntity):
    """A writable lock parameter, stored under `config[config_key]` and written back with `PATCH .../config`."""

    def __init__(
        self, coordinator: ZwaveAlarmCoordinator, entry: ConfigEntry, lock: dict[str, Any], config_key: str, translation_key: str
    ) -> None:
        super().__init__(coordinator, entry, lock, translation_key)
        self._config_key = config_key
        self._attr_translation_key = translation_key

    async def _async_write(self, value: Any) -> None:
        await self.coordinator.async_update_lock_config(self._node_id, **{self._config_key: value})
