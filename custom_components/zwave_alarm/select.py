"""Selects for the BE469's alarm mode and its three alarm sensitivities."""

from __future__ import annotations

from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo, async_generate_entity_id
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.components.select import ENTITY_ID_FORMAT
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import ZwaveAlarmCoordinator
from .sensor_config import ZwaveAlarmSensorSetting, async_add_sensor_settings
from .sensor_settings import CHIME_SOUNDS, SENSOR_KINDS
from .lock_state import (
    ALARM_MODES,
    SENSITIVITY_OPTIONS,
    SENSITIVITY_VALUES,
    alarm_mode_option,
    lock_supports,
    sensitivity_option,
)
from .lock_mode_state import ACTION_OPTIONS, MODES, action_option, action_value, mode_settings
from .schlage import ZwaveAlarmLockModeEntity, ZwaveAlarmLockSettingEntity, async_add_lock_entities

SENSITIVITY_SELECTS = (
    ("alertSensitivity", "alert_sensitivity"),
    ("tamperSensitivity", "tamper_sensitivity"),
    ("kickSensitivity", "kick_sensitivity"),
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator: ZwaveAlarmCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_sensor_settings(
        hass, entry, async_add_entities,
        lambda c, e, sub, chime: [ZwaveAlarmSensorKindSelect(c, e, sub, "sensor_kind"), *([ZwaveAlarmChimeSoundSelect(c, e, sub, "chime_sound")] if chime else [])],
    )

    def _selects(coordinator: ZwaveAlarmCoordinator, entry: ConfigEntry, lock: dict[str, Any]) -> list[SelectEntity]:
        selects: list[SelectEntity] = []
        if lock_supports(lock, "alarmMode"):  # the BE468 lists none of these settings
            selects.append(ZwaveAlarmLockAlarmModeSelect(coordinator, entry, lock))
        selects.extend(
            ZwaveAlarmLockSensitivitySelect(coordinator, entry, lock, *select)
            for select in SENSITIVITY_SELECTS
            if lock_supports(lock, select[0])
        )
        return selects

    async_add_lock_entities(coordinator, entry, async_add_entities, _selects)
    async_add_lock_entities(
        coordinator, entry, async_add_entities,
        lambda c, e, lock: [ZwaveAlarmLockModeActionSelect(c, e, lock, mode) for mode in MODES] if mode_settings(lock) is not None else [],
    )


class ZwaveAlarmLockAlarmModeSelect(ZwaveAlarmLockSettingEntity, SelectEntity):
    """Which event the lock's built-in alarm reacts to (parameter 0x07)."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_options = list(ALARM_MODES)
    _attr_icon = "mdi:shield-alert-outline"

    def __init__(self, coordinator: ZwaveAlarmCoordinator, entry: ConfigEntry, lock: dict[str, Any]) -> None:
        super().__init__(coordinator, entry, lock, "alarmMode", "alarm_mode")

    @property
    def current_option(self) -> str | None:
        return alarm_mode_option(self._setting_value(self._setting_key))

    async def async_select_option(self, option: str) -> None:
        await self._async_write(option)


class ZwaveAlarmLockSensitivitySelect(ZwaveAlarmLockSettingEntity, SelectEntity):
    """The alert, tamper or kick sensitivity (parameters 0x08-0x0A); 1 is most sensitive, 5 least."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_options = list(SENSITIVITY_OPTIONS.values())
    _attr_icon = "mdi:tune-vertical"

    @property
    def current_option(self) -> str | None:
        return sensitivity_option(self._setting_value(self._setting_key))

    async def async_select_option(self, option: str) -> None:
        await self._async_write(SENSITIVITY_VALUES[option])


class ZwaveAlarmLockModeActionSelect(ZwaveAlarmLockModeEntity, SelectEntity):
    """What this lock does when the alarm enters a mode: nothing, lock the bolt, or unlock it."""

    _attr_options = ACTION_OPTIONS
    _attr_icon = "mdi:lock-clock"

    def __init__(self, coordinator: ZwaveAlarmCoordinator, entry: ConfigEntry, lock: dict[str, Any], mode: str) -> None:
        super().__init__(coordinator, entry, lock, f"action_{mode}")
        self._mode = mode

    @property
    def current_option(self) -> str | None:
        return action_option(self._mode_settings(), self._mode)

    async def async_select_option(self, option: str) -> None:
        # A partial `actions` merges per mode on the service, so only this mode changes.
        await self._async_put(actions={self._mode: action_value(option)})


CHIRP_TONES = ["none", "double_beep", "guitar", "wind_chimes", "bing_bong", "doorbell"]


class ZwaveAlarmSensorKindSelect(ZwaveAlarmSensorSetting, SelectEntity):
    """What the sensor watches: a door, a window or the interior."""

    _attr_options = SENSOR_KINDS

    @property
    def current_option(self) -> str | None:
        return self._value()

    async def async_select_option(self, option: str) -> None:
        await self._write(option)


class ZwaveAlarmChimeSoundSelect(ZwaveAlarmSensorSetting, SelectEntity):
    """Which chime plays when the sensor trips (the chime switch turns it on and off)."""

    _attr_options = CHIME_SOUNDS

    @property
    def current_option(self) -> str | None:
        return self._value()

    async def async_select_option(self, option: str) -> None:
        await self._write(option)
