"""The Schlage lock's user code PIN length (parameter 0x10, 4-8 digits) and the per-mode entry and exit delays (0-180 s)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo, async_generate_entity_id
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import ZwaveAlarmCoordinator
from .lock_state import PIN_LENGTH_MAX, PIN_LENGTH_MIN, lock_supports
from .siren import ZwaveAlarmSirenEntity, async_add_siren_entities
from .siren_state import OUTDOOR_MAX_SEC, OUTDOOR_MIN_SEC, siren_is_configurable
from .schlage import ZwaveAlarmLockSettingEntity, async_add_lock_entities


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator: ZwaveAlarmCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_lock_entities(
        coordinator,
        entry,
        async_add_entities,
        lambda c, e, lock: [ZwaveAlarmLockPinLengthNumber(c, e, lock)] if lock_supports(lock, "pinLength") else [],
    )
    _async_add_delay_numbers(coordinator, entry, async_add_entities)
    async_add_siren_entities(
        coordinator, entry, async_add_entities,
        lambda c, e, siren: [ZwaveAlarmSirenDurationNumber(c, e, siren)] if siren_is_configurable(siren) else [],
    )


# (armed mode key in the service's `modes`, field, translation key); spec Timers: 0-180 s per mode.
MODE_DELAYS = (
    ("armed_home", "entryDelaySec", "home_entry_delay"),
    ("armed_home", "exitDelaySec", "home_exit_delay"),
    ("armed_away", "entryDelaySec", "away_entry_delay"),
    ("armed_away", "exitDelaySec", "away_exit_delay"),
)
MODE_DELAY_MAX_SEC = 180


@callback
def _async_add_delay_numbers(
    coordinator: ZwaveAlarmCoordinator, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Add the four delay numbers once the service reports `modes` (3.0.0+; older services never do)."""
    added = False

    @callback
    def _add() -> None:
        nonlocal added
        data = coordinator.data
        if added or data is None or data.modes is None:
            return
        added = True
        async_add_entities([ZwaveAlarmModeDelayNumber(coordinator, entry, *d) for d in MODE_DELAYS])

    _add()
    entry.async_on_unload(coordinator.async_add_listener(_add))


class ZwaveAlarmModeDelayNumber(CoordinatorEntity[ZwaveAlarmCoordinator], NumberEntity):
    """How long the entry or exit delay lasts in Home or Away. One value per mode: it applies to every sensor placed on a door or entryway."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value = 0
    _attr_native_max_value = MODE_DELAY_MAX_SEC
    _attr_native_step = 1
    _attr_native_unit_of_measurement = "s"
    _attr_mode = NumberMode.BOX
    _attr_icon = "mdi:timer-outline"

    def __init__(
        self, coordinator: ZwaveAlarmCoordinator, entry: ConfigEntry, mode: str, field: str, translation_key: str
    ) -> None:
        super().__init__(coordinator)
        self._mode = mode
        self._field = field
        self._attr_translation_key = translation_key
        self._attr_unique_id = f"{entry.entry_id}_{translation_key}"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry.entry_id)})

    @property
    def native_value(self) -> int | None:
        modes = self.coordinator.data.modes if self.coordinator.data is not None else None
        value = (modes or {}).get(self._mode, {}).get(self._field)
        return value if isinstance(value, int) and not isinstance(value, bool) else None

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_update_modes({self._mode: {self._field: int(value)}})


class ZwaveAlarmLockPinLengthNumber(ZwaveAlarmLockSettingEntity, NumberEntity):
    """How many digits user codes must have; changing it does not rewrite codes already stored on the lock."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value = PIN_LENGTH_MIN
    _attr_native_max_value = PIN_LENGTH_MAX
    _attr_native_step = 1
    _attr_mode = NumberMode.BOX
    _attr_icon = "mdi:dialpad"

    def __init__(self, coordinator: ZwaveAlarmCoordinator, entry: ConfigEntry, lock: dict[str, Any]) -> None:
        super().__init__(coordinator, entry, lock, "pinLength", "pin_length")

    @property
    def native_value(self) -> int | None:
        value = self._setting_value(self._setting_key)
        return value if isinstance(value, int) and not isinstance(value, bool) else None

    async def async_set_native_value(self, value: float) -> None:
        await self._async_write(int(value))


class ZwaveAlarmSirenDurationNumber(ZwaveAlarmSirenEntity, NumberEntity):
    """How long an outdoor siren sounds, 60-600 s. Base and dome sirens are fixed at 600 s and get no number."""

    _attr_translation_key = "siren_duration"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value = OUTDOOR_MIN_SEC
    _attr_native_max_value = OUTDOOR_MAX_SEC
    _attr_native_step = 1
    _attr_native_unit_of_measurement = "s"
    _attr_mode = NumberMode.BOX
    _attr_icon = "mdi:timer-outline"

    def __init__(self, coordinator: ZwaveAlarmCoordinator, entry: ConfigEntry, siren: dict[str, Any]) -> None:
        super().__init__(coordinator, entry, siren, "duration")
        self.entity_id = async_generate_entity_id("number.{}", f"zwave_alarm_siren_{self._node_id}_duration", hass=coordinator.hass)

    @property
    def native_value(self) -> int | None:
        siren = self._siren()
        value = siren.get("durationSec") if siren else None
        return value if isinstance(value, int) and not isinstance(value, bool) else None

    async def async_set_native_value(self, value: float) -> None:
        siren = self._siren()
        if siren is not None:
            await self.coordinator.async_put_siren(self._node_id, siren["kind"], duration_sec=int(value))
