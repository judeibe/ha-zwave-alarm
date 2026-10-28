"""Per-sensor settings as config entities on the sensor's own device (one set per sensor subentry).

Each entity reads its value back from the coordinator's sensor and writes through `PATCH /sensors/{id}`
(`ZwaveAlarmCoordinator.async_update_sensor_settings`). Chime entities are skipped for life-safety sensors,
which the service rejects chime fields for.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import ZwaveAlarmCoordinator
from .sensor_settings import SENSOR_WIRE_FIELDS, SUBENTRY_SENSOR, has_chime, settings_from_sensor, to_wire

# (setting key, chime-only)
SETTING_SWITCHES = (("is_interior", False), ("chime_enabled", True), ("quick_exit_enabled", False))


class ZwaveAlarmSensorSetting(CoordinatorEntity[ZwaveAlarmCoordinator]):
    """Base: a single setting of the sensor behind one subentry."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: ZwaveAlarmCoordinator, entry: ConfigEntry, subentry: Any, setting: str) -> None:
        super().__init__(coordinator)
        self._sensor_id: str = subentry.unique_id
        self._setting = setting
        self._attr_translation_key = f"sensor_{setting}"
        self._attr_unique_id = f"{entry.entry_id}_subentry_{self._sensor_id}_{setting}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry.entry_id}_sensor_{self._sensor_id}")}, name=subentry.title, via_device=(DOMAIN, entry.entry_id)
        )

    def _sensor(self) -> dict[str, Any] | None:
        if self.coordinator.data is None:
            return None
        return next((s for z in self.coordinator.data.zones for s in z["sensors"] if s["id"] == self._sensor_id), None)

    @property
    def available(self) -> bool:
        return super().available and self._sensor() is not None

    def _value(self) -> Any:
        sensor = self._sensor()
        return settings_from_sensor(sensor)[self._setting] if sensor else None

    async def _write(self, value: Any) -> None:
        await self.coordinator.async_update_sensor_settings(self._sensor_id, to_wire({self._setting: value}))


def async_sensor_subentries(entry: ConfigEntry) -> list[Any]:
    return [s for s in entry.subentries.values() if s.subentry_type == SUBENTRY_SENSOR and s.unique_id]


def async_add_sensor_settings(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
    factory: Callable[[ZwaveAlarmCoordinator, ConfigEntry, Any, bool], list[Any]],
) -> None:
    """Add `factory(coordinator, entry, subentry, has_chime)` entities to each sensor subentry's device.

    The sensor's category (which decides on chime entities) arrives with the first snapshot, so a subentry's
    entities are added the first time its sensor shows up in the coordinator data.
    """
    coordinator: ZwaveAlarmCoordinator = hass.data[DOMAIN][entry.entry_id]
    pending = {s.subentry_id: s for s in async_sensor_subentries(entry)}

    @callback
    def _add() -> None:
        if coordinator.data is None:
            return
        sensors = {s["id"]: s for z in coordinator.data.zones for s in z["sensors"]}
        for subentry_id, subentry in list(pending.items()):
            sensor = sensors.get(subentry.unique_id)
            if sensor is None:
                continue
            del pending[subentry_id]
            async_add_entities(factory(coordinator, entry, subentry, has_chime(sensor)), config_subentry_id=subentry_id)

    _add()
    entry.async_on_unload(coordinator.async_add_listener(_add))


assert set(dict(SETTING_SWITCHES)) <= set(SENSOR_WIRE_FIELDS)
