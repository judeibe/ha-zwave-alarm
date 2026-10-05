"""Shared plumbing for the per-keypad entities (keypad contract v1.1).

Each keypad the service reports becomes its own Home Assistant device, with
the connectivity binary_sensor, battery sensor and input event entity hung off
it. Keypads arrive with the first `snapshot` (or a `keypad.changed` on later
discovery), so entities are added the first time each node id shows up.
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


def keypad_device_identifier(entry_id: str, node_id: int) -> tuple[str, str]:
    return (DOMAIN, f"{entry_id}_keypad_{node_id}")


def keypad_device_info(entry: ConfigEntry, keypad: dict[str, Any]) -> DeviceInfo:
    return DeviceInfo(
        identifiers={keypad_device_identifier(entry.entry_id, keypad["nodeId"])},
        name=keypad.get("label") or f"Keypad {keypad['nodeId']}",
        manufacturer="Z-Wave Alarm",
        model=keypad.get("adapterId"),
        via_device=(DOMAIN, entry.entry_id),
    )


@callback
def async_add_keypad_entities(
    coordinator: ZwaveAlarmCoordinator,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
    factory: Callable[[ZwaveAlarmCoordinator, ConfigEntry, dict[str, Any]], list[Entity]],
) -> None:
    """Add `factory(coordinator, entry, keypad)` entities for every keypad, now and as new ones are discovered."""
    known_node_ids: set[int] = set()

    @callback
    def _add_new_keypads() -> None:
        if coordinator.data is None:
            return
        new_keypads = [k for k in coordinator.data.keypads if k["nodeId"] not in known_node_ids]
        known_node_ids.update(k["nodeId"] for k in new_keypads)
        async_add_entities([entity for keypad in new_keypads for entity in factory(coordinator, entry, keypad)])

    _add_new_keypads()
    entry.async_on_unload(coordinator.async_add_listener(_add_new_keypads))


class ZwaveAlarmKeypadEntity(CoordinatorEntity[ZwaveAlarmCoordinator]):
    """Base for entities that read one keypad's latest summary from the coordinator."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: ZwaveAlarmCoordinator, entry: ConfigEntry, keypad: dict[str, Any], key: str) -> None:
        super().__init__(coordinator)
        self._node_id: int = keypad["nodeId"]
        self._attr_unique_id = f"{entry.entry_id}_keypad_{self._node_id}_{key}"
        self._attr_device_info = keypad_device_info(entry, keypad)

    def _keypad(self) -> dict[str, Any] | None:
        if self.coordinator.data is None:
            return None
        return next((k for k in self.coordinator.data.keypads if k["nodeId"] == self._node_id), None)

    @property
    def available(self) -> bool:
        return super().available and self._keypad() is not None
