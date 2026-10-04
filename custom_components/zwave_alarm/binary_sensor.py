"""Per-zone `binary_sensor.zwave_alarm_zone_<zone>` entities (T037).

One entity per Zone (enumerated once via `GET /api/v1/zones` at setup), `on`
when any sensor in that zone is `breached`, with each sensor's `category`
exposed as an entity attribute, per contracts/ha-custom-component.md's
"Entities exposed to Home Assistant" section.

As of T039, live state comes from the WebSocket-driven `ZwaveAlarmCoordinator`
(coordinator.py) rather than polling: each entity is a `CoordinatorEntity`
that looks itself up by zone id in `coordinator.data.zones` on every push.
The on/off and attribute logic itself lives in zone_state.py so it can be
unit tested without Home Assistant installed.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.binary_sensor import (
    ENTITY_ID_FORMAT,
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo, async_generate_entity_id
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import ZwaveAlarmCoordinator
from .zone_state import zone_is_breached, zone_is_disarmed, zone_sensor_attributes

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Create one binary_sensor per zone in the coordinator's data, including zones added later.

    Zones arrive with the first `snapshot` (or a zone refresh after an unknown
    sensor event), not at setup, so a listener adds an entity the first time
    each zone id shows up.
    """
    coordinator: ZwaveAlarmCoordinator = hass.data[DOMAIN][entry.entry_id]
    known_zone_ids: set[str] = set()

    @callback
    def _add_new_zones() -> None:
        if coordinator.data is None:
            return
        new_zones = [zone for zone in coordinator.data.zones if zone["id"] not in known_zone_ids]
        known_zone_ids.update(zone["id"] for zone in new_zones)
        async_add_entities(
            ZwaveAlarmZoneBinarySensor(coordinator, entry, zone["id"], zone["name"]) for zone in new_zones
        )

    _add_new_zones()
    entry.async_on_unload(coordinator.async_add_listener(_add_new_zones))


class ZwaveAlarmZoneBinarySensor(CoordinatorEntity[ZwaveAlarmCoordinator], BinarySensorEntity):
    """`binary_sensor.zwave_alarm_zone_<zone>` -- on when any sensor in this zone is breached."""

    _attr_device_class = BinarySensorDeviceClass.SAFETY

    def __init__(self, coordinator: ZwaveAlarmCoordinator, entry: ConfigEntry, zone_id: str, zone_name: str) -> None:
        super().__init__(coordinator)
        self._zone_id = zone_id
        self._attr_name = zone_name
        self._attr_unique_id = f"{entry.entry_id}_zone_{zone_id}"
        # Explicit entity_id (rather than has_entity_name's device+name slug,
        # which alarm_control_panel.py relies on) so the id matches the
        # contract's literal `zwave_alarm_zone_<zone>` pattern.
        self.entity_id = async_generate_entity_id(
            ENTITY_ID_FORMAT, f"zwave_alarm_zone_{zone_name}", hass=coordinator.hass
        )
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Z-Wave Alarm",
            manufacturer="Z-Wave Alarm",
        )

    def _zone(self) -> dict[str, Any] | None:
        """This zone's current dict from the coordinator's cached state, or `None` if unknown/absent."""
        if self.coordinator.data is None:
            return None
        return next((z for z in self.coordinator.data.zones if z["id"] == self._zone_id), None)

    @property
    def available(self) -> bool:
        """Unavailable if the coordinator is disconnected, or this zone no longer exists upstream.

        There's no live "zone removed" signal on the WebSocket channel, so a
        zone deleted upstream since this entity was created is only noticed
        the next time coordinator data changes and this zone is missing from
        it -- surfaced as unavailable rather than a stale last-known state.
        """
        return super().available and self._zone() is not None

    @property
    def is_on(self) -> bool | None:
        zone = self._zone()
        return zone_is_breached(zone) if zone is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        zone = self._zone()
        if zone is None:
            return None
        panel = self.coordinator.data.panel
        return {
            "sensors": zone_sensor_attributes(zone),
            # A zone-restricted guest disarmed just this zone (FR-010a): its
            # intrusion breaches are ignored until the panel is next fully
            # disarmed or armed.
            "disarmed": zone_is_disarmed(self._zone_id, panel),
        }
