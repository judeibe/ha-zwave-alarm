"""Config flow for the Z-Wave Alarm integration (T035).

Prompts for the service's host/port and the API token issued via
`POST /api/v1/ha-links` (T032), and validates by calling `GET /api/v1/panel`,
per contracts/ha-custom-component.md's "Config flow" section.
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_ACCESS_TOKEN, CONF_HOST, CONF_PORT
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from zwave_alarm_client import CannotConnect, InvalidAuth, async_validate_connection
from .const import CONF_SSL, DEFAULT_PORT, DOMAIN

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_PORT, default=DEFAULT_PORT): int,
        vol.Required(CONF_ACCESS_TOKEN): str,
        vol.Optional(CONF_SSL, default=False): bool,
    }
)

STEP_REAUTH_DATA_SCHEMA = vol.Schema({vol.Required(CONF_ACCESS_TOKEN): str})


class ZwaveAlarmConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Z-Wave Alarm."""

    VERSION = 1

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
                    user_input[CONF_ACCESS_TOKEN],
                    secure=user_input.get(CONF_SSL, False),
                )
            except InvalidAuth:
                errors["base"] = "invalid_auth"
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

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> FlowResult:
        """The stream was refused with 401 (token revoked): ask for a replacement token."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Collect and validate a new API token for the existing entry."""
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()

        if user_input is not None:
            try:
                await async_validate_connection(
                    async_get_clientsession(self.hass),
                    entry.data[CONF_HOST],
                    entry.data[CONF_PORT],
                    user_input[CONF_ACCESS_TOKEN],
                    secure=entry.data.get(CONF_SSL, False),
                )
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            else:
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_ACCESS_TOKEN: user_input[CONF_ACCESS_TOKEN]}
                )

        return self.async_show_form(
            step_id="reauth_confirm", data_schema=STEP_REAUTH_DATA_SCHEMA, errors=errors
        )
