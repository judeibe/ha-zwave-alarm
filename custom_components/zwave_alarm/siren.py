"""Shared plumbing for the per-siren entities: each enrolled siren is its own Home Assistant device.

Sirens arrive with the snapshot's `sirens` (or a `siren.changed` on later enrolment), so entities are added the first
time each node id shows up, like keypads and locks.
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
from .nodes import async_add_node_entities
from .siren_state import siren_label


def siren_device_info(entry: ConfigEntry, siren: dict[str, Any]) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, f"{entry.entry_id}_siren_{siren['nodeId']}")},
        name=siren_label(siren),
        manufacturer="Z-Wave Alarm",
        model=f"{siren['kind'].title()} siren",
        via_device=(DOMAIN, entry.entry_id),
    )


@callback
def async_add_siren_entities(
    coordinator: ZwaveAlarmCoordinator,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
    factory: Callable[[ZwaveAlarmCoordinator, ConfigEntry, dict[str, Any]], list[Entity]],
) -> None:
    """Add `factory(coordinator, entry, siren)` entities for every enrolled siren, now and as new ones are enrolled."""
    async_add_node_entities(coordinator, entry, async_add_entities, "sirens", factory)


class ZwaveAlarmSirenEntity(CoordinatorEntity[ZwaveAlarmCoordinator]):
    """Base for entities that read one siren's latest summary from the coordinator."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: ZwaveAlarmCoordinator, entry: ConfigEntry, siren: dict[str, Any], key: str) -> None:
        super().__init__(coordinator)
        self._node_id: int = siren["nodeId"]
        self._attr_unique_id = f"{entry.entry_id}_siren_{self._node_id}_{key}"
        self._attr_device_info = siren_device_info(entry, siren)

    def _siren(self) -> dict[str, Any] | None:
        if self.coordinator.data is None:
            return None
        return next((s for s in self.coordinator.data.sirens if s["nodeId"] == self._node_id), None)

    @property
    def available(self) -> bool:
        return super().available and self._siren() is not None
