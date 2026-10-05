"""Admin-only websocket commands behind the configuration panel."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_ACCESS_TOKEN, CONF_HOST, CONF_PORT
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

import zwave_alarm_client as api
from custom_components.zwave_alarm.const import CONF_SSL, DOMAIN

API = "custom_components.zwave_alarm.websocket_api.api"
ZONE = {"id": "z1", "name": "Downstairs", "sensors": []}
USER = {"id": "u1", "name": "Alex", "role": "member", "hasCode": True, "haPersonId": "person.alex", "haUserId": None}


@pytest.fixture(autouse=True)
def _enable(enable_custom_integrations):
    """Let HA load custom_components/zwave_alarm."""


@pytest.fixture
async def entry(hass):
    assert await async_setup_component(hass, DOMAIN, {})
    entry = MockConfigEntry(
        domain=DOMAIN, data={CONF_HOST: "svc", CONF_PORT: 3000, CONF_ACCESS_TOKEN: "tok", CONF_SSL: False}
    )
    entry.add_to_hass(hass)
    entry.mock_state(hass, ConfigEntryState.LOADED)
    yield entry
    entry.mock_state(hass, ConfigEntryState.NOT_LOADED)  # never really set up, so don't let teardown unload it


async def _send(client, type_, **payload):
    await client.send_json_auto_id({"type": f"zwave_alarm/{type_}", **payload})
    return await client.receive_json()


async def test_overview(hass, hass_ws_client, entry) -> None:
    hass.states.async_set("person.alex", "home", {"friendly_name": "Alex", "user_id": "abc"})
    with (
        patch(f"{API}.async_get_zones", AsyncMock(return_value=[ZONE])),
        patch(f"{API}.async_list_discoverable_sensors", AsyncMock(return_value=[{"zwaveNodeId": 5}])),
        patch(f"{API}.async_list_users", AsyncMock(return_value=[USER])),
    ):
        resp = await _send(await hass_ws_client(hass), "overview")
    assert resp["success"]
    assert resp["result"]["zones"] == [ZONE]
    assert resp["result"]["discoverable"] == [{"zwaveNodeId": 5}]
    assert resp["result"]["ha_people"] == [{"entity_id": "person.alex", "name": "Alex", "user_id": "abc"}]


async def test_non_admin_is_refused(hass, hass_ws_client, hass_admin_user, entry) -> None:
    hass_admin_user.groups = []  # demote to a non-admin
    with patch(f"{API}.async_get_zones", AsyncMock()) as zones:
        resp = await _send(await hass_ws_client(hass), "overview")
    assert not resp["success"]
    assert resp["error"]["code"] == "unauthorized"
    zones.assert_not_called()


async def test_set_code_passes_code_but_never_returns_it(hass, hass_ws_client, entry) -> None:
    with patch(f"{API}.async_set_user_code", AsyncMock(return_value=None)) as set_code:
        resp = await _send(await hass_ws_client(hass), "user/set_code", user_id="u1", code="123456")
    assert resp["success"] and resp["result"] is None
    assert "123456" not in str(resp)
    assert set_code.await_args.args[-2:] == ("u1", "123456")


@pytest.mark.parametrize("code", ["12", "1234567890123", "12a456", "", 1234])
async def test_set_code_rejects_malformed(hass, hass_ws_client, entry, code) -> None:
    with patch(f"{API}.async_set_user_code", AsyncMock()) as set_code:
        resp = await _send(await hass_ws_client(hass), "user/set_code", user_id="u1", code=code)
    assert not resp["success"] and resp["error"]["code"] == "invalid_code"
    assert resp["error"]["message"] == "The code must be 4 to 12 digits"  # the bad value is never echoed
    set_code.assert_not_called()


@pytest.mark.parametrize(
    ("exc", "code"),
    [
        (api.CodeInUse("dup"), "code_in_use"),
        (api.ZoneNotEmpty("busy"), "zone_not_empty"),
        (api.Conflict("last admin"), "conflict"),
        (api.NotFound("gone"), "not_found"),
        (api.CannotConnect("down"), "cannot_connect"),
    ],
)
async def test_client_errors_map_to_codes(hass, hass_ws_client, entry, exc, code) -> None:
    with patch(f"{API}.async_delete_zone", AsyncMock(side_effect=exc)):
        resp = await _send(await hass_ws_client(hass), "zone/delete", zone_id="z1")
    assert not resp["success"] and resp["error"]["code"] == code


async def test_zone_create_with_description_and_delete_force(hass, hass_ws_client, entry) -> None:
    client = await hass_ws_client(hass)
    with (
        patch(f"{API}.async_create_zone", AsyncMock(return_value=ZONE)),
        patch(f"{API}.async_update_zone", AsyncMock(return_value={**ZONE, "description": "d"})) as update,
        patch(f"{API}.async_delete_zone", AsyncMock(return_value=None)) as delete,
    ):
        resp = await _send(client, "zone/create", name="Downstairs", description="d")
        await _send(client, "zone/delete", zone_id="z1", force=True)
    assert resp["result"]["description"] == "d"
    assert update.await_args.args[-2:] == ("z1", {"description": "d"})
    assert delete.await_args.kwargs["force"] is True


async def test_user_create_links_ha_person_without_code(hass, hass_ws_client, entry) -> None:
    with patch(f"{API}.async_create_user", AsyncMock(return_value=USER)) as create:
        resp = await _send(
            await hass_ws_client(hass), "user/create", name="Alex", role="member", ha_person_id="person.alex"
        )
    assert resp["success"]
    assert create.await_args.args[-3:] == ("Alex", "member", None)
    assert create.await_args.kwargs["ha_person_id"] == "person.alex"


async def test_sensor_update_maps_wire_names(hass, hass_ws_client, entry) -> None:
    with patch(f"{API}.async_update_sensor", AsyncMock(return_value={})) as update:
        await _send(await hass_ws_client(hass), "sensor/update", sensor_id="s1", zone_id="z2", category="intrusion")
    assert update.await_args.args[-2:] == ("s1", {"category": "intrusion", "zoneId": "z2"})


async def test_no_loaded_entry(hass, hass_ws_client) -> None:
    assert await async_setup_component(hass, DOMAIN, {})
    resp = await _send(await hass_ws_client(hass), "overview")
    assert not resp["success"] and resp["error"]["code"] == "entry_not_found"


async def test_panel_registered_admin_only_and_removed_on_unload(hass) -> None:
    from homeassistant.components import frontend

    from custom_components.zwave_alarm.panel import PANEL_URL_PATH, async_register_panel, async_remove_panel

    assert await async_setup_component(hass, "frontend", {})
    with patch("homeassistant.components.http.HomeAssistantHTTP.async_register_static_paths", AsyncMock()):
        await async_register_panel(hass)
        await async_register_panel(hass)  # a second entry must not raise
    panel = hass.data["frontend_panels"][PANEL_URL_PATH]
    assert panel.require_admin is True
    async_remove_panel(hass)
    assert PANEL_URL_PATH not in hass.data["frontend_panels"]
