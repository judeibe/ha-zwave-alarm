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
from homeassistant.const import EntityCategory
from homeassistant.helpers.entity import DeviceInfo, async_generate_entity_id
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .alarm_event_state import siren_sounding
from .const import DOMAIN
from .coordinator import ZwaveAlarmCoordinator
from .keypad import ZwaveAlarmKeypadEntity, async_add_keypad_entities
from .keypad_state import keypad_is_online
from .lock_state import lock_is_online
from .schlage import ZwaveAlarmLockEntity, async_add_lock_entities
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
    async_add_entities([ZwaveAlarmSirenSoundingSensor(coordinator, entry)])
    _async_add_tamper_sensors(coordinator, entry, async_add_entities)

    async_add_keypad_entities(
        coordinator, entry, async_add_entities, lambda c, e, keypad: [ZwaveAlarmKeypadConnectivitySensor(c, e, keypad)]
    )
    async_add_lock_entities(
        coordinator, entry, async_add_entities, lambda c, e, lock: [ZwaveAlarmLockConnectivitySensor(c, e, lock)]
    )


class ZwaveAlarmZoneBinarySensor(CoordinatorEntity[ZwaveAlarmCoordinator], BinarySensorEntity):
    """`binary_sensor.zwave_alarm_zone_<zone>` -- on when any sensor in this zone is breached."""

    _attr_has_entity_name = True  # HA prefixes the device name; entity_id stays the explicit one set below
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


class ZwaveAlarmKeypadConnectivitySensor(ZwaveAlarmKeypadEntity, BinarySensorEntity):
    """Whether a keypad is reachable, from the snapshot and `keypad.changed`."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "keypad_connectivity"

    def __init__(self, coordinator: ZwaveAlarmCoordinator, entry: ConfigEntry, keypad: dict[str, Any]) -> None:
        super().__init__(coordinator, entry, keypad, "connectivity")

    @property
    def is_on(self) -> bool | None:
        keypad = self._keypad()
        return keypad_is_online(keypad) if keypad is not None else None


class ZwaveAlarmLockConnectivitySensor(ZwaveAlarmLockEntity, BinarySensorEntity):
    """Whether a lock is reachable, from the snapshot and `lock.changed`."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "lock_connectivity"

    def __init__(self, coordinator: ZwaveAlarmCoordinator, entry: ConfigEntry, lock: dict[str, Any]) -> None:
        super().__init__(coordinator, entry, lock, "connectivity")

    @property
    def is_on(self) -> bool | None:
        lock = self._lock()
        return lock_is_online(lock) if lock is not None else None


class ZwaveAlarmSirenSoundingSensor(CoordinatorEntity[ZwaveAlarmCoordinator], BinarySensorEntity):
    """On while an open alarm event has its siren sounding; off once it is silenced, times out or the alarm ends."""

    _attr_has_entity_name = True
    _attr_translation_key = "siren_sounding"
    _attr_device_class = BinarySensorDeviceClass.SOUND

    def __init__(self, coordinator: ZwaveAlarmCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_siren_sounding"
        # Explicit, like the zone and fault-count entities, so the id does not depend on how HA slugs the device name.
        self.entity_id = async_generate_entity_id(ENTITY_ID_FORMAT, "zwave_alarm_siren_sounding", hass=coordinator.hass)
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry.entry_id)})

    @property
    def is_on(self) -> bool | None:
        return siren_sounding(self.coordinator.data.alarm_events) if self.coordinator.data is not None else None


@callback
def _async_add_tamper_sensors(
    coordinator: ZwaveAlarmCoordinator, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """One tamper sensor per assigned sensor, added the first time each sensor id shows up (also for later assignments)."""
    known: set[str] = set()

    @callback
    def _add() -> None:
        if coordinator.data is None:
            return
        new = [s for zone in coordinator.data.zones for s in zone["sensors"] if s["id"] not in known]
        known.update(s["id"] for s in new)
        async_add_entities(ZwaveAlarmTamperSensor(coordinator, entry, s["id"], s["name"]) for s in new)

    _add()
    entry.async_on_unload(coordinator.async_add_listener(_add))


class ZwaveAlarmTamperSensor(CoordinatorEntity[ZwaveAlarmCoordinator], BinarySensorEntity):
    """On while the sensor reports its cover removed or not seated. Tamper clears only when the cover is reseated."""

    _attr_has_entity_name = True
    _attr_device_class = BinarySensorDeviceClass.TAMPER
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: ZwaveAlarmCoordinator, entry: ConfigEntry, sensor_id: str, sensor_name: str) -> None:
        super().__init__(coordinator)
        self._sensor_id = sensor_id
        self._attr_unique_id = f"{entry.entry_id}_sensor_{sensor_id}_tamper"
        self.entity_id = async_generate_entity_id(ENTITY_ID_FORMAT, f"zwave_alarm_tamper_{sensor_name}", hass=coordinator.hass)
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry.entry_id)})

    def _sensor(self) -> dict[str, Any] | None:
        if self.coordinator.data is None:
            return None
        return next((s for z in self.coordinator.data.zones for s in z["sensors"] if s["id"] == self._sensor_id), None)

    @property
    def name(self) -> str | None:
        sensor = self._sensor()
        return f"{sensor['name']} tamper" if sensor else None

    @property
    def available(self) -> bool:
        return super().available and self._sensor() is not None

    @property
    def is_on(self) -> bool | None:
        sensor = self._sensor()
        # A service older than 3.3.0 never sends `tampered`: unknown, not "not tampered".
        return sensor.get("tampered") if sensor is not None and "tampered" in sensor else None
