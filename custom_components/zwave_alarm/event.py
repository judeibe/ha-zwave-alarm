"""The `event.zwave_alarm_security_events` entity (FR-011, FR-013, User Story 3).

Surfaces every `event.recorded` the service pushes, so Home Assistant
automations can trigger on e.g. `alarm_cleared` and read its `details`
("Cleared by <name>" / "Cleared by Home Assistant") to tell recipients the
alarm was cleared and by whom -- which the alarm_control_panel state alone
cannot carry.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.event import ENTITY_ID_FORMAT, EventEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo, async_generate_entity_id
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import ZwaveAlarmCoordinator
from .keypad import ZwaveAlarmKeypadEntity, async_add_keypad_entities
from .keypad_state import KEYPAD_EVENT_TYPES

# data-model.md SecurityEvent.type
SECURITY_EVENT_TYPES = [
    "armed",
    "disarmed",
    "breach",
    "alarm_triggered",
    "alarm_cleared",
    "device_fault",
    "lockout",
    "guest_code_used",
]


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Create the single security-event entity for this config entry."""
    coordinator: ZwaveAlarmCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([ZwaveAlarmSecurityEvents(coordinator, entry)])
    async_add_keypad_entities(
        coordinator, entry, async_add_entities, lambda c, e, keypad: [ZwaveAlarmKeypadInputEvent(c, e, keypad)]
    )


class ZwaveAlarmSecurityEvents(EventEntity):
    """Fires once per `SecurityEvent` the service records."""

    _attr_has_entity_name = True
    _attr_translation_key = "security_events"
    _attr_should_poll = False
    _attr_event_types = SECURITY_EVENT_TYPES

    def __init__(self, coordinator: ZwaveAlarmCoordinator, entry: ConfigEntry) -> None:
        self._coordinator = coordinator
        self._attr_unique_id = f"{entry.entry_id}_security_events"
        self.entity_id = async_generate_entity_id(ENTITY_ID_FORMAT, "zwave_alarm_security_events", hass=coordinator.hass)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Z-Wave Alarm",
            manufacturer="Z-Wave Alarm",
        )

    @property
    def available(self) -> bool:
        return self._coordinator.last_update_success

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self._coordinator.async_add_security_event_listener(self._handle_event))
        # Track availability: the coordinator flips it on disconnect/reconnect.
        self.async_on_remove(self._coordinator.async_add_listener(self.async_write_ha_state))

    @callback
    def _handle_event(self, event_type: str, attributes: dict[str, Any]) -> None:
        # An event type this integration doesn't know yet (newer service) is
        # dropped: EventEntity rejects types outside `event_types`.
        if event_type in SECURITY_EVENT_TYPES:
            self._trigger_event(event_type, attributes)
            self.async_write_ha_state()


class ZwaveAlarmKeypadInputEvent(ZwaveAlarmKeypadEntity, EventEntity):
    """Fires on each button press on one keypad (`keypad.event`); never carries the entered code."""

    _attr_translation_key = "keypad_input"
    _attr_event_types = KEYPAD_EVENT_TYPES

    def __init__(self, coordinator: ZwaveAlarmCoordinator, entry: ConfigEntry, keypad: dict[str, Any]) -> None:
        super().__init__(coordinator, entry, keypad, "input")

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self.coordinator.async_add_keypad_event_listener(self._handle_keypad_event))

    @callback
    def _handle_keypad_event(self, node_id: int, event_type: str, attributes: dict[str, Any]) -> None:
        if node_id == self._node_id:
            self._trigger_event(event_type, attributes)
            self.async_write_ha_state()
