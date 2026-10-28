"""Config flow for the Z-Wave Alarm integration (T035).

Prompts for the service's host/port only (no authentication is required) and
validates by calling `GET /api/v1/panel`, per contracts/ha-custom-component.md's
"Config flow" section.
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigSubentryFlow, SubentryFlowResult
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from zwave_alarm_client import CannotConnect, async_validate_connection
from homeassistant.helpers import selector

from .const import CONF_SHOW_IN_SIDEBAR, CONF_SSL, DEFAULT_PORT, DOMAIN
from .sensor_settings import (
    SUBENTRY_SENSOR,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_PORT, default=DEFAULT_PORT): int,
        vol.Optional(CONF_SSL, default=False): bool,
    }
)


class ZwaveAlarmConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Z-Wave Alarm."""

    VERSION = 2

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> ZwaveAlarmOptionsFlow:
        return ZwaveAlarmOptionsFlow()

    @classmethod
    @callback
    def async_get_supported_subentry_types(cls, config_entry: config_entries.ConfigEntry) -> dict[str, type[ConfigSubentryFlow]]:
        """One `sensor` subentry per Ring-supported sensor (quick entry is a sensor setting on the service)."""
        return {SUBENTRY_SENSOR: SensorSubentryFlow}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Handle the (only) step: collect connection details and validate them."""
        errors: dict[str, str] = {}

        if user_input is not None:
            session = async_get_clientsession(self.hass)
            try:
                await async_validate_connection(
                    session,
                    user_input[CONF_HOST],
                    user_input[CONF_PORT],
                    None,
                    secure=user_input.get(CONF_SSL, False),
                )
            except CannotConnect:
                _LOGGER.debug("Cannot connect to Z-Wave Alarm service", exc_info=True)
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(f"{user_input[CONF_HOST]}:{user_input[CONF_PORT]}")
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=user_input[CONF_HOST], data=user_input)

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )


class ZwaveAlarmOptionsFlow(config_entries.OptionsFlow):
    """Options: whether the configuration panel appears in the sidebar."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        current = self.config_entry.options.get(CONF_SHOW_IN_SIDEBAR, True)
        return self.async_show_form(
            step_id="init", data_schema=vol.Schema({vol.Required(CONF_SHOW_IN_SIDEBAR, default=current): bool})
        )


class SensorSubentryFlow(ConfigSubentryFlow):
    """Add a supported sensor as its own entry (device); everything else is configured on that device."""

    def _sensors(self) -> list[dict[str, Any]]:
        coordinator = self.hass.data.get(DOMAIN, {}).get(self._get_entry().entry_id)
        data = getattr(coordinator, "data", None)
        return [s for z in (data.zones if data else []) for s in z["sensors"]]

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        """Pick which sensor to add. Its settings live as entities on the sensor's device, not in this flow."""
        taken = {sub.unique_id for sub in self._get_entry().subentries.values()}
        choices = {s["id"]: s["name"] for s in self._sensors() if s["id"] not in taken}
        if not choices:
            return self.async_abort(reason="no_supported_sensors")
        if user_input is not None:
            return self.async_create_entry(title=choices[user_input["sensor_id"]], data={}, unique_id=user_input["sensor_id"])
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {vol.Required("sensor_id"): selector.SelectSelector(selector.SelectSelectorConfig(
                    options=[selector.SelectOptionDict(value=k, label=v) for k, v in choices.items()]))}
            ),
        )
