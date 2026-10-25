"""Admin-only websocket commands behind the configuration panel."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.helpers import device_registry as dr
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

import zwave_alarm_client as api
from custom_components.zwave_alarm.const import CONF_SSL, DOMAIN
from custom_components.zwave_alarm.websocket_api import _zwave_device_names

WS = "custom_components.zwave_alarm.websocket_api"
API = f"{WS}.api"
ZONE = {"id": "z1", "name": "Downstairs", "sensors": []}
OK_SENSOR = {"connectivityStatus": "online", "batteryLevel": 90}
USER = {"id": "u1", "name": "Alex", "role": "member", "hasCode": True, "haPersonId": "person.alex", "haUserId": None}


@pytest.fixture(autouse=True)
def _enable(enable_custom_integrations):
    """Let HA load custom_components/zwave_alarm."""


@pytest.fixture(autouse=True)
def _no_discoverable_locks():
    """Overview also asks for paired-but-not-enrolled locks; default to none so no test reaches the network."""
    with patch(f"{API}.async_list_discoverable_locks", AsyncMock(return_value=[])) as mock:
        yield mock


@pytest.fixture
async def entry(hass):
    assert await async_setup_component(hass, DOMAIN, {})
    entry = MockConfigEntry(
        domain=DOMAIN, data={CONF_HOST: "svc", CONF_PORT: 3000, CONF_SSL: False}
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
    assert resp["result"]["discoverable_error"] is None
    assert resp["result"]["ha_people"] == [{"entity_id": "person.alex", "name": "Alex", "user_id": "abc"}]


async def test_overview_names_sensors_after_their_ha_device(hass, hass_ws_client, entry) -> None:
    registry = dr.async_get(hass)
    registry.async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={("zwave_js", "3458-5")}, name="Hallway door"
    )
    renamed = registry.async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={("zwave_js", "3458-9")}, name="Door sensor"
    )
    registry.async_update_device(renamed.id, name_by_user="Back door")
    zone = {**ZONE, "sensors": [{**OK_SENSOR, "id": "s1", "zwaveNodeId": 9, "name": "stored"}, {**OK_SENSOR, "id": "s2", "zwaveNodeId": 77, "name": "x"}]}
    with (
        patch(f"{API}.async_get_zones", AsyncMock(return_value=[zone])),
        patch(f"{API}.async_list_discoverable_sensors", AsyncMock(return_value=[{"zwaveNodeId": 5}])),
        patch(f"{API}.async_list_users", AsyncMock(return_value=[])),
    ):
        resp = await _send(await hass_ws_client(hass), "overview")
    assert resp["result"]["discoverable"] == [{"zwaveNodeId": 5, "haName": "Hallway door"}]
    sensors = resp["result"]["zones"][0]["sensors"]
    assert sensors[0]["haName"] == "Back door"  # the user's rename wins
    assert "haName" not in sensors[1]  # unknown to HA: the panel falls back to the stored name


async def test_overview_ignores_devices_with_longer_identifiers(hass, hass_ws_client, entry) -> None:
    registry = dr.async_get(hass)
    registry.async_get_or_create(config_entry_id=entry.entry_id, identifiers={("other", "a", "b")}, name="Odd device")
    registry.async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={("zwave_js", "3458-5")}, name="Hallway door"
    )
    with (
        patch(f"{API}.async_get_zones", AsyncMock(return_value=[ZONE])),
        patch(f"{API}.async_list_discoverable_sensors", AsyncMock(return_value=[{"zwaveNodeId": 5}])),
        patch(f"{API}.async_list_users", AsyncMock(return_value=[])),
    ):
        resp = await _send(await hass_ws_client(hass), "overview")
    assert resp["success"]
    assert resp["result"]["discoverable"] == [{"zwaveNodeId": 5, "haName": "Hallway door"}]


@pytest.mark.parametrize("identifier", [(), ("zwave_js",), ("zwave_js", 5), ("zwave_js", None, "x"), "zwave_js", 5])
def test_zwave_device_names_skips_malformed_identifiers(hass, identifier) -> None:
    good = SimpleNamespace(identifiers={("zwave_js", "3458-5")}, name="Hallway door", name_by_user=None)
    bad = SimpleNamespace(identifiers={identifier}, name="Odd device", name_by_user=None)
    registry = SimpleNamespace(devices={"good": good, "bad": bad})
    with patch(f"{WS}.dr.async_get", return_value=registry):
        assert _zwave_device_names(hass) == {5: "Hallway door"}


async def test_overview_summarises_alarm_state_and_faults(hass, hass_ws_client, entry) -> None:
    sensors = [
        {**OK_SENSOR, "id": "s1", "zwaveNodeId": 2, "name": "a"},
        {**OK_SENSOR, "id": "s2", "zwaveNodeId": 3, "name": "b", "connectivityStatus": "offline"},
        {**OK_SENSOR, "id": "s3", "zwaveNodeId": 4, "name": "c", "batteryLevel": 10},
    ]
    coordinator = SimpleNamespace(
        data=SimpleNamespace(panel={"mode": "armed_away", "armedMode": "away", "pendingDelayEndsAt": None})
    )
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    with (
        patch(f"{API}.async_get_zones", AsyncMock(return_value=[{**ZONE, "sensors": sensors}])),
        patch(f"{API}.async_list_discoverable_sensors", AsyncMock(return_value=[])),
        patch(f"{API}.async_list_users", AsyncMock(return_value=[])),
    ):
        resp = await _send(await hass_ws_client(hass), "overview")
    hass.data[DOMAIN].pop(entry.entry_id)
    result = resp["result"]
    assert result["panel"] == {"state": "armed_away", "armed_mode": "away", "pending_delay_ends_at": None}
    assert result["fault_count"] == 2
    assert result["faults"] == {"offline": 1, "low_battery": 1}


async def test_overview_lists_keypads_and_their_settings(hass, hass_ws_client, entry) -> None:
    keypad = {"nodeId": 12, "label": "Ring Keypad v2", "connectivityStatus": "online", "batteryLevel": 87}
    coordinator = SimpleNamespace(
        data=SimpleNamespace(panel=None, keypads=[keypad], keypad_settings={"requireCodeToArm": True})
    )
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    with (
        patch(f"{API}.async_get_zones", AsyncMock(return_value=[])),
        patch(f"{API}.async_list_discoverable_sensors", AsyncMock(return_value=[])),
        patch(f"{API}.async_list_users", AsyncMock(return_value=[])),
    ):
        resp = await _send(await hass_ws_client(hass), "overview")
    hass.data[DOMAIN].pop(entry.entry_id)
    assert resp["result"]["keypads"] == [keypad]
    assert resp["result"]["keypad_settings"] == {"requireCodeToArm": True}


async def test_overview_has_no_keypads_before_the_first_snapshot(hass, hass_ws_client, entry) -> None:
    with (
        patch(f"{API}.async_get_zones", AsyncMock(return_value=[])),
        patch(f"{API}.async_list_discoverable_sensors", AsyncMock(return_value=[])),
        patch(f"{API}.async_list_users", AsyncMock(return_value=[])),
    ):
        resp = await _send(await hass_ws_client(hass), "overview")
    assert resp["result"]["keypads"] == []
    assert resp["result"]["keypad_settings"] is None


async def test_keypad_settings_update_maps_wire_names(hass, hass_ws_client, entry) -> None:
    with patch(f"{API}.async_update_keypad_settings", AsyncMock(return_value={"requireCodeToArm": True})) as update:
        resp = await _send(await hass_ws_client(hass), "keypad_settings/update", require_code_to_arm=True)
    assert resp["success"]
    assert resp["result"] == {"requireCodeToArm": True}
    assert update.await_args.args[-1] == {"requireCodeToArm": True}


async def test_keypad_settings_update_rejects_a_non_boolean(hass, hass_ws_client, entry) -> None:
    resp = await _send(await hass_ws_client(hass), "keypad_settings/update", require_code_to_arm="yes")
    assert not resp["success"]


async def test_overview_has_no_panel_before_the_first_snapshot(hass, hass_ws_client, entry) -> None:
    with (
        patch(f"{API}.async_get_zones", AsyncMock(return_value=[ZONE])),
        patch(f"{API}.async_list_discoverable_sensors", AsyncMock(return_value=[])),
        patch(f"{API}.async_list_users", AsyncMock(return_value=[])),
    ):
        resp = await _send(await hass_ws_client(hass), "overview")
    assert resp["result"]["panel"] is None
    assert resp["result"]["fault_count"] == 0


async def test_overview_degrades_when_the_driver_is_not_ready(hass, hass_ws_client, entry) -> None:
    with (
        patch(f"{API}.async_get_zones", AsyncMock(return_value=[ZONE])),
        patch(f"{API}.async_list_discoverable_sensors", AsyncMock(side_effect=api.ServiceUnavailable("driver not ready"))),
        patch(f"{API}.async_list_users", AsyncMock(return_value=[USER])),
    ):
        resp = await _send(await hass_ws_client(hass), "overview")
    assert resp["success"]
    assert resp["result"]["zones"] == [ZONE] and resp["result"]["users"] == [USER]
    assert resp["result"]["discoverable"] == []
    assert resp["result"]["discoverable_error"] == {"code": "service_unavailable", "message": "driver not ready"}


async def test_overview_still_fails_when_zones_are_unavailable(hass, hass_ws_client, entry) -> None:
    with patch(f"{API}.async_get_zones", AsyncMock(side_effect=api.ServiceUnavailable("driver not ready"))):
        resp = await _send(await hass_ws_client(hass), "overview")
    assert not resp["success"]
    assert resp["error"]["code"] == "service_unavailable"
    assert resp["error"]["message"] == "driver not ready"


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
        (api.ZoneInUse("guest"), "zone_in_use"),
        (api.Conflict("last admin"), "conflict"),
        (api.NotFound("gone"), "not_found"),
        (api.CannotConnect("down"), "cannot_connect"),
        (api.ServiceUnavailable("driver not ready"), "service_unavailable"),
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


async def test_sensor_update_passes_placement_and_armed_flags(hass, hass_ws_client, entry) -> None:
    with patch(f"{API}.async_update_sensor", AsyncMock(return_value={})) as update:
        resp = await _send(
            await hass_ws_client(hass), "sensor/update", sensor_id="s1", placement="ENTRYWAY", armed={"home": False}, alerts_only=True
        )
    assert resp["success"]
    assert update.await_args.args[-2:] == ("s1", {"placement": "ENTRYWAY", "armed": {"home": False}, "alertsOnly": True})


@pytest.mark.parametrize("payload", [{"placement": "GARAGE"}, {"armed": {}}, {"armed": {"home": "yes"}}])
async def test_sensor_update_rejects_bad_placement_or_flags(hass, hass_ws_client, entry, payload) -> None:
    resp = await _send(await hass_ws_client(hass), "sensor/update", sensor_id="s1", **payload)
    assert not resp["success"]


async def test_sensor_assign_sends_placement_in_one_call(hass, hass_ws_client, entry) -> None:
    with patch(f"{API}.async_assign_sensor", AsyncMock(return_value={"id": "s9"})) as assign:
        resp = await _send(
            await hass_ws_client(hass), "sensor/assign", zone_id="z1", zwave_node_id=7, name="Back door", category="intrusion",
            placement="SECONDARY_DOOR", armed={"away": True},
        )
    assert resp["result"] == {"id": "s9"}
    assert assign.await_args.args[-4:] == ("z1", 7, "Back door", "intrusion")
    assert assign.await_args.kwargs == {"placement": "SECONDARY_DOOR", "armed": {"away": True}, "alerts_only": None, "secure": False}


async def test_modes_update_writes_through_the_coordinator(hass, hass_ws_client, entry) -> None:
    update = AsyncMock(return_value={"armed_home": {"entryDelaySec": 90, "exitDelaySec": 60}})
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = SimpleNamespace(async_update_modes=update, data=None)
    resp = await _send(await hass_ws_client(hass), "modes/update", armed_home={"entryDelaySec": 90})
    assert resp["success"]
    update.assert_awaited_once_with({"armed_home": {"entryDelaySec": 90}})


@pytest.mark.parametrize("payload", [{"armed_home": {"entryDelaySec": 181}}, {"armed_away": {"exitDelaySec": -1}}, {"armed_home": {}}, {}])
async def test_modes_update_rejects_bad_delays(hass, hass_ws_client, entry, payload) -> None:
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = SimpleNamespace(async_update_modes=AsyncMock(), data=None)
    resp = await _send(await hass_ws_client(hass), "modes/update", **payload)
    assert not resp["success"]


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


def test_built_panel_bundle_is_shipped() -> None:
    """HACS installs from the repo, so the React bundle must be committed (built from panel/)."""
    from pathlib import Path

    from custom_components.zwave_alarm.panel import PANEL_ELEMENT

    bundle = Path(__file__).parents[1] / "custom_components" / "zwave_alarm" / "frontend" / f"{PANEL_ELEMENT}.js"
    assert bundle.stat().st_size > 10_000
    assert "customElements.define(" in bundle.read_text()
    assert PANEL_ELEMENT in bundle.read_text()


# --- Locks ------------------------------------------------------------------

def _lock(**changes):
    lock = {
        "nodeId": 5, "model": "BE469", "label": "Front Door",
        "supportedSettings": ["beeper", "alarmMode"], "settings": {"pinLength": 4}, "userSlotCount": 30,
        "scheduleSlots": {"weekDay": 7, "yearDay": 0, "dailyRepeating": 7},
        "capabilities": {
            "secure": True, "userCodes": True, "alarmSettings": True,
            "schedules": {"weekDay": True, "yearDay": False, "dailyRepeating": True},
        },
    }
    return {**lock, **changes}


def _caps(**schedules):
    """Capabilities for a secure lock with the given schedule flags (anything unnamed is `None`, not reported yet)."""
    flags = {"weekDay": None, "yearDay": None, "dailyRepeating": None, **schedules}
    return {"secure": True, "userCodes": True, "alarmSettings": False, "schedules": flags}


@pytest.fixture
def with_locks(hass, entry):
    def _set(*locks):
        hass.data.setdefault(DOMAIN, {})[entry.entry_id] = SimpleNamespace(
            data=SimpleNamespace(panel={"mode": "disarmed"}, keypads=[], locks=list(locks))
        )
    yield _set
    hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)


async def test_overview_lists_enrolled_locks_with_capabilities_and_offers_paired_ones(
    hass, hass_ws_client, entry, with_locks, _no_discoverable_locks
) -> None:
    with_locks(_lock())
    _no_discoverable_locks.return_value = [{"nodeId": 6, "model": "BE469", "label": "Paired", "connectivityStatus": "online", "secure": True}]
    with (
        patch(f"{API}.async_get_zones", AsyncMock(return_value=[])),
        patch(f"{API}.async_list_discoverable_sensors", AsyncMock(return_value=[])),
        patch(f"{API}.async_list_users", AsyncMock(return_value=[])),
    ):
        resp = await _send(await hass_ws_client(hass), "overview")
    assert [lock["nodeId"] for lock in resp["result"]["locks"]] == [5]
    caps = resp["result"]["locks"][0]["capabilities"]
    assert caps["schedules"] == {"weekDay": True, "yearDay": False, "dailyRepeating": True} and caps["userSlots"] == 30
    assert [lock["nodeId"] for lock in resp["result"]["discoverable_locks"]] == [6]


async def test_overview_tolerates_a_service_without_lock_enrolment(hass, hass_ws_client, entry, with_locks, _no_discoverable_locks) -> None:
    with_locks()
    _no_discoverable_locks.side_effect = api.NotFound("no such route")
    with (
        patch(f"{API}.async_get_zones", AsyncMock(return_value=[])),
        patch(f"{API}.async_list_discoverable_sensors", AsyncMock(return_value=[])),
        patch(f"{API}.async_list_users", AsyncMock(return_value=[])),
    ):
        resp = await _send(await hass_ws_client(hass), "overview")
    assert resp["success"] and resp["result"]["discoverable_locks"] == []
    assert resp["result"]["discoverable_locks_error"] is None


async def test_lock_enroll_and_unenroll_call_the_service(hass, hass_ws_client, entry) -> None:
    enroll = AsyncMock(return_value=_lock())
    unenroll = AsyncMock(return_value={"nodeId": 5, "cleared": True, "failures": []})  # the client's UnenrollResult
    with patch(f"{API}.async_enroll_lock", enroll), patch(f"{API}.async_unenroll_lock", unenroll):
        client = await hass_ws_client(hass)
        assert (await _send(client, "lock/enroll", node_id=5))["success"]
        resp = await _send(client, "lock/unenroll", node_id=5)
    assert resp["result"] == {"node_id": 5, "cleared": True, "failures": []}
    assert enroll.await_args.args[-1] == 5 and unenroll.await_args.args[-1] == 5


async def test_lock_unenroll_reports_when_the_lock_could_not_be_cleared(hass, hass_ws_client, entry) -> None:
    failures = ["user code 3: lock did not answer"]
    unenroll = AsyncMock(return_value={"nodeId": 5, "cleared": False, "failures": failures})
    with patch(f"{API}.async_unenroll_lock", unenroll):
        resp = await _send(await hass_ws_client(hass), "lock/unenroll", node_id=5)
    assert resp["success"] and resp["result"] == {"node_id": 5, "cleared": False, "failures": failures}


async def test_schedule_kind_unsupported_has_its_own_error_code(hass, hass_ws_client, entry, with_locks) -> None:
    with_locks(_lock())
    setter = AsyncMock(side_effect=api.ScheduleKindUnsupported("no slots"))
    week = {"weekday": 1, "startHour": 8, "startMinute": 0, "stopHour": 17, "stopMinute": 0}
    with patch(f"{API}.async_set_lock_schedule", setter):
        resp = await _send(await hass_ws_client(hass), "lock/schedule/set", node_id=5, user_id=1, kind="weekDay", slot_id=1, schedule=week)
    assert resp["error"]["code"] == "schedule_kind_unsupported"


async def test_lock_enroll_maps_a_lock_included_without_security(hass, hass_ws_client, entry) -> None:
    with patch(f"{API}.async_enroll_lock", AsyncMock(side_effect=api.LockNotSecure("no S2"))):
        resp = await _send(await hass_ws_client(hass), "lock/enroll", node_id=5)
    assert resp["error"]["code"] == "lock_not_secure"


async def test_lock_codes_and_schedules_refuse_a_lock_known_to_be_insecure(hass, hass_ws_client, entry, with_locks) -> None:
    insecure = _lock()
    insecure["capabilities"] = {**insecure["capabilities"], "secure": False}
    with_locks(insecure)
    client = await hass_ws_client(hass)
    assert (await _send(client, "lock/user/set_code", node_id=5, user_id=1, code="1234"))["error"]["code"] == "lock_not_secure"
    assert (await _send(client, "lock/schedules", node_id=5, user_id=1))["error"]["code"] == "lock_not_secure"


async def test_lock_commands_refuse_a_lock_that_is_not_enrolled(hass, hass_ws_client, entry, with_locks) -> None:
    with_locks(_lock(nodeId=6))  # only node 6 is enrolled; 5 is merely paired
    set_code = AsyncMock()
    with patch(f"{API}.async_set_lock_user_code", set_code):
        client = await hass_ws_client(hass)
        for node_id in (5, 99):
            resp = await _send(client, "lock/user/set_code", node_id=node_id, user_id=1, code="1234")
            assert resp["error"]["code"] == "lock_not_enrolled"
    set_code.assert_not_awaited()


async def test_lock_set_code_checks_slots_and_passes_the_pin_length(hass, hass_ws_client, entry, with_locks) -> None:
    with_locks(_lock(settings={"pinLength": 6}))
    set_code = AsyncMock(return_value={"userId": 2, "status": "enabled"})
    with patch(f"{API}.async_set_lock_user_code", set_code):
        client = await hass_ws_client(hass)
        ok = await _send(client, "lock/user/set_code", node_id=5, user_id=2, code="123456", status="enabled")
        too_many = await _send(client, "lock/user/set_code", node_id=5, user_id=31, code="123456")
    assert ok["success"] and (set_code.await_args.kwargs["status"], set_code.await_args.kwargs["pin_length"]) == ("enabled", 6)
    assert too_many["error"]["code"] == "lock_unsupported"
    assert set_code.await_count == 1


async def test_lock_code_is_never_echoed_in_errors(hass, hass_ws_client, entry, with_locks) -> None:
    with_locks(_lock())
    resp = await _send(await hass_ws_client(hass), "lock/user/set_code", node_id=5, user_id=1, code="12")
    assert resp["error"]["code"] == "invalid_code" and "12" not in resp["error"]["message"].replace("4 to 12", "")


async def test_lock_schedule_commands_are_gated_by_capability(hass, hass_ws_client, entry, with_locks) -> None:
    with_locks(_lock())  # BE469ZP-style: no year-day slots
    setter = AsyncMock()
    week = {"weekday": 1, "startHour": 8, "startMinute": 0, "stopHour": 17, "stopMinute": 0}
    with patch(f"{API}.async_set_lock_schedule", setter):
        client = await hass_ws_client(hass)
        year = await _send(client, "lock/schedule/set", node_id=5, user_id=1, kind="yearDay", slot_id=1, schedule={})
        past_end = await _send(client, "lock/schedule/set", node_id=5, user_id=1, kind="weekDay", slot_id=8, schedule=week)
        ok = await _send(client, "lock/schedule/set", node_id=5, user_id=1, kind="weekDay", slot_id=7, schedule=week)
    assert year["error"]["code"] == "lock_unsupported" and past_end["error"]["code"] == "lock_unsupported"
    assert ok["success"] and setter.await_count == 1
    assert setter.await_args.args[-4:] == (1, "weekDay", 7, week)


async def test_lock_schedule_kind_not_reported_yet_is_not_writable(hass, hass_ws_client, entry, with_locks) -> None:
    with_locks(_lock(capabilities=_caps(weekDay=True), scheduleSlots={"weekDay": 2}))
    setter = AsyncMock()
    with patch(f"{API}.async_set_lock_schedule", setter):
        resp = await _send(await hass_ws_client(hass), "lock/schedule/set", node_id=5, user_id=1, kind="dailyRepeating", slot_id=1, schedule={})
    assert resp["error"]["code"] == "lock_schedule_unknown"
    setter.assert_not_awaited()


async def test_lock_schedules_reads_only_supported_kinds_and_names_unreported_ones(hass, hass_ws_client, entry, with_locks) -> None:
    with_locks(_lock(capabilities=_caps(weekDay=True, yearDay=False), scheduleSlots={"weekDay": 2, "yearDay": 0}))
    get = AsyncMock(side_effect=lambda *a, **k: {"kind": a[-2], "userId": a[-3], "slotId": a[-1], "schedule": None})
    with patch(f"{API}.async_get_lock_schedule", get):
        resp = await _send(await hass_ws_client(hass), "lock/schedules", node_id=5, user_id=1)
    assert resp["result"] == {
        "user_id": 1, "unknown": ["dailyRepeating"],
        "kinds": {"weekDay": [{"slot_id": 1, "schedule": None}, {"slot_id": 2, "schedule": None}]},
    }
    assert get.await_count == 2


async def test_lock_without_schedules_rejects_schedule_reads(hass, hass_ws_client, entry, with_locks) -> None:
    with_locks(_lock(capabilities=_caps(weekDay=False, yearDay=False, dailyRepeating=False)))
    client = await hass_ws_client(hass)
    assert (await _send(client, "lock/schedules", node_id=5, user_id=1))["error"]["code"] == "lock_unsupported"
    assert (await _send(client, "lock/schedule/enabled", node_id=5, user_id=1, enabled=True))["error"]["code"] == "lock_unsupported"


async def test_lock_settings_reject_unsupported_keys_and_map_unavailable(hass, hass_ws_client, entry, with_locks) -> None:
    with_locks(_lock())
    update = AsyncMock(side_effect=api.LockUnavailable("asleep"))
    with patch(f"{API}.async_update_lock_settings", update):
        client = await hass_ws_client(hass)
        bad = await _send(client, "lock/settings", node_id=5, settings={"kickSensitivity": 3})
        asleep = await _send(client, "lock/settings", node_id=5, settings={"beeper": True})
    assert bad["error"]["code"] == "lock_unsupported"
    assert asleep["error"]["code"] == "lock_unavailable"


async def test_arm_returns_the_faulted_sensors_instead_of_an_error(hass, hass_ws_client, entry) -> None:
    faulted = [{"sensorId": "s1", "name": "Front door", "zoneId": "z1", "reason": "open"}]
    with patch(f"{API}.async_arm", AsyncMock(side_effect=api.NeedsBypass("faulted", faulted))):
        resp = await _send(await hass_ws_client(hass), "arm", mode="armed_away")
    assert resp["success"]
    assert resp["result"] == {"needs_bypass": faulted}


async def test_arm_resends_with_bypass_and_the_app_source(hass, hass_ws_client, entry) -> None:
    with patch(f"{API}.async_arm", AsyncMock(return_value={"mode": "arming"})) as arm:
        resp = await _send(await hass_ws_client(hass), "arm", mode="armed_home", bypass=["s1"])
    assert resp["result"] == {"needs_bypass": []}
    assert arm.await_args.args[-3:] == ("armed_home", ["s1"], "app")


async def test_arm_rejects_disarmed_as_a_mode(hass, hass_ws_client, entry) -> None:
    resp = await _send(await hass_ws_client(hass), "arm", mode="disarmed")
    assert not resp["success"]
