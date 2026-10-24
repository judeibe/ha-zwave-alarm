"""Switches for the Schlage lock's on/off parameters (beeper, vacation mode, Lock & Leave, auto lock, local controls)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import ZwaveAlarmCoordinator
from .lock_state import lock_has_alarm_config
from .schlage import ZwaveAlarmLockConfigEntity, async_add_lock_entities

# (config key, translation key, icon); the first four exist on every lock, the last is BE469-only.
SHARED_SWITCHES = (
    ("beeper", "beeper", "mdi:volume-high"),
    ("vacationMode", "vacation_mode", "mdi:airplane"),
    ("lockAndLeave", "lock_and_leave", "mdi:door-closed-lock"),
    ("autoLock", "auto_lock", "mdi:lock-clock"),
)
ALARM_SWITCHES = (("localControlsEnabled", "local_controls", "mdi:gesture-tap-button"),)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator: ZwaveAlarmCoordinator = hass.data[DOMAIN][entry.entry_id]

    def _switches(coordinator: ZwaveAlarmCoordinator, entry: ConfigEntry, lock: dict[str, Any]) -> list[ZwaveAlarmLockSwitch]:
        definitions = SHARED_SWITCHES + (ALARM_SWITCHES if lock_has_alarm_config(lock) else ())
        return [ZwaveAlarmLockSwitch(coordinator, entry, lock, *definition) for definition in definitions]

    async_add_lock_entities(coordinator, entry, async_add_entities, _switches)


class ZwaveAlarmLockSwitch(ZwaveAlarmLockConfigEntity, SwitchEntity):
    """One boolean lock parameter; unknown until the lock has reported it."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self, coordinator: ZwaveAlarmCoordinator, entry: ConfigEntry, lock: dict[str, Any], config_key: str, translation_key: str, icon: str
    ) -> None:
        super().__init__(coordinator, entry, lock, config_key, translation_key)
        self._attr_icon = icon

    @property
    def is_on(self) -> bool | None:
        value = self._config_value(self._config_key)
        return value if isinstance(value, bool) else None

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._async_write(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._async_write(False)
