"""Shared discovery plumbing for per-node devices (keypads, locks) reported in the stream state."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import ZwaveAlarmCoordinator


def _live_unique_ids(coordinator: ZwaveAlarmCoordinator, entry: ConfigEntry) -> set[str | None]:
    """Unique ids of this entry's entities that currently exist (registered and holding a state)."""
    hass = coordinator.hass
    return {
        e.unique_id
        for e in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
        if hass.states.get(e.entity_id) is not None
    }


@callback
def async_add_node_entities(
    coordinator: ZwaveAlarmCoordinator,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
    collection: str,
    factory: Callable[[ZwaveAlarmCoordinator, ConfigEntry, dict[str, Any]], list[Entity]],
) -> None:
    """Add `factory(coordinator, entry, node)` entities for every node in `StreamState.<collection>`, now and as new ones appear (a node that was removed and comes back is added again).

    Nodes arrive with the first `snapshot` (or a later `*.changed`), so entities are added the first time each node id shows up.
    A node that drops out of the list (a snapshot sent before the service rediscovered it) keeps its entities, which go
    unavailable; when it returns only entities that no longer exist are added, so none is created twice.
    """
    known_node_ids: set[int] = set()

    @callback
    def _add_new_nodes() -> None:
        if coordinator.data is None:
            return
        nodes = getattr(coordinator.data, collection)
        known_node_ids.intersection_update(n["nodeId"] for n in nodes)  # forget removed nodes so a re-added one gets entities again
        new_nodes = [n for n in nodes if n["nodeId"] not in known_node_ids]
        known_node_ids.update(n["nodeId"] for n in new_nodes)
        live = _live_unique_ids(coordinator, entry)
        async_add_entities(
            [e for node in new_nodes for e in factory(coordinator, entry, node) if e.unique_id not in live]
        )

    _add_new_nodes()
    entry.async_on_unload(coordinator.async_add_listener(_add_new_nodes))
