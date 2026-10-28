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
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import selector

from .const import CONF_SHOW_IN_SIDEBAR, CONF_SSL, DEFAULT_PORT, DOMAIN
from .sensor_settings import (
    CHIME_SOUNDS,
    SENSOR_KINDS,
    SUBENTRY_SENSOR,
    has_chime,
    settings_from_sensor,
    to_wire,
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


def _select(options: list[str], key: str) -> selector.SelectSelector:
    return selector.SelectSelector(
        selector.SelectSelectorConfig(options=options, translation_key=key, mode=selector.SelectSelectorMode.DROPDOWN)
    )


def _sensor_schema(defaults: dict[str, Any], chime: bool) -> vol.Schema:
    fields: dict[Any, Any] = {
        vol.Required("sensor_kind", default=defaults["sensor_kind"]): _select(SENSOR_KINDS, "sensor_kind"),
        vol.Optional("entryway", description={"suggested_value": defaults["entryway"]}): vol.All(str, vol.Length(max=60)),
        vol.Required("is_interior", default=defaults["is_interior"]): bool,
        vol.Required("quick_entry_supported", default=defaults["quick_entry_supported"]): bool,
    }
    if chime:  # life-safety sensors have no chime and the service rejects the fields
        fields[vol.Required("chime_enabled", default=defaults["chime_enabled"])] = bool
        fields[vol.Required("chime_sound", default=defaults["chime_sound"])] = _select(CHIME_SOUNDS, "chime_sound")
    return vol.Schema(fields)


class SensorSubentryFlow(ConfigSubentryFlow):
    """Add a supported sensor as its own entry, or reconfigure its chime, kind (door/window/interior) and entryway."""

    _sensor_id: str | None = None

    def _sensors(self) -> list[dict[str, Any]]:
        coordinator = self.hass.data.get(DOMAIN, {}).get(self._get_entry().entry_id)
        data = getattr(coordinator, "data", None)
        return [s for z in (data.zones if data else []) for s in z["sensors"]]

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        taken = {sub.unique_id for sub in self._get_entry().subentries.values()}
        choices = {s["id"]: s["name"] for s in self._sensors() if s["id"] not in taken}
        if not choices:
            return self.async_abort(reason="no_supported_sensors")
        if user_input is not None:
            self._sensor_id = user_input["sensor_id"]
            return await self.async_step_settings()
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {vol.Required("sensor_id"): selector.SelectSelector(selector.SelectSelectorConfig(
                    options=[selector.SelectOptionDict(value=k, label=v) for k, v in choices.items()]))}
            ),
        )

    async def async_step_settings(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        sensor = next((s for s in self._sensors() if s["id"] == self._sensor_id), None)
        if sensor is None:
            return self.async_abort(reason="sensor_gone")
        errors: dict[str, str] = {}
        if user_input is not None:
            coordinator = self.hass.data[DOMAIN][self._get_entry().entry_id]
            try:
                await coordinator.async_update_sensor_settings(sensor["id"], to_wire(user_input))
            except ServiceValidationError:  # incl. UnsupportedDevice / CategoryMismatch, mapped by the coordinator
                errors["base"] = "rejected"
            except Exception:  # the service rejected the change or is unreachable; keep the form open
                _LOGGER.debug("Could not save sensor settings", exc_info=True)
                errors["base"] = "save_failed"
            else:
                if self.source == config_entries.SOURCE_RECONFIGURE:
                    return self.async_update_and_abort(
                        self._get_entry(), self._get_reconfigure_subentry(), title=sensor["name"], data=user_input
                    )
                return self.async_create_entry(title=sensor["name"], data=user_input, unique_id=sensor["id"])
        defaults = {**settings_from_sensor(sensor), **(user_input or {})}
        return self.async_show_form(
            step_id="settings", data_schema=_sensor_schema(defaults, has_chime(sensor)), errors=errors, description_placeholders={"sensor": sensor["name"]}
        )

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        self._sensor_id = self._get_reconfigure_subentry().unique_id
        return await self.async_step_settings(user_input)
