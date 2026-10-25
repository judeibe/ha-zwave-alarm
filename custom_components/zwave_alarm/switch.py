"""Switches for the Schlage lock's on/off settings (beeper, vacation mode, Lock & Leave, auto lock, local controls)
and for requiring a PIN to arm from a keypad."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import ENTITY_ID_FORMAT, SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo, async_generate_entity_id
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import ZwaveAlarmCoordinator
from .lock_state import lock_supports
from .schlage import ZwaveAlarmLockSettingEntity, async_add_lock_entities

# (setting key, translation key, icon); a switch is created only for settings the lock lists as supported.
SWITCHES = (
    ("beeper", "beeper", "mdi:volume-high"),
    ("vacationMode", "vacation_mode", "mdi:airplane"),
    ("lockAndLeave", "lock_and_leave", "mdi:door-closed-lock"),
    ("autoLock", "auto_lock", "mdi:lock-clock"),
    ("localControls", "local_controls", "mdi:gesture-tap-button"),  # BE469 only
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator: ZwaveAlarmCoordinator = hass.data[DOMAIN][entry.entry_id]

    def _switches(coordinator: ZwaveAlarmCoordinator, entry: ConfigEntry, lock: dict[str, Any]) -> list[ZwaveAlarmLockSwitch]:
        return [ZwaveAlarmLockSwitch(coordinator, entry, lock, *d) for d in SWITCHES if lock_supports(lock, d[0])]

    async_add_lock_entities(coordinator, entry, async_add_entities, _switches)
    _async_add_keypad_pin_switch(coordinator, entry, async_add_entities)
    _async_add_mode_schedule_switches(coordinator, entry, async_add_entities)


@callback
def _async_add_keypad_pin_switch(
    coordinator: ZwaveAlarmCoordinator, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Add the one keypad-wide switch once a keypad exists and the service reports its settings (older services don't)."""
    added = False

    @callback
    def _add() -> None:
        nonlocal added
        data = coordinator.data
        if added or data is None or not data.keypads or data.keypad_settings is None:
            return
        added = True
        async_add_entities([ZwaveAlarmKeypadPinSwitch(coordinator, entry)])

    _add()
    entry.async_on_unload(coordinator.async_add_listener(_add))


class ZwaveAlarmLockSwitch(ZwaveAlarmLockSettingEntity, SwitchEntity):
    """One boolean lock parameter; unknown until the lock has reported it."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self, coordinator: ZwaveAlarmCoordinator, entry: ConfigEntry, lock: dict[str, Any], setting_key: str, translation_key: str, icon: str
    ) -> None:
        super().__init__(coordinator, entry, lock, setting_key, translation_key)
        self._attr_icon = icon

    @property
    def is_on(self) -> bool | None:
        value = self._setting_value(self._setting_key)
        return value if isinstance(value, bool) else None

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._async_write(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._async_write(False)


class ZwaveAlarmKeypadPinSwitch(CoordinatorEntity[ZwaveAlarmCoordinator], SwitchEntity):
    """Whether arming from a keypad needs a valid PIN (disarming always does). Changing it needs an administrator."""

    _attr_has_entity_name = True
    _attr_translation_key = "keypad_require_code_to_arm"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:dialpad"

    def __init__(self, coordinator: ZwaveAlarmCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_keypad_require_code_to_arm"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry.entry_id)})

    @property
    def available(self) -> bool:
        data = self.coordinator.data
        return super().available and data is not None and data.keypad_settings is not None

    @property
    def is_on(self) -> bool | None:
        settings = self.coordinator.data.keypad_settings if self.coordinator.data is not None else None
        value = settings.get("requireCodeToArm") if settings else None
        return value if isinstance(value, bool) else None

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_update_keypad_settings(requireCodeToArm=True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_update_keypad_settings(requireCodeToArm=False)


@callback
def _async_add_mode_schedule_switches(
    coordinator: ZwaveAlarmCoordinator, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """One switch per mode schedule (on = enabled), added the first time each schedule id shows up."""
    known: set[str] = set()

    @callback
    def _add() -> None:
        if coordinator.data is None:
            return
        new = [x for x in coordinator.data.mode_schedules if x["id"] not in known]
        known.update(x["id"] for x in new)
        async_add_entities(ZwaveAlarmModeScheduleSwitch(coordinator, entry, x) for x in new)

    _add()
    entry.async_on_unload(coordinator.async_add_listener(_add))


class ZwaveAlarmModeScheduleSwitch(CoordinatorEntity[ZwaveAlarmCoordinator], SwitchEntity):
    """Turns a mode schedule on or off without deleting it. A deleted schedule's switch goes unavailable."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:calendar-clock"

    def __init__(self, coordinator: ZwaveAlarmCoordinator, entry: ConfigEntry, schedule: dict[str, Any]) -> None:
        super().__init__(coordinator)
        self._schedule_id: str = schedule["id"]
        self._attr_unique_id = f"{entry.entry_id}_mode_schedule_{self._schedule_id}"
        self.entity_id = async_generate_entity_id(ENTITY_ID_FORMAT, f"zwave_alarm_schedule_{schedule['name']}", hass=coordinator.hass)
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry.entry_id)})

    def _schedule(self) -> dict[str, Any] | None:
        if self.coordinator.data is None:
            return None
        return next((x for x in self.coordinator.data.mode_schedules if x["id"] == self._schedule_id), None)

    @property
    def name(self) -> str | None:
        schedule = self._schedule()
        return f"Schedule {schedule['name']}" if schedule else None

    @property
    def available(self) -> bool:
        return super().available and self._schedule() is not None

    @property
    def is_on(self) -> bool | None:
        schedule = self._schedule()
        return schedule["enabled"] if schedule else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        schedule = self._schedule()
        if not schedule:
            return None
        return {
            "schedule_id": schedule["id"],
            "mode": schedule["mode"],
            "time": schedule["time"],
            "days": schedule["days"],
            "time_zone": schedule.get("timeZone"),
            "last_run_at": schedule.get("lastRunAt"),
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_update_mode_schedule(self._schedule_id, enabled=True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_update_mode_schedule(self._schedule_id, enabled=False)
