"""Button platform: open a sensor's quick-exit window."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .sensor_config import ZwaveAlarmSensorSetting, async_add_sensor_settings


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    # Life-safety sensors have no chime and no quick exit; `chime` is False exactly for them.
    async_add_sensor_settings(
        hass, entry, async_add_entities, lambda c, e, sub, chime: [ZwaveAlarmQuickExitButton(c, e, sub, "quick_exit")] if chime else []
    )


class ZwaveAlarmQuickExitButton(ZwaveAlarmSensorSetting, ButtonEntity):
    """Press to let the door open for a few seconds without tripping the alarm (panel armed Home, quick exit on)."""

    _attr_entity_category = None  # an action, not a setting

    async def async_press(self) -> None:
        await self.coordinator.async_quick_exit(self._sensor_id)
