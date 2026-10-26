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
    with patch(f"{API}.async_set_user_code", AsyncMock(return_value=[])) as set_code:
        resp = await _send(await hass_ws_client(hass), "user/set_code", user_id="u1", code="1234", confirm_code="1234")
    assert resp["success"] and resp["result"] == {"lock_sync": []}
    assert "1234" not in str(resp)
    assert set_code.await_args.args[-3:] == ("u1", "1234", "1234")


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
    assert assign.await_args.kwargs == {"placement": "SECONDARY_DOOR", "armed": {"away": True}, "alerts_only": None, "chirp_tone": None, "secure": False}


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


async def test_panic_command_raises_the_alarm_through_the_coordinator(hass, hass_ws_client, entry) -> None:
    panic = AsyncMock(return_value={"id": "e1", "type": "PANIC"})
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = SimpleNamespace(async_panic=panic, data=None)
    resp = await _send(await hass_ws_client(hass), "panic", kind="SOS", service="medical")
    assert resp["result"] == {"id": "e1", "type": "PANIC"}
    panic.assert_awaited_once_with("SOS", "medical")


async def test_panic_command_rejects_an_unknown_kind(hass, hass_ws_client, entry) -> None:
    resp = await _send(await hass_ws_client(hass), "panic", kind="BURGLARY")
    assert not resp["success"]


async def test_silence_command_returns_the_silenced_events(hass, hass_ws_client, entry) -> None:
    silence = AsyncMock(return_value=[{"id": "e1", "sirenState": "silenced"}])
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = SimpleNamespace(async_silence=silence, data=None)
    resp = await _send(await hass_ws_client(hass), "silence")
    assert resp["result"] == {"silenced": [{"id": "e1", "sirenState": "silenced"}]}


async def test_overview_lists_the_open_alarm_events(hass, hass_ws_client, entry) -> None:
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = SimpleNamespace(
        data=SimpleNamespace(alarm_events=[{"id": "e1"}], keypads=[], keypad_settings=None, modes=None, panel=None, locks=[])
    )
    with (
        patch(f"{API}.async_get_zones", AsyncMock(return_value=[])),
        patch(f"{API}.async_list_discoverable_sensors", AsyncMock(return_value=[])),
        patch(f"{API}.async_list_users", AsyncMock(return_value=[])),
    ):
        resp = await _send(await hass_ws_client(hass), "overview")
    assert resp["result"]["alarm_events"] == [{"id": "e1"}]


async def test_siren_put_maps_wire_names(hass, hass_ws_client, entry) -> None:
    with patch(f"{API}.async_put_siren", AsyncMock(return_value={"nodeId": 14})) as put:
        resp = await _send(await hass_ws_client(hass), "siren/put", node_id=14, kind="OUTDOOR", name="Garden", duration_sec=120)
    assert resp["result"] == {"nodeId": 14}
    assert put.await_args.args[-4:] == (14, "OUTDOOR", "Garden", 120)


@pytest.mark.parametrize(
    "payload",
    [{"kind": "BASE", "duration_sec": 120}, {"kind": "OUTDOOR", "duration_sec": 30}, {"kind": "OUTDOOR", "duration_sec": 601}, {"kind": "SPEAKER"}],
)
async def test_siren_put_rejects_a_bad_duration_or_kind(hass, hass_ws_client, entry, payload) -> None:
    with patch(f"{API}.async_put_siren", AsyncMock()) as put:
        resp = await _send(await hass_ws_client(hass), "siren/put", node_id=14, **payload)
    assert not resp["success"]
    put.assert_not_awaited()


async def test_siren_delete_calls_the_service(hass, hass_ws_client, entry) -> None:
    with patch(f"{API}.async_delete_siren", AsyncMock(return_value=None)) as delete:
        resp = await _send(await hass_ws_client(hass), "siren/delete", node_id=14)
    assert resp["success"]
    assert delete.await_args.args[-1] == 14


async def test_overview_lists_the_enrolled_sirens(hass, hass_ws_client, entry) -> None:
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = SimpleNamespace(
        data=SimpleNamespace(sirens=[{"nodeId": 14}], alarm_events=[], keypads=[], keypad_settings=None, modes=None, panel=None, locks=[])
    )
    with (
        patch(f"{API}.async_get_zones", AsyncMock(return_value=[])),
        patch(f"{API}.async_list_discoverable_sensors", AsyncMock(return_value=[])),
        patch(f"{API}.async_list_users", AsyncMock(return_value=[])),
    ):
        resp = await _send(await hass_ws_client(hass), "overview")
    assert resp["result"]["sirens"] == [{"nodeId": 14}]


@pytest.mark.parametrize("code", ["12345", "123456789", "123"])
async def test_a_persons_code_must_be_exactly_four_digits(hass, hass_ws_client, entry, code) -> None:
    # Passes the 4-12 digit wire check (locks use it) but not the people rule; the value is never echoed.
    with patch(f"{API}.async_set_user_code", AsyncMock()) as set_code:
        resp = await _send(await hass_ws_client(hass), "user/set_code", user_id="u1", code=code)
    assert not resp["success"] and resp["error"]["code"] == "invalid_code"
    assert code not in str(resp)
    set_code.assert_not_called()


async def test_a_confirm_code_must_also_be_four_digits(hass, hass_ws_client, entry) -> None:
    with patch(f"{API}.async_set_user_code", AsyncMock()) as set_code:
        resp = await _send(await hass_ws_client(hass), "user/set_code", user_id="u1", code="1234", confirm_code="99999")
    assert resp["error"]["code"] == "invalid_code" and "99999" not in str(resp)
    set_code.assert_not_called()


async def test_user_create_sends_confirm_code_and_accepts_the_installer_role(hass, hass_ws_client, entry) -> None:
    with patch(f"{API}.async_create_user", AsyncMock(return_value={"id": "u9", "role": "installer"})) as create:
        resp = await _send(await hass_ws_client(hass), "user/create", name="Pat", role="installer", code="4321", confirm_code="4321")
    assert resp["result"] == {"id": "u9", "role": "installer"}
    assert create.await_args.kwargs["confirm_code"] == "4321"
    assert create.await_args.args[-3:] == ("Pat", "installer", "4321")


async def test_duress_code_commands_call_the_service_and_never_echo_the_code(hass, hass_ws_client, entry) -> None:
    with patch(f"{API}.async_set_duress_code", AsyncMock(return_value=None)) as put:
        resp = await _send(await hass_ws_client(hass), "user/set_duress_code", user_id="u1", code="2468", confirm_code="2468")
    assert resp["success"] and "2468" not in str(resp)
    assert put.await_args.args[-3:] == ("u1", "2468", "2468")
    with patch(f"{API}.async_delete_duress_code", AsyncMock(return_value=None)) as delete:
        resp = await _send(await hass_ws_client(hass), "user/clear_duress_code", user_id="u1")
    assert resp["success"] and delete.await_args.args[-1] == "u1"


@pytest.mark.parametrize(
    ("exc", "code"),
    [(api.CodeLimit("full"), "code_limit"), (api.CodeInUse("dup"), "code_in_use"), (api.TooManyRequests("slow"), "too_many_requests")],
)
async def test_code_errors_map_to_their_own_codes(hass, hass_ws_client, entry, exc, code) -> None:
    with patch(f"{API}.async_set_duress_code", AsyncMock(side_effect=exc)):
        resp = await _send(await hass_ws_client(hass), "user/set_duress_code", user_id="u1", code="2468")
    assert resp["error"]["code"] == code


async def test_guest_schedule_list_and_delete_call_the_service(hass, hass_ws_client, entry) -> None:
    with patch(f"{API}.async_get_guest_schedules", AsyncMock(return_value=[{"id": "s1"}])) as get:
        resp = await _send(await hass_ws_client(hass), "guest_schedule/list", user_id="g1")
    assert resp["result"] == [{"id": "s1"}] and get.await_args.args[-1] == "g1"
    with patch(f"{API}.async_delete_guest_schedule", AsyncMock(return_value=None)) as delete:
        resp = await _send(await hass_ws_client(hass), "guest_schedule/delete", user_id="g1", schedule_id="s1")
    assert resp["success"] and delete.await_args.args[-2:] == ("g1", "s1")


async def test_guest_schedule_create_goes_through_the_coordinator_with_trimmed_times(hass, hass_ws_client, entry) -> None:
    create = AsyncMock(return_value={"id": "s1"})
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = SimpleNamespace(async_create_guest_schedule=create, data=None)
    resp = await _send(
        await hass_ws_client(hass), "guest_schedule/create", user_id="g1", name="Cleaners", days=["mon"], start="08:00:00", end="17:30"
    )
    assert resp["result"] == {"id": "s1"}
    create.assert_awaited_once_with("g1", "Cleaners", ["mon"], start="08:00", end="17:30")


@pytest.mark.parametrize(
    "payload",
    [{"days": []}, {"days": ["funday"]}, {"days": ["mon"], "start": "08:00"}, {"days": ["mon"], "start": "9", "end": "10:00"}],
)
async def test_guest_schedule_create_rejects_a_bad_schedule(hass, hass_ws_client, entry, payload) -> None:
    create = AsyncMock()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = SimpleNamespace(async_create_guest_schedule=create, data=None)
    resp = await _send(await hass_ws_client(hass), "guest_schedule/create", user_id="g1", name="x", **payload)
    assert not resp["success"]
    create.assert_not_awaited()


async def test_guest_schedule_update_sends_only_the_changed_fields(hass, hass_ws_client, entry) -> None:
    with patch(f"{API}.async_update_guest_schedule", AsyncMock(return_value={"id": "s1"})) as update:
        resp = await _send(await hass_ws_client(hass), "guest_schedule/update", user_id="g1", schedule_id="s1", all_day=False)
    assert resp["success"]  # the service re-checks it against the stored schedule
    assert update.await_args.args[-2:] == ("g1", "s1") and update.await_args.kwargs["all_day"] is False
    resp = await _send(await hass_ws_client(hass), "guest_schedule/update", user_id="g1", schedule_id="s1")
    assert not resp["success"]


async def test_events_command_maps_filters_to_the_client(hass, hass_ws_client, entry) -> None:
    with patch(f"{API}.async_get_events", AsyncMock(return_value=[{"id": "e1"}])) as get:
        resp = await _send(
            await hass_ws_client(hass), "events", event_type=["tamper", "code_added"], device_id="s1", before="e9", limit=50, since=5
        )
    assert resp["result"] == [{"id": "e1"}]
    assert get.await_args.kwargs == {"type": ["tamper", "code_added"], "device_id": "s1", "before": "e9", "limit": 50, "since": 5, "secure": False}


@pytest.mark.parametrize("payload", [{"limit": 0}, {"limit": 501}, {"since": -1}])
async def test_events_command_rejects_bad_limits(hass, hass_ws_client, entry, payload) -> None:
    with patch(f"{API}.async_get_events", AsyncMock()) as get:
        resp = await _send(await hass_ws_client(hass), "events", **payload)
    assert not resp["success"]
    get.assert_not_awaited()


async def test_mode_schedule_create_trims_the_time_and_goes_through_the_coordinator(hass, hass_ws_client, entry) -> None:
    create = AsyncMock(return_value={"id": "m1"})
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = SimpleNamespace(async_create_mode_schedule=create, data=None)
    resp = await _send(await hass_ws_client(hass), "mode_schedule/create", name="Night", mode="armed_home", time="22:00:00", days=["mon"])
    assert resp["result"] == {"id": "m1"}
    create.assert_awaited_once_with("Night", "armed_home", "22:00", ["mon"], None, None)


@pytest.mark.parametrize("payload", [{"mode": "armed_night"}, {"days": []}, {"time": "10pm"}])
async def test_mode_schedule_create_rejects_a_bad_schedule(hass, hass_ws_client, entry, payload) -> None:
    create = AsyncMock()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = SimpleNamespace(async_create_mode_schedule=create, data=None)
    body = {"name": "Night", "mode": "armed_home", "time": "22:00", "days": ["mon"], **payload}
    resp = await _send(await hass_ws_client(hass), "mode_schedule/create", **body)
    assert not resp["success"]
    create.assert_not_awaited()


async def test_mode_schedule_conflict_has_its_own_error_code(hass, hass_ws_client, entry) -> None:
    update = AsyncMock(side_effect=api.ScheduleConflict("clash", "m2"))
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = SimpleNamespace(async_update_mode_schedule=update, data=None)
    resp = await _send(await hass_ws_client(hass), "mode_schedule/update", schedule_id="m1", enabled=True)
    assert resp["error"]["code"] == "schedule_conflict"


async def test_mode_schedule_list_and_delete(hass, hass_ws_client, entry) -> None:
    with patch(f"{API}.async_get_mode_schedules", AsyncMock(return_value=[{"id": "m1"}])):
        resp = await _send(await hass_ws_client(hass), "mode_schedule/list")
    assert resp["result"] == [{"id": "m1"}]
    delete = AsyncMock(return_value=None)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = SimpleNamespace(async_delete_mode_schedule=delete, data=None)
    resp = await _send(await hass_ws_client(hass), "mode_schedule/delete", schedule_id="m1")
    assert resp["success"]
    delete.assert_awaited_once_with("m1")


async def test_set_code_returns_each_locks_sync_result_but_never_the_code(hass, hass_ws_client, entry) -> None:
    sync = [{"nodeId": 44, "slot": 3, "status": "synced"}, {"nodeId": 45, "slot": 3, "status": "failed", "message": "lock asleep"}]
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = SimpleNamespace(lock_names=lambda: {44: "Front door"}, data=None)
    with patch(f"{API}.async_set_user_code", AsyncMock(return_value=sync)):
        resp = await _send(await hass_ws_client(hass), "user/set_code", user_id="u1", code="4821", confirm_code="4821")
    assert resp["result"]["lock_sync"] == [
        {"node_id": 44, "lock": "Front door", "slot": 3, "status": "synced"},
        {"node_id": 45, "lock": "Lock 45", "slot": 3, "status": "failed", "message": "lock asleep"},
    ]
    assert "4821" not in str(resp)


async def test_clear_code_returns_the_lock_sync_too(hass, hass_ws_client, entry) -> None:
    with patch(f"{API}.async_clear_user_code", AsyncMock(return_value=[{"nodeId": 44, "slot": 3, "status": "synced"}])):
        resp = await _send(await hass_ws_client(hass), "user/clear_code", user_id="u1")
    assert resp["result"]["lock_sync"][0]["status"] == "synced"


async def test_lock_mode_settings_command_maps_wire_names_and_merges_actions(hass, hass_ws_client, entry) -> None:
    put = AsyncMock(return_value={"armOnLockWithCode": True})
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = SimpleNamespace(async_put_lock_mode_settings=put, data=None)
    resp = await _send(
        await hass_ws_client(hass), "lock/mode_settings", node_id=44, arm_on_lock_with_code=True, actions={"armed_away": "lock", "disarmed": None}
    )
    assert resp["result"] == {"armOnLockWithCode": True}
    put.assert_awaited_once_with(44, armOnLockWithCode=True, actions={"armed_away": "lock", "disarmed": None})


@pytest.mark.parametrize("payload", [{}, {"actions": {}}, {"actions": {"armed_night": "lock"}}, {"actions": {"armed_away": "open"}}])
async def test_lock_mode_settings_command_rejects_an_empty_or_bad_change(hass, hass_ws_client, entry, payload) -> None:
    put = AsyncMock()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = SimpleNamespace(async_put_lock_mode_settings=put, data=None)
    resp = await _send(await hass_ws_client(hass), "lock/mode_settings", node_id=44, **payload)
    assert not resp["success"]
    put.assert_not_awaited()


async def test_sensor_update_and_assign_pass_the_chirp_tone(hass, hass_ws_client, entry) -> None:
    with patch(f"{API}.async_update_sensor", AsyncMock(return_value={})) as update:
        resp = await _send(await hass_ws_client(hass), "sensor/update", sensor_id="s1", chirp_tone="doorbell")
    assert resp["success"] and update.await_args.args[-2:] == ("s1", {"chirpTone": "doorbell"})
    with patch(f"{API}.async_assign_sensor", AsyncMock(return_value={"id": "s9"})) as assign:
        await _send(await hass_ws_client(hass), "sensor/assign", zone_id="z1", zwave_node_id=7, name="Back", category="intrusion", chirp_tone="none")
    assert assign.await_args.kwargs["chirp_tone"] == "none"


async def test_sensor_update_rejects_an_unknown_chirp_tone(hass, hass_ws_client, entry) -> None:
    resp = await _send(await hass_ws_client(hass), "sensor/update", sensor_id="s1", chirp_tone="siren")
    assert not resp["success"]


async def test_modes_update_takes_chirps_and_the_disarmed_mode(hass, hass_ws_client, entry) -> None:
    update = AsyncMock(return_value={})
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = SimpleNamespace(async_update_modes=update, data=None)
    resp = await _send(await hass_ws_client(hass), "modes/update", disarmed={"chirpsEnabled": True}, armed_home={"chirpsEnabled": False})
    assert resp["success"]
    update.assert_awaited_once_with({"disarmed": {"chirpsEnabled": True}, "armed_home": {"chirpsEnabled": False}})


@pytest.mark.parametrize("payload", [{"disarmed": {"entryDelaySec": 10}}, {"disarmed": {}}, {"armed_home": {"chirpsEnabled": "yes"}}])
async def test_modes_update_rejects_what_a_mode_does_not_have(hass, hass_ws_client, entry, payload) -> None:
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = SimpleNamespace(async_update_modes=AsyncMock(), data=None)
    resp = await _send(await hass_ws_client(hass), "modes/update", **payload)
    assert not resp["success"]


async def test_keypad_settings_update_takes_volume_alone_or_with_the_pin_switch(hass, hass_ws_client, entry) -> None:
    with patch(f"{API}.async_update_keypad_settings", AsyncMock(return_value={})) as update:
        await _send(await hass_ws_client(hass), "keypad_settings/update", volume=40)
        assert update.await_args.args[-1] == {"volume": 40}
        await _send(await hass_ws_client(hass), "keypad_settings/update", volume=0, require_code_to_arm=True)
        assert update.await_args.args[-1] == {"requireCodeToArm": True, "volume": 0}


@pytest.mark.parametrize("payload", [{"volume": 100}, {"volume": -1}, {}])
async def test_keypad_settings_update_rejects_a_bad_volume_or_nothing(hass, hass_ws_client, entry, payload) -> None:
    with patch(f"{API}.async_update_keypad_settings", AsyncMock()) as update:
        resp = await _send(await hass_ws_client(hass), "keypad_settings/update", **payload)
    assert not resp["success"]
    update.assert_not_awaited()
