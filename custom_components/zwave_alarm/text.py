"""Text platform: each sensor's entryway name."""

from __future__ import annotations

from homeassistant.components.text import TextEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .sensor_config import ZwaveAlarmSensorSetting, async_add_sensor_settings


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    async_add_sensor_settings(hass, entry, async_add_entities, lambda c, e, sub, _chime: [ZwaveAlarmEntrywayText(c, e, sub, "entryway")])


class ZwaveAlarmEntrywayText(ZwaveAlarmSensorSetting, TextEntity):
    _attr_native_min = 0
    _attr_native_max = 60  # the service takes 1..60 characters; empty clears the entryway

    @property
    def native_value(self) -> str | None:
        return self._value()

    async def async_set_value(self, value: str) -> None:
        await self._write(value)
