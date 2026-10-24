"""The Schlage lock's user code PIN length (parameter 0x10, 4-8 digits)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import ZwaveAlarmCoordinator
from .lock_state import PIN_LENGTH_MAX, PIN_LENGTH_MIN
from .schlage import ZwaveAlarmLockConfigEntity, async_add_lock_entities


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator: ZwaveAlarmCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_lock_entities(
        coordinator, entry, async_add_entities, lambda c, e, lock: [ZwaveAlarmLockPinLengthNumber(c, e, lock)]
    )


class ZwaveAlarmLockPinLengthNumber(ZwaveAlarmLockConfigEntity, NumberEntity):
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
        value = self._config_value(self._config_key)
        return value if isinstance(value, int) and not isinstance(value, bool) else None

    async def async_set_native_value(self, value: float) -> None:
        await self._async_write(int(value))
