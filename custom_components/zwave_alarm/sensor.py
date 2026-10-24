"""The `sensor.zwave_alarm_fault_count` entity (T038).

Count of sensors currently reporting a fault (offline or low battery),
across all zones, per contracts/ha-custom-component.md's "Entities exposed
to Home Assistant" section -- lets automations alert on system health
separately from security breaches (arm/disarm, zone breach).

As of T039, this reads live state from the WebSocket-driven
`ZwaveAlarmCoordinator` (coordinator.py) rather than polling `GET
/api/v1/zones` directly. The counting logic itself lives in fault_state.py
so it can be unit tested without Home Assistant installed.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import (
    ENTITY_ID_FORMAT,
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo, async_generate_entity_id
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import ZwaveAlarmCoordinator
from .fault_state import count_faulted_sensors, faulted_sensors
from .keypad import ZwaveAlarmKeypadEntity, async_add_keypad_entities
from .keypad_state import keypad_battery_level
from .lock_state import (
    DIAGNOSTIC_COUNTERS,
    lock_battery_level,
    lock_diagnostics,
    occupied_slot_count,
    occupied_slots,
)
from .schlage import ZwaveAlarmLockEntity, async_add_lock_entities

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Create the single fault-count sensor for this config entry."""
    coordinator: ZwaveAlarmCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([ZwaveAlarmFaultCountSensor(coordinator, entry)])
    async_add_keypad_entities(
        coordinator, entry, async_add_entities, lambda c, e, keypad: [ZwaveAlarmKeypadBatterySensor(c, e, keypad)]
    )
    async_add_lock_entities(coordinator, entry, async_add_entities, _lock_sensors)


def _lock_sensors(coordinator: ZwaveAlarmCoordinator, entry: ConfigEntry, lock: dict[str, Any]) -> list[SensorEntity]:
    return [
        ZwaveAlarmLockBatterySensor(coordinator, entry, lock),
        *(ZwaveAlarmLockCounterSensor(coordinator, entry, lock, key) for key in DIAGNOSTIC_COUNTERS),
        ZwaveAlarmLockOccupiedSlotsSensor(coordinator, entry, lock),
        ZwaveAlarmLockBootloaderSensor(coordinator, entry, lock),
    ]


class ZwaveAlarmFaultCountSensor(CoordinatorEntity[ZwaveAlarmCoordinator], SensorEntity):
    """`sensor.zwave_alarm_fault_count` -- count of sensors currently reporting a fault."""

    _attr_has_entity_name = True  # HA prefixes the device name; entity_id stays the explicit one set below
    _attr_native_unit_of_measurement = "sensors"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:alert-circle-outline"

    def __init__(self, coordinator: ZwaveAlarmCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_name = "Fault Count"
        self._attr_unique_id = f"{entry.entry_id}_fault_count"
        # Explicit entity_id (matching binary_sensor.py's per-zone entities)
        # so the id matches the contract's literal
        # `sensor.zwave_alarm_fault_count` name rather than whatever slug
        # HA's default device+name naming would produce.
        self.entity_id = async_generate_entity_id(
            ENTITY_ID_FORMAT, "zwave_alarm_fault_count", hass=coordinator.hass
        )
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Z-Wave Alarm",
            manufacturer="Z-Wave Alarm",
        )

    @property
    def native_value(self) -> int | None:
        """Current fault count from the coordinator's cached data, or `None` before any snapshot arrives."""
        if self.coordinator.data is None:
            return None
        return count_faulted_sensors(self.coordinator.data.zones)

    @property
    def extra_state_attributes(self) -> dict[str, list[dict]] | None:
        """Which sensors are faulted, in which zone, and why (offline / low battery)."""
        if self.coordinator.data is None:
            return None
        return {"sensors": faulted_sensors(self.coordinator.data.zones)}


class ZwaveAlarmKeypadBatterySensor(ZwaveAlarmKeypadEntity, SensorEntity):
    """A keypad's battery percentage; unknown while the keypad reports no level."""

    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: ZwaveAlarmCoordinator, entry: ConfigEntry, keypad: dict[str, Any]) -> None:
        super().__init__(coordinator, entry, keypad, "battery")

    @property
    def native_value(self) -> int | None:
        keypad = self._keypad()
        return keypad_battery_level(keypad) if keypad is not None else None


class ZwaveAlarmLockBatterySensor(ZwaveAlarmLockEntity, SensorEntity):
    """A lock's battery percentage; unknown while the lock reports no level."""

    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: ZwaveAlarmCoordinator, entry: ConfigEntry, lock: dict[str, Any]) -> None:
        super().__init__(coordinator, entry, lock, "battery")

    @property
    def native_value(self) -> int | None:
        lock = self._lock()
        return lock_battery_level(lock) if lock is not None else None


class ZwaveAlarmLockCounterSensor(ZwaveAlarmLockEntity, SensorEntity):
    """One of the lock's read-only lifetime counters (transitions, failed attempts)."""

    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_suggested_display_precision = 0

    def __init__(self, coordinator: ZwaveAlarmCoordinator, entry: ConfigEntry, lock: dict[str, Any], key: str) -> None:
        super().__init__(coordinator, entry, lock, key)
        self._key = key
        self._attr_translation_key = _snake(key)

    @property
    def native_value(self) -> int | None:
        lock = self._lock()
        value = lock_diagnostics(lock).get(self._key) if lock is not None else None
        return value if isinstance(value, int) and not isinstance(value, bool) else None


class ZwaveAlarmLockOccupiedSlotsSensor(ZwaveAlarmLockEntity, SensorEntity):
    """How many user code slots hold a code; the slot numbers are an attribute (parameter 0x06)."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "occupied_slots"
    _attr_icon = "mdi:account-key"

    def __init__(self, coordinator: ZwaveAlarmCoordinator, entry: ConfigEntry, lock: dict[str, Any]) -> None:
        super().__init__(coordinator, entry, lock, "occupied_slots")

    @property
    def native_value(self) -> int | None:
        lock = self._lock()
        return occupied_slot_count(lock) if lock is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, list[int]] | None:
        lock = self._lock()
        return {"slots": occupied_slots(lock)} if lock is not None else None


class ZwaveAlarmLockBootloaderSensor(ZwaveAlarmLockEntity, SensorEntity):
    """The lock's bootloader version (parameter 0x12)."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "bootloader_version"
    _attr_icon = "mdi:chip"

    def __init__(self, coordinator: ZwaveAlarmCoordinator, entry: ConfigEntry, lock: dict[str, Any]) -> None:
        super().__init__(coordinator, entry, lock, "bootloader_version")

    @property
    def native_value(self) -> int | None:
        lock = self._lock()
        value = lock_diagnostics(lock).get("bootloaderVersion") if lock is not None else None
        return value if isinstance(value, int) and not isinstance(value, bool) else None


def _snake(key: str) -> str:
    return "".join(f"_{c.lower()}" if c.isupper() else c for c in key)
