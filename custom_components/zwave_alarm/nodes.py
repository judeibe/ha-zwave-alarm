"""Shared discovery plumbing for per-node devices (keypads, locks) reported in the stream state."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import callback
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import ZwaveAlarmCoordinator


@callback
def async_add_node_entities(
    coordinator: ZwaveAlarmCoordinator,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
    collection: str,
    factory: Callable[[ZwaveAlarmCoordinator, ConfigEntry, dict[str, Any]], list[Entity]],
) -> None:
    """Add `factory(coordinator, entry, node)` entities for every node in `StreamState.<collection>`, now and as new ones appear.

    Nodes arrive with the first `snapshot` (or a later `*.changed`), so entities are added the first time each node id shows up.
    """
    known_node_ids: set[int] = set()

    @callback
    def _add_new_nodes() -> None:
        if coordinator.data is None:
            return
        new_nodes = [n for n in getattr(coordinator.data, collection) if n["nodeId"] not in known_node_ids]
        known_node_ids.update(n["nodeId"] for n in new_nodes)
        async_add_entities([entity for node in new_nodes for entity in factory(coordinator, entry, node)])

    _add_new_nodes()
    entry.async_on_unload(coordinator.async_add_listener(_add_new_nodes))
