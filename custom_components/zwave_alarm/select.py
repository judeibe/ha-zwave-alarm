"""Selects for the BE469's alarm mode and its three alarm sensitivities."""

from __future__ import annotations

from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import ZwaveAlarmCoordinator
from .lock_state import (
    ALARM_MODES,
    SENSITIVITY_OPTIONS,
    SENSITIVITY_VALUES,
    alarm_mode_option,
    lock_has_alarm_config,
    sensitivity_option,
)
from .schlage import ZwaveAlarmLockConfigEntity, async_add_lock_entities

SENSITIVITY_SELECTS = (
    ("alertSensitivity", "alert_sensitivity"),
    ("tamperSensitivity", "tamper_sensitivity"),
    ("kickSensitivity", "kick_sensitivity"),
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator: ZwaveAlarmCoordinator = hass.data[DOMAIN][entry.entry_id]

    def _selects(coordinator: ZwaveAlarmCoordinator, entry: ConfigEntry, lock: dict[str, Any]) -> list[SelectEntity]:
        if not lock_has_alarm_config(lock):  # the BE468 has none of these parameters
            return []
        return [
            ZwaveAlarmLockAlarmModeSelect(coordinator, entry, lock),
            *(ZwaveAlarmLockSensitivitySelect(coordinator, entry, lock, *select) for select in SENSITIVITY_SELECTS),
        ]

    async_add_lock_entities(coordinator, entry, async_add_entities, _selects)


class ZwaveAlarmLockAlarmModeSelect(ZwaveAlarmLockConfigEntity, SelectEntity):
    """Which event the lock's built-in alarm reacts to (parameter 0x07)."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_options = list(ALARM_MODES)
    _attr_icon = "mdi:shield-alert-outline"

    def __init__(self, coordinator: ZwaveAlarmCoordinator, entry: ConfigEntry, lock: dict[str, Any]) -> None:
        super().__init__(coordinator, entry, lock, "alarmMode", "alarm_mode")

    @property
    def current_option(self) -> str | None:
        return alarm_mode_option(self._config_value(self._config_key))

    async def async_select_option(self, option: str) -> None:
        await self._async_write(option)


class ZwaveAlarmLockSensitivitySelect(ZwaveAlarmLockConfigEntity, SelectEntity):
    """The alert, tamper or kick sensitivity (parameters 0x08-0x0A); 1 is most sensitive, 5 least."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_options = list(SENSITIVITY_OPTIONS.values())
    _attr_icon = "mdi:tune-vertical"

    @property
    def current_option(self) -> str | None:
        return sensitivity_option(self._config_value(self._config_key))

    async def async_select_option(self, option: str) -> None:
        await self._async_write(SENSITIVITY_VALUES[option])
