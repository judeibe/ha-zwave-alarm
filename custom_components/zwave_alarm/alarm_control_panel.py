"""The `alarm_control_panel.zwave_alarm` entity (T036).

Maps `AlarmPanel.mode` (src/alarm/panel-repository.ts) to Home Assistant's
standard `alarm_control_panel` states and implements `arm_away`/`arm_home`/
`disarm` services against Phase 02's REST endpoints, per
contracts/ha-custom-component.md's "Entities exposed to Home Assistant"
section.

As of T039, this is a `CoordinatorEntity` built on the WebSocket-driven
`ZwaveAlarmCoordinator` (coordinator.py) rather than a polling entity: state
comes from `coordinator.data.panel`, and `available` mirrors the
coordinator's own connectivity (`last_update_success`), so this entity is
pushed to immediately on `panel.changed` and never reports a stale/assumed
state -- including `disarmed` -- while the coordinator is disconnected, per
the contract's "Failure handling" section (FR-006).
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from homeassistant.components.alarm_control_panel import (
    AlarmControlPanelEntity,
    AlarmControlPanelEntityFeature,
    AlarmControlPanelState,
    CodeFormat,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ACCESS_TOKEN, CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity import DeviceInfo, async_generate_entity_id
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

import zwave_alarm_client as api
from .const import CONF_SSL, DOMAIN
from .coordinator import ZwaveAlarmCoordinator
from .coordinator_state import StreamState, merge_panel
from .panel_state import map_panel_mode, panel_attributes

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the alarm_control_panel entity for a config entry."""
    coordinator: ZwaveAlarmCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([ZwaveAlarmControlPanel(coordinator, entry)])


class ZwaveAlarmControlPanel(
    CoordinatorEntity[ZwaveAlarmCoordinator], AlarmControlPanelEntity
):
    """Represents this service's AlarmPanel singleton as an HA alarm_control_panel."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_supported_features = (
        AlarmControlPanelEntityFeature.ARM_HOME
        | AlarmControlPanelEntityFeature.ARM_AWAY
    )
    # POST /api/v1/panel/arm takes no code (contracts/rest-api.md); disarm
    # always requires the caller's own code.
    _attr_code_arm_required = False
    _attr_code_format = CodeFormat.TEXT

    def __init__(self, coordinator: ZwaveAlarmCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._host: str = entry.data[CONF_HOST]
        self._port: int = entry.data[CONF_PORT]
        self._token: str = entry.data[CONF_ACCESS_TOKEN]
        self._secure: bool = entry.data.get(CONF_SSL, False)
        self._attr_unique_id = f"{entry.entry_id}_panel"
        # Explicit entity_id so it is the contract's `alarm_control_panel.zwave_alarm`
        # rather than the slug of the device name (`z_wave_alarm`).
        self.entity_id = async_generate_entity_id("alarm_control_panel.{}", "zwave_alarm", hass=coordinator.hass)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Z-Wave Alarm",
            manufacturer="Z-Wave Alarm",
        )

    @property
    def alarm_state(self) -> AlarmControlPanelState | None:
        """Current alarm state from the coordinator's cached data, or `None` before any snapshot arrives."""
        panel = (
            self.coordinator.data.panel if self.coordinator.data is not None else None
        )
        return (
            AlarmControlPanelState(map_panel_mode(panel["mode"]))
            if panel is not None
            else None
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Armed mode, pending delay, zones a zone-restricted guest disarmed, and what triggered the alarm."""
        data = self.coordinator.data
        if data is None or data.panel is None:
            return None
        return panel_attributes(data.panel, data.zones)

    async def async_alarm_arm_away(self, code: str | None = None) -> None:
        """Arm away via `POST /api/v1/panel/arm`."""
        await self._async_call(api.async_arm, mode="armed_away")

    async def async_alarm_arm_home(self, code: str | None = None) -> None:
        """Arm home via `POST /api/v1/panel/arm`."""
        await self._async_call(api.async_arm, mode="armed_home")

    async def async_alarm_disarm(self, code: str | None = None) -> None:
        """Disarm via `POST /api/v1/panel/disarm`; a code is always required."""
        if not code:
            raise ServiceValidationError("A code is required to disarm this alarm.")
        await self._async_call(api.async_disarm, code=code)

    async def _async_call(
        self, func: Callable[..., Awaitable[dict[str, Any]]], **kwargs: Any
    ) -> None:
        """Invoke a zwave_alarm_client arm/disarm call and feed the returned AlarmPanel state into the coordinator.

        Updating the coordinator (rather than just this entity) makes the
        result visible immediately, without waiting for the WebSocket's own
        `panel.changed` echo of the same change to arrive and round-trip
        back through `_handle_message`.
        """
        session = async_get_clientsession(self.hass)
        try:
            panel = await func(
                session, self._host, self._port, self._token, secure=self._secure, **kwargs
            )
        except api.InvalidAuth as err:
            raise ServiceValidationError(
                "The Z-Wave Alarm service rejected the Home Assistant token or code."
            ) from err
        except api.AccountLocked as err:
            raise HomeAssistantError(
                "This account is locked from repeated invalid codes. Try again later."
            ) from err
        except api.Forbidden as err:
            raise HomeAssistantError(
                "The Z-Wave Alarm service does not allow this action for the Home Assistant link."
            ) from err
        except api.TooManyRequests as err:
            raise HomeAssistantError(
                "The Z-Wave Alarm service is rate limiting requests. Try again shortly."
            ) from err
        except api.CommandRejected as err:
            raise HomeAssistantError(
                "The Z-Wave Alarm service rejected this command in favor of a conflicting request."
            ) from err
        except api.CannotConnect as err:
            raise HomeAssistantError(
                "Could not reach the Z-Wave Alarm service."
            ) from err
        except api.ZwaveAlarmError as err:
            raise HomeAssistantError(f"The Z-Wave Alarm service rejected the request: {err}") from err

        current = (
            self.coordinator.data
            if self.coordinator.data is not None
            else StreamState(panel=None, zones=[])
        )
        self.coordinator.async_set_updated_data(merge_panel(current, panel))
