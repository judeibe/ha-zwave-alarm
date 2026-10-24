"""Shared plumbing for the per-lock entities (Schlage BE469 / BE468).

Each lock the service reports (enrolled locks only) becomes its own Home Assistant device, with its
configuration switches/selects/number and diagnostic sensors hung off it. Entities
are created from the lock's `supportedSettings`, so the BE469-only parameters (alarm
mode, sensitivities, local controls) never appear on a BE468.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.entity import DeviceInfo, Entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import ZwaveAlarmCoordinator
from .lock_state import lock_settings
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


def _is_lock_identifier(entry_id: str, identifier: tuple[str, str]) -> bool:
    return identifier[0] == DOMAIN and identifier[1].startswith(f"{entry_id}_lock_")


@callback
def async_setup_lock_lifecycle(hass: HomeAssistant, entry: ConfigEntry, coordinator: ZwaveAlarmCoordinator) -> None:
    """Remove the device (and so its entities) of every lock the service no longer reports.

    The service reports enrolled locks only, and sends `lock.removed` on unenrol or when the node leaves the Z-Wave
    network; the coordinator drops the lock from its data and this removes the device. It also prunes a lock device
    left over from an unenrol that happened while Home Assistant was down. Nothing is removed before the first
    snapshot (`coordinator.data is None`), and a dropped stream keeps the last data, so an outage can't wipe devices.
    """

    @callback
    def _sync() -> None:
        if coordinator.data is None:
            return
        enrolled = {lock_device_identifier(entry.entry_id, lock["nodeId"]) for lock in coordinator.data.locks}
        registry = dr.async_get(hass)
        for device in dr.async_entries_for_config_entry(registry, entry.entry_id):
            lock_ids = {i for i in device.identifiers if _is_lock_identifier(entry.entry_id, i)}
            if lock_ids and not lock_ids & enrolled:
                registry.async_remove_device(device.id)  # a device has a single config entry; removing it drops its entities

    _sync()
    entry.async_on_unload(coordinator.async_add_listener(_sync))


@callback
def async_can_remove_lock_device(entry: ConfigEntry, coordinator: ZwaveAlarmCoordinator | None, device: dr.DeviceEntry) -> bool:
    """Whether the user may delete `device` by hand: never a lock still enrolled (unenrol it from the panel instead)."""
    enrolled = {lock["nodeId"] for lock in coordinator.data.locks} if coordinator and coordinator.data else set()
    return not any(
        _is_lock_identifier(entry.entry_id, i) and int(i[1].rsplit("_", 1)[1]) in enrolled for i in device.identifiers
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

    def _setting_value(self, key: str) -> Any:
        lock = self._lock()
        return lock_settings(lock).get(key) if lock is not None else None

    @property
    def available(self) -> bool:
        return super().available and self._lock() is not None


class ZwaveAlarmLockSettingEntity(ZwaveAlarmLockEntity):
    """A writable lock parameter, read from `settings[setting_key]` and written back with `PATCH .../settings`."""

    def __init__(
        self, coordinator: ZwaveAlarmCoordinator, entry: ConfigEntry, lock: dict[str, Any], setting_key: str, translation_key: str
    ) -> None:
        super().__init__(coordinator, entry, lock, translation_key)
        self._setting_key = setting_key
        self._attr_translation_key = translation_key

    async def _async_write(self, value: Any) -> None:
        await self.coordinator.async_update_lock_settings(self._node_id, **{self._setting_key: value})
