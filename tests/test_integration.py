"""End-to-end tests: a real Home Assistant core against a fake Z-Wave Alarm service (REST + WebSocket)."""

from __future__ import annotations

import asyncio
import copy
from typing import Any

import pytest
import voluptuous as vol
import zwave_alarm_client as api
from aiohttp import WSMsgType, web
from aiohttp.test_utils import TestServer
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.zwave_alarm.const import CONF_SSL, DOMAIN

SENSOR = {
    "id": "s1", "zwaveNodeId": 2, "zoneId": "z1", "name": "Front door", "category": "intrusion",
    "currentState": "normal", "batteryLevel": 90, "connectivityStatus": "online", "updatedAt": 0,
}
ZONES = [{"id": "z1", "name": "Downstairs", "sensors": [SENSOR]}]
KEYPAD = {
    "nodeId": 12, "adapterId": "ring-keypad-v2", "label": "Ring Keypad v2",
    "capabilities": ["arm_disarm", "emergency", "indicators", "chime"],
    "chimeSounds": ["double_beep", "guitar", "wind_chimes", "bing_bong", "doorbell"],
    "connectivityStatus": "online", "batteryLevel": 87,
}
BE469 = {
    "nodeId": 21, "model": "BE469", "label": "Front Door Lock", "connectivityStatus": "online", "batteryLevel": 80,
    "supportedSettings": [
        "beeper", "vacationMode", "lockAndLeave", "autoLock", "pinLength",
        "alarmMode", "alertSensitivity", "tamperSensitivity", "kickSensitivity", "localControls",
    ],
    "settings": {
        "beeper": True, "vacationMode": False, "lockAndLeave": False, "autoLock": True, "pinLength": 4,
        "alarmMode": "alert", "alertSensitivity": 3, "tamperSensitivity": 1, "kickSensitivity": 0, "localControls": True,
    },
    "diagnostics": {
        "electronicTransitionCount": 120, "mechanicalTransitionCount": 14, "electronicFailedCount": 2,
        "electronicHighPreloadTransitionCount": 1, "bootloaderVersion": 3,
        "userSlotBitField": [259, 0, 0, 0], "occupiedUserSlots": [1, 2, 9],
    },
    "scheduleSlots": {"weekDay": 7, "yearDay": 7, "dailyRepeating": 7},
    "userSlotCount": 30,
}
BE468 = {
    "nodeId": 22, "model": "BE468", "label": "Back Door Lock", "connectivityStatus": "online", "batteryLevel": 55,
    "supportedSettings": ["beeper", "vacationMode", "lockAndLeave", "autoLock", "pinLength"],
    "settings": {
        "beeper": False, "vacationMode": True, "lockAndLeave": True, "autoLock": False, "pinLength": 6,
        "alarmMode": None, "alertSensitivity": None, "tamperSensitivity": None, "kickSensitivity": None, "localControls": None,
    },
    "diagnostics": {
        "electronicTransitionCount": 3, "mechanicalTransitionCount": 0, "electronicFailedCount": 0,
        "electronicHighPreloadTransitionCount": 0, "bootloaderVersion": 2, "userSlotBitField": [0, 0, 0, 0], "occupiedUserSlots": [],
    },
    "scheduleSlots": {"weekDay": 4, "yearDay": 4, "dailyRepeating": 0},
    "userSlotCount": 30,
}
PANEL = {"mode": "armed_away", "pendingDelayEndsAt": None, "disarmedZoneIds": []}


class FakeService:
    """Serves /panel, /zones, /panel/disarm and /stream; tests push messages via `broadcast`."""

    def __init__(self) -> None:
        self.zones = copy.deepcopy(ZONES)
        self.sockets: list[web.WebSocketResponse] = []
        self.connected = asyncio.Event()
        self.disarm_response: dict[str, Any] = {"mode": "disarmed", "pendingDelayEndsAt": None}
        self.disarm_calls: list[dict] = []
        self.keypads: list[dict] | None = [copy.deepcopy(KEYPAD)]
        self.locks: list[dict] | None = None
        self.lock_calls: list[tuple] = []
        self.lock_status = 200  # non-2xx makes every lock write fail with the matching error body
        self.schedule: dict | None = {"weekday": 1, "startHour": 8, "startMinute": 0, "stopHour": 17, "stopMinute": 30}
        self.keypad_settings: dict | None = {"requireCodeToArm": False}
        self.keypad_settings_calls: list[dict] = []
        self.keypad_settings_status = 200
        self.chime_calls: list[dict] = []
        self.chime_status = 204
        self.auth_headers: list[str | None] = []

    def _note(self, request: web.Request) -> None:
        self.auth_headers.append(request.headers.get("Authorization"))

    async def panel(self, request: web.Request) -> web.Response:
        self._note(request)
        return web.json_response(PANEL)

    async def zones_handler(self, request: web.Request) -> web.Response:
        return web.json_response(self.zones)

    async def disarm(self, request: web.Request) -> web.Response:
        self.disarm_calls.append(await request.json())
        return web.json_response(self.disarm_response)

    async def chime(self, request: web.Request) -> web.Response:
        self._note(request)
        self.chime_calls.append({"node_id": int(request.match_info["node_id"]), **await request.json()})
        if self.chime_status == 204:
            return web.Response(status=204)
        return web.json_response({"error": {"code": "bad_request", "message": "nope"}}, status=self.chime_status)

    async def patch_keypad_settings(self, request: web.Request) -> web.Response:
        self._note(request)
        body = await request.json()
        self.keypad_settings_calls.append(body)
        if self.keypad_settings_status != 200:
            return web.json_response({"error": {"code": "forbidden", "message": "no"}}, status=self.keypad_settings_status)
        self.keypad_settings = {**self.keypad_settings, **body}
        return web.json_response(self.keypad_settings)

    def _lock_failure(self) -> web.Response | None:
        if self.lock_status < 300:
            return None
        code = {400: "bad_request", 401: "unauthorized", 404: "not_found", 502: "lock_unavailable"}.get(self.lock_status, "internal")
        return web.json_response({"error": {"code": code, "message": f"lock said {code}"}}, status=self.lock_status)

    async def lock_settings(self, request: web.Request) -> web.Response:
        node_id, body = int(request.match_info["node_id"]), await request.json()
        self.lock_calls.append(("settings", node_id, body))
        if (failure := self._lock_failure()) is not None:
            return failure
        lock = next(lk for lk in self.locks if lk["nodeId"] == node_id)
        lock["settings"] = {**lock["settings"], **body}
        return web.json_response(lock)

    async def lock_schedule(self, request: web.Request) -> web.Response:
        info = request.match_info
        key = (request.method.lower(), int(info["node_id"]), int(info["user_id"]), info["kind"], int(info["slot_id"]))
        self.lock_calls.append((*key, *([await request.json()] if request.method == "PUT" else [])))
        if (failure := self._lock_failure()) is not None:
            return failure
        if request.method == "GET":
            return web.json_response({"kind": key[3], "userId": key[2], "slotId": key[4], "schedule": self.schedule})
        return web.Response(status=204)

    async def lock_schedules_enabled(self, request: web.Request) -> web.Response:
        info = request.match_info
        self.lock_calls.append(("enabled", int(info["node_id"]), int(info["user_id"]), await request.json()))
        return self._lock_failure() or web.Response(status=204)

    async def stream(self, request: web.Request) -> web.StreamResponse:
        self._note(request)
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        self.sockets.append(ws)
        snapshot = {"type": "snapshot", "panel": PANEL, "zones": copy.deepcopy(self.zones)}
        if self.keypads is not None:
            snapshot["keypads"] = copy.deepcopy(self.keypads)
        if self.keypad_settings is not None:
            snapshot["keypadSettings"] = copy.deepcopy(self.keypad_settings)
        if self.locks is not None:
            snapshot["locks"] = copy.deepcopy(self.locks)
        await ws.send_json(snapshot)
        self.connected.set()
        async for msg in ws:
            if msg.type == WSMsgType.ERROR:
                break
        return ws

    async def broadcast(self, message: dict) -> None:
        for ws in self.sockets:
            await ws.send_json(message)

    async def drop_connections(self) -> None:
        for ws in self.sockets:
            await ws.close()
        self.sockets.clear()
        self.connected.clear()


@pytest.fixture
async def service(socket_enabled):
    fake = FakeService()
    app = web.Application()
    app.router.add_get("/api/v1/panel", fake.panel)
    app.router.add_get("/api/v1/zones", fake.zones_handler)
    app.router.add_post("/api/v1/panel/disarm", fake.disarm)
    app.router.add_post("/api/v1/keypads/{node_id}/chime", fake.chime)
    app.router.add_patch("/api/v1/keypad-settings", fake.patch_keypad_settings)
    app.router.add_patch("/api/v1/locks/{node_id}/settings", fake.lock_settings)
    app.router.add_put("/api/v1/locks/{node_id}/users/{user_id}/schedules/enabled", fake.lock_schedules_enabled)
    app.router.add_route("*", "/api/v1/locks/{node_id}/users/{user_id}/schedules/{kind}/{slot_id}", fake.lock_schedule)
    app.router.add_get("/api/v1/stream", fake.stream)
    server = TestServer(app, host="127.0.0.1")
    await server.start_server()
    fake.port = server.port
    yield fake
    await server.close()


@pytest.fixture(autouse=True)
def _enable(enable_custom_integrations, socket_enabled):
    yield


@pytest.fixture
async def setup(hass: HomeAssistant, service: FakeService):
    """Returns an async factory that adds+sets up an entry, and unloads every entry on teardown.

    Unloading cancels the coordinator's stream task so the fake server can close.
    """
    entries: list[MockConfigEntry] = []

    async def _setup(**extra: Any) -> MockConfigEntry:
        entry = MockConfigEntry(
            domain=DOMAIN,
            data={CONF_HOST: "127.0.0.1", CONF_PORT: service.port, CONF_SSL: False, **extra},
            version=1 if extra else 2,
            unique_id=f"127.0.0.1:{service.port}",
        )
        entry.add_to_hass(hass)
        entries.append(entry)
        await hass.config_entries.async_setup(entry.entry_id)
        return entry

    yield _setup

    for entry in entries:
        if entry.state is ConfigEntryState.LOADED:
            await hass.config_entries.async_unload(entry.entry_id)


def _device(hass: HomeAssistant, entry: MockConfigEntry, identifier: str):
    """Look a device up by identifier on both older and newer Home Assistant (`async_get_device` was deprecated)."""
    registry = dr.async_get(hass)
    if hasattr(registry, "async_get_device_by_identifier"):
        return registry.async_get_device_by_identifier((DOMAIN, identifier), entry.entry_id)
    return registry.async_get_device(identifiers={(DOMAIN, identifier)})


async def _settle(hass: HomeAssistant, service: FakeService) -> None:
    await asyncio.wait_for(service.connected.wait(), 5)
    await hass.async_block_till_done()
    await asyncio.sleep(0.05)
    await hass.async_block_till_done()


async def test_entities_follow_snapshot_and_pushed_events(hass: HomeAssistant, service: FakeService, setup) -> None:
    entry = await setup()
    await _settle(hass, service)

    panel = hass.states.get("alarm_control_panel.zwave_alarm")
    assert panel.state == "armed_away"
    assert hass.states.get("binary_sensor.zwave_alarm_zone_downstairs").state == "off"
    assert hass.states.get("sensor.zwave_alarm_fault_count").state == "0"

    await service.broadcast({"type": "sensor.changed", "sensorId": "s1", "zoneId": "z1", "currentState": "breached", "category": "intrusion"})
    await service.broadcast({"type": "sensor.fault", "sensorId": "s1", "connectivityStatus": "online", "batteryLevel": 5})
    await service.broadcast({
        "type": "panel.changed", "mode": "alarm_triggered", "pendingDelayEndsAt": None,
        "disarmedZoneIds": [], "triggeredBy": {"sensorId": "s1", "zoneId": "z1"},
    })
    await asyncio.sleep(0.1)
    await hass.async_block_till_done()

    assert hass.states.get("binary_sensor.zwave_alarm_zone_downstairs").state == "on"
    fault = hass.states.get("sensor.zwave_alarm_fault_count")
    assert fault.state == "1"
    assert fault.attributes["sensors"] == [{"name": "Front door", "zone": "Downstairs", "reasons": ["low_battery"]}]
    panel = hass.states.get("alarm_control_panel.zwave_alarm")
    assert panel.state == "triggered"
    assert panel.attributes["triggered_by_zone"] == "Downstairs"

    assert await hass.config_entries.async_unload(entry.entry_id)
    assert hass.states.get("alarm_control_panel.zwave_alarm").state == "unavailable"


async def test_zone_restricted_guest_disarm_is_visible(hass: HomeAssistant, service: FakeService, setup) -> None:
    await setup()
    await _settle(hass, service)

    await service.broadcast({"type": "panel.changed", "mode": "armed_away", "pendingDelayEndsAt": None, "disarmedZoneIds": ["z1"], "triggeredBy": None})
    await asyncio.sleep(0.1)
    await hass.async_block_till_done()

    assert hass.states.get("alarm_control_panel.zwave_alarm").state == "armed_away"
    assert hass.states.get("alarm_control_panel.zwave_alarm").attributes["disarmed_zones"] == ["Downstairs"]
    assert hass.states.get("binary_sensor.zwave_alarm_zone_downstairs").attributes["disarmed"] is True


async def test_security_event_entity_exposes_cleared_by(hass: HomeAssistant, service: FakeService, setup) -> None:
    await setup()
    await _settle(hass, service)

    await service.broadcast({
        "type": "event.recorded",
        "event": {"id": "e1", "type": "alarm_cleared", "occurredAt": 5, "details": "Cleared by Owner"},
    })
    await asyncio.sleep(0.1)
    await hass.async_block_till_done()

    state = hass.states.get("event.zwave_alarm_security_events")
    assert state.attributes["event_type"] == "alarm_cleared"
    assert state.attributes["details"] == "Cleared by Owner"


async def test_zone_added_later_gets_an_entity(hass: HomeAssistant, service: FakeService, setup) -> None:
    await setup()
    await _settle(hass, service)
    assert hass.states.get("binary_sensor.zwave_alarm_zone_garage") is None

    service.zones.append({
        "id": "z2", "name": "Garage",
        "sensors": [{**SENSOR, "id": "s2", "zoneId": "z2", "name": "Garage door"}],
    })
    await service.broadcast({"type": "sensor.changed", "sensorId": "s2", "zoneId": "z2", "currentState": "breached", "category": "intrusion"})
    await asyncio.sleep(0.2)
    await hass.async_block_till_done()

    assert hass.states.get("binary_sensor.zwave_alarm_zone_garage").state == "on"


async def test_entities_unavailable_while_disconnected(hass: HomeAssistant, service: FakeService, setup) -> None:
    await setup()
    await _settle(hass, service)

    await service.drop_connections()
    await asyncio.sleep(0.1)
    await hass.async_block_till_done()

    for entity_id in (
        "alarm_control_panel.zwave_alarm",
        "binary_sensor.zwave_alarm_zone_downstairs",
        "sensor.zwave_alarm_fault_count",
    ):
        assert hass.states.get(entity_id).state == "unavailable"


async def test_disarm_passes_code_and_updates_state(hass: HomeAssistant, service: FakeService, setup) -> None:
    await setup()
    await _settle(hass, service)

    await hass.services.async_call(
        "alarm_control_panel", "alarm_disarm", {"entity_id": "alarm_control_panel.zwave_alarm", "code": "1234"}, blocking=True
    )

    assert service.disarm_calls == [{"code": "1234"}]
    assert hass.states.get("alarm_control_panel.zwave_alarm").state == "disarmed"


async def test_no_token_is_sent(hass: HomeAssistant, service: FakeService, setup) -> None:
    await setup()
    await _settle(hass, service)

    assert service.auth_headers and set(service.auth_headers) == {None}
    assert hass.states.get("alarm_control_panel.zwave_alarm").state == "armed_away"


async def test_legacy_entry_token_is_dropped(hass: HomeAssistant, service: FakeService, setup) -> None:
    entry = await setup(access_token="stale-token")
    await _settle(hass, service)

    assert entry.version == 2
    assert "access_token" not in entry.data
    assert set(service.auth_headers) == {None}
    assert hass.config_entries.flow.async_progress_by_handler(DOMAIN) == []


async def test_config_flow_asks_only_for_connection_details(hass: HomeAssistant, service: FakeService) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert set(result["data_schema"].schema) == {CONF_HOST, CONF_PORT, CONF_SSL}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: "127.0.0.1", CONF_PORT: service.port}
    )
    assert result["type"] == "create_entry"
    assert result["data"] == {CONF_HOST: "127.0.0.1", CONF_PORT: service.port, CONF_SSL: False}
    assert set(service.auth_headers) == {None}
    await hass.config_entries.async_unload(result["result"].entry_id)


async def _push(hass: HomeAssistant, service: FakeService, message: dict) -> None:
    await service.broadcast(message)
    await asyncio.sleep(0.1)
    await hass.async_block_till_done()


async def test_keypad_gets_a_device_and_entities_from_the_snapshot(hass: HomeAssistant, service: FakeService, setup) -> None:
    entry = await setup()
    await _settle(hass, service)

    device = _device(hass, entry, f"{entry.entry_id}_keypad_12")
    assert device.name == "Ring Keypad v2"
    assert device.model == "ring-keypad-v2"
    assert device.via_device_id is not None

    assert hass.states.get("binary_sensor.ring_keypad_v2_connectivity").state == "on"
    assert hass.states.get("sensor.ring_keypad_v2_battery").state == "87"
    assert hass.states.get("event.ring_keypad_v2_keypad_input").state == "unknown"


async def test_keypad_changed_updates_sensors_and_discovers_new_keypads(hass: HomeAssistant, service: FakeService, setup) -> None:
    await setup()
    await _settle(hass, service)

    await _push(hass, service, {"type": "keypad.changed", "keypad": {**KEYPAD, "connectivityStatus": "offline", "batteryLevel": None}})
    assert hass.states.get("binary_sensor.ring_keypad_v2_connectivity").state == "off"
    assert hass.states.get("sensor.ring_keypad_v2_battery").state == "unknown"

    await _push(hass, service, {"type": "keypad.changed", "keypad": {**KEYPAD, "nodeId": 30, "label": "Hall Keypad"}})
    assert hass.states.get("binary_sensor.hall_keypad_connectivity").state == "on"
    assert hass.states.get("sensor.hall_keypad_battery").state == "87"


async def test_keypad_event_fires_only_that_keypads_event_entity(hass: HomeAssistant, service: FakeService, setup) -> None:
    await setup()
    await _settle(hass, service)
    await _push(hass, service, {"type": "keypad.changed", "keypad": {**KEYPAD, "nodeId": 30, "label": "Hall Keypad"}})

    await _push(hass, service, {
        "type": "keypad.event", "nodeId": 12, "adapterId": "ring-keypad-v2", "input": {"kind": "emergency", "emergency": "fire"},
    })

    state = hass.states.get("event.ring_keypad_v2_keypad_input")
    assert state.attributes["event_type"] == "emergency"
    assert state.attributes["emergency"] == "fire"
    assert state.attributes["adapter_id"] == "ring-keypad-v2"
    assert hass.states.get("event.hall_keypad_keypad_input").state == "unknown"


async def test_unknown_keypad_event_kind_is_ignored(hass: HomeAssistant, service: FakeService, setup) -> None:
    await setup()
    await _settle(hass, service)

    await _push(hass, service, {"type": "keypad.event", "nodeId": 12, "adapterId": "ring-keypad-v2", "input": {"kind": "wave_hello"}})
    await _push(hass, service, {"type": "keypad.event", "nodeId": 12, "adapterId": "ring-keypad-v2", "input": {"kind": "arm_home"}})

    assert hass.states.get("event.ring_keypad_v2_keypad_input").attributes["event_type"] == "arm_home"


async def test_snapshot_without_keypads_creates_none(hass: HomeAssistant, service: FakeService, setup) -> None:
    service.keypads = None
    await setup()
    await _settle(hass, service)

    assert hass.states.get("binary_sensor.ring_keypad_v2_connectivity") is None
    assert hass.states.get("alarm_control_panel.zwave_alarm").state == "armed_away"


async def test_keypad_entities_unavailable_while_disconnected(hass: HomeAssistant, service: FakeService, setup) -> None:
    await setup()
    await _settle(hass, service)

    await service.drop_connections()
    await asyncio.sleep(0.1)
    await hass.async_block_till_done()

    for entity_id in (
        "binary_sensor.ring_keypad_v2_connectivity", "sensor.ring_keypad_v2_battery", "event.ring_keypad_v2_keypad_input",
    ):
        assert hass.states.get(entity_id).state == "unavailable"


@pytest.fixture
def chime_calls(service: FakeService) -> list[dict]:
    """Chime requests the fake service received, sent by the real zwave-alarm-client."""
    return service.chime_calls


def _keypad_device_id(hass: HomeAssistant, entry: MockConfigEntry, node_id: int = 12) -> str:
    return _device(hass, entry, f"{entry.entry_id}_keypad_{node_id}").id


async def test_chime_service_calls_the_client(hass: HomeAssistant, service: FakeService, setup, chime_calls) -> None:
    entry = await setup()
    await _settle(hass, service)

    await hass.services.async_call(
        DOMAIN, "keypad_chime", {"device_id": _keypad_device_id(hass, entry), "sound": "doorbell", "volume": 60}, blocking=True
    )
    await hass.services.async_call(
        DOMAIN, "keypad_chime", {"entity_id": "event.ring_keypad_v2_keypad_input", "sound": "guitar"}, blocking=True
    )

    assert chime_calls == [
        {"node_id": 12, "sound": "doorbell", "volume": 60},
        {"node_id": 12, "sound": "guitar"},
    ]


@pytest.mark.parametrize("data", [{"sound": "doorbell", "volume": 100}, {"sound": "doorbell", "volume": -1}, {"volume": 5}])
async def test_chime_service_rejects_bad_data(hass: HomeAssistant, service: FakeService, setup, chime_calls, data) -> None:
    entry = await setup()
    await _settle(hass, service)

    with pytest.raises(vol.Invalid):
        await hass.services.async_call(DOMAIN, "keypad_chime", {"device_id": _keypad_device_id(hass, entry), **data}, blocking=True)
    assert chime_calls == []


async def test_chime_service_rejects_unsupported_sound_and_capability(hass: HomeAssistant, service: FakeService, setup, chime_calls) -> None:
    entry = await setup()
    await _settle(hass, service)
    await _push(hass, service, {
        "type": "keypad.changed",
        "keypad": {**KEYPAD, "nodeId": 30, "label": "Hall Keypad", "capabilities": ["arm_disarm"], "chimeSounds": []},
    })

    with pytest.raises(ServiceValidationError, match="does not support the sound"):
        await hass.services.async_call(
            DOMAIN, "keypad_chime", {"device_id": _keypad_device_id(hass, entry), "sound": "kazoo"}, blocking=True
        )
    with pytest.raises(ServiceValidationError, match="Hall Keypad does not support chimes"):
        await hass.services.async_call(
            DOMAIN, "keypad_chime", {"device_id": _keypad_device_id(hass, entry, 30), "sound": "doorbell"}, blocking=True
        )
    assert chime_calls == []


async def test_chime_service_needs_a_keypad_target(hass: HomeAssistant, service: FakeService, setup, chime_calls) -> None:
    entry = await setup()
    await _settle(hass, service)
    panel_device = _device(hass, entry, entry.entry_id)

    with pytest.raises(ServiceValidationError, match="No Z-Wave Alarm keypad"):
        await hass.services.async_call(DOMAIN, "keypad_chime", {"device_id": panel_device.id, "sound": "doorbell"}, blocking=True)
    assert chime_calls == []


@pytest.mark.parametrize(
    ("status", "expected"),
    [(404, ServiceValidationError), (400, ServiceValidationError), (401, HomeAssistantError), (500, HomeAssistantError)],
)
async def test_chime_service_maps_client_errors(hass: HomeAssistant, service: FakeService, setup, status, expected) -> None:
    service.chime_status = status
    entry = await setup()
    await _settle(hass, service)

    with pytest.raises(expected) as caught:
        await hass.services.async_call(
            DOMAIN, "keypad_chime", {"device_id": _keypad_device_id(hass, entry), "sound": "doorbell"}, blocking=True
        )
    assert type(caught.value) is expected


async def test_chime_service_maps_unreachable_service(hass: HomeAssistant, service: FakeService, setup, monkeypatch) -> None:
    async def unreachable(*args, **kwargs):
        raise api.CannotConnect

    monkeypatch.setattr(api, "async_chime_keypad", unreachable)
    entry = await setup()
    await _settle(hass, service)

    with pytest.raises(HomeAssistantError, match="Could not reach"):
        await hass.services.async_call(
            DOMAIN, "keypad_chime", {"device_id": _keypad_device_id(hass, entry), "sound": "doorbell"}, blocking=True
        )


# --- Schlage locks -----------------------------------------------------------------------------------------------------


@pytest.fixture
def locks(service: FakeService) -> FakeService:
    """The fake service reporting a BE469 and a BE468; lock writes reach it through the real client."""
    service.locks = [copy.deepcopy(BE469), copy.deepcopy(BE468)]
    return service


def _lock_device_id(hass: HomeAssistant, entry: MockConfigEntry, node_id: int = 21) -> str:
    return _device(hass, entry, f"{entry.entry_id}_lock_{node_id}").id


async def test_be469_gets_every_lock_entity(hass: HomeAssistant, service: FakeService, setup, locks) -> None:
    entry = await setup()
    await _settle(hass, service)

    device = _device(hass, entry, f"{entry.entry_id}_lock_21")
    assert (device.name, device.manufacturer, device.model) == ("Front Door Lock", "Schlage", "BE469")

    expected = {
        "switch.front_door_lock_beeper": "on",
        "switch.front_door_lock_vacation_mode": "off",
        "switch.front_door_lock_lock_leave": "off",
        "switch.front_door_lock_auto_lock": "on",
        "switch.front_door_lock_local_controls": "on",
        "select.front_door_lock_alarm_mode": "alert",
        "select.front_door_lock_alert_sensitivity": "medium",
        "select.front_door_lock_tamper_sensitivity": "most_sensitive",
        "select.front_door_lock_kick_sensitivity": "unknown",  # 0 means the sensor isn't supported
        "number.front_door_lock_pin_length": "4",
        "sensor.front_door_lock_battery": "80",
        "sensor.front_door_lock_electronic_transitions": "120",
        "sensor.front_door_lock_mechanical_transitions": "14",
        "sensor.front_door_lock_electronic_failed_transitions": "2",
        "sensor.front_door_lock_electronic_high_preload_transitions": "1",
        "sensor.front_door_lock_occupied_user_slots": "3",
        "sensor.front_door_lock_bootloader_version": "3",
        "binary_sensor.front_door_lock_connectivity": "on",
    }
    for entity_id, state in expected.items():
        assert hass.states.get(entity_id).state == state, entity_id
    assert hass.states.get("sensor.front_door_lock_occupied_user_slots").attributes["slots"] == [1, 2, 9]


async def test_entities_are_built_from_supported_settings(hass: HomeAssistant, service: FakeService, setup, locks) -> None:
    await setup()
    await _settle(hass, service)

    assert hass.states.get("switch.back_door_lock_vacation_mode").state == "on"
    assert hass.states.get("number.back_door_lock_pin_length").state == "6"
    for entity_id in (  # a BE468 lists none of the BE469-only settings, even though it reports them as null
        "switch.back_door_lock_local_controls", "select.back_door_lock_alarm_mode",
        "select.back_door_lock_alert_sensitivity", "select.back_door_lock_tamper_sensitivity",
        "select.back_door_lock_kick_sensitivity",
    ):
        assert hass.states.get(entity_id) is None, entity_id


async def test_unreported_values_are_unknown(hass: HomeAssistant, service: FakeService, setup, locks) -> None:
    locks.locks[0]["settings"]["beeper"] = None
    locks.locks[0]["settings"]["pinLength"] = None
    locks.locks[0]["diagnostics"].update(electronicFailedCount=None, occupiedUserSlots=None, bootloaderVersion=None)
    locks.locks[0]["batteryLevel"] = None
    await setup()
    await _settle(hass, service)

    for entity_id in (
        "switch.front_door_lock_beeper", "number.front_door_lock_pin_length", "sensor.front_door_lock_electronic_failed_transitions",
        "sensor.front_door_lock_occupied_user_slots", "sensor.front_door_lock_bootloader_version", "sensor.front_door_lock_battery",
    ):
        assert hass.states.get(entity_id).state == "unknown", entity_id


async def test_snapshot_without_locks_creates_none(hass: HomeAssistant, service: FakeService, setup) -> None:
    await setup()
    await _settle(hass, service)

    assert hass.states.get("switch.front_door_lock_beeper") is None


async def test_switch_writes_the_setting_and_updates_at_once(hass: HomeAssistant, service: FakeService, setup, locks) -> None:
    await setup()
    await _settle(hass, service)

    await hass.services.async_call("switch", "turn_off", {"entity_id": "switch.front_door_lock_beeper"}, blocking=True)
    await hass.services.async_call("switch", "turn_on", {"entity_id": "switch.front_door_lock_local_controls"}, blocking=True)
    await hass.services.async_call("switch", "turn_on", {"entity_id": "switch.back_door_lock_beeper"}, blocking=True)

    assert locks.lock_calls == [
        ("settings", 21, {"beeper": False}),
        ("settings", 21, {"localControls": True}),
        ("settings", 22, {"beeper": True}),
    ]
    assert hass.states.get("switch.front_door_lock_beeper").state == "off"
    assert hass.states.get("switch.back_door_lock_beeper").state == "on"


async def test_selects_write_option_values(hass: HomeAssistant, service: FakeService, setup, locks) -> None:
    await setup()
    await _settle(hass, service)

    for entity, option in (
        ("alarm_mode", "forced_entry"), ("kick_sensitivity", "least_sensitive"), ("alert_sensitivity", "low"),
    ):
        await hass.services.async_call(
            "select", "select_option", {"entity_id": f"select.front_door_lock_{entity}", "option": option}, blocking=True
        )

    assert locks.lock_calls == [
        ("settings", 21, {"alarmMode": "forced_entry"}),
        ("settings", 21, {"kickSensitivity": 5}),
        ("settings", 21, {"alertSensitivity": 4}),
    ]
    assert hass.states.get("select.front_door_lock_alarm_mode").state == "forced_entry"
    assert hass.states.get("select.front_door_lock_kick_sensitivity").state == "least_sensitive"


async def test_pin_length_is_limited_to_4_through_8(hass: HomeAssistant, service: FakeService, setup, locks) -> None:
    await setup()
    await _settle(hass, service)

    await hass.services.async_call("number", "set_value", {"entity_id": "number.front_door_lock_pin_length", "value": 8}, blocking=True)
    for bad in (3, 9):
        with pytest.raises(ServiceValidationError):
            await hass.services.async_call(
                "number", "set_value", {"entity_id": "number.front_door_lock_pin_length", "value": bad}, blocking=True
            )

    assert locks.lock_calls == [("settings", 21, {"pinLength": 8})]
    assert hass.states.get("number.front_door_lock_pin_length").state == "8"


@pytest.mark.parametrize(("status", "expected", "message"), [
    (400, ServiceValidationError, "lock said bad_request"),
    (404, ServiceValidationError, "lock said not_found"),
    (401, HomeAssistantError, "refused"),
    (502, HomeAssistantError, "did not respond"),  # LockUnavailable, not "service unreachable"
    (500, HomeAssistantError, "Could not reach"),  # the client treats a 5xx as an unreachable service
])
async def test_lock_write_errors_map_to_home_assistant_errors(hass, service, setup, locks, status, expected, message) -> None:
    await setup()
    await _settle(hass, service)
    locks.lock_status = status

    with pytest.raises(expected, match=message) as caught:
        await hass.services.async_call("switch", "turn_off", {"entity_id": "switch.front_door_lock_beeper"}, blocking=True)
    assert type(caught.value) is expected
    assert hass.states.get("switch.front_door_lock_beeper").state == "on"  # a failed write leaves the state untouched


async def test_unreachable_service_is_reported_as_such(hass, service, setup, locks, monkeypatch) -> None:
    async def unreachable(*args, **kwargs):
        raise api.CannotConnect

    monkeypatch.setattr(api, "async_update_lock_settings", unreachable)
    await setup()
    await _settle(hass, service)

    with pytest.raises(HomeAssistantError, match="Could not reach"):
        await hass.services.async_call("switch", "turn_off", {"entity_id": "switch.front_door_lock_beeper"}, blocking=True)


async def test_lock_changed_updates_entities_and_discovers_new_locks(hass: HomeAssistant, service: FakeService, setup, locks) -> None:
    await setup()
    await _settle(hass, service)

    changed = {**BE469, "batteryLevel": 9, "connectivityStatus": "offline",
               "settings": {**BE469["settings"], "vacationMode": True},
               "diagnostics": {**BE469["diagnostics"], "occupiedUserSlots": [4], "electronicFailedCount": 5}}
    await _push(hass, service, {"type": "lock.changed", "lock": changed})
    assert hass.states.get("sensor.front_door_lock_battery").state == "9"
    assert hass.states.get("binary_sensor.front_door_lock_connectivity").state == "off"
    assert hass.states.get("switch.front_door_lock_vacation_mode").state == "on"
    assert hass.states.get("sensor.front_door_lock_occupied_user_slots").state == "1"
    assert hass.states.get("sensor.front_door_lock_electronic_failed_transitions").state == "5"

    await _push(hass, service, {"type": "lock.changed", "lock": {**BE468, "nodeId": 30, "label": "Garage Lock"}})
    assert hass.states.get("switch.garage_lock_beeper").state == "off"
    assert hass.states.get("select.garage_lock_alarm_mode") is None


async def test_lock_entities_unavailable_while_disconnected(hass: HomeAssistant, service: FakeService, setup, locks) -> None:
    await setup()
    await _settle(hass, service)

    await service.drop_connections()
    await asyncio.sleep(0.1)
    await hass.async_block_till_done()

    for entity_id in (
        "switch.front_door_lock_beeper", "select.front_door_lock_alarm_mode", "number.front_door_lock_pin_length",
        "sensor.front_door_lock_battery", "binary_sensor.front_door_lock_connectivity",
    ):
        assert hass.states.get(entity_id).state == "unavailable"


async def test_set_lock_schedule_sends_the_services_encoding(hass, service, setup, locks) -> None:
    entry = await setup()
    await _settle(hass, service)

    await hass.services.async_call(DOMAIN, "set_lock_schedule", {
        "device_id": _lock_device_id(hass, entry), "user_id": 3, "slot": 2, "schedule_type": "weekday",
        "weekday": "monday", "start_time": "08:00:00", "end_time": "17:30:00",
    }, blocking=True)
    await hass.services.async_call(DOMAIN, "set_lock_schedule", {
        "device_id": [_lock_device_id(hass, entry)], "user_id": 3, "slot": 1, "schedule_type": "yearday",
        "start": "2026-01-02 00:00:00", "end": "2026-01-09 23:59:00",
    }, blocking=True)
    await hass.services.async_call(DOMAIN, "set_lock_schedule", {
        "device_id": _lock_device_id(hass, entry), "user_id": 4, "slot": 1, "schedule_type": "daily_repeating",
        "weekdays": ["sunday", "friday"], "start_time": "08:00:00", "duration": {"hours": 9, "minutes": 30},
    }, blocking=True)

    assert locks.lock_calls == [
        ("put", 21, 3, "weekDay", 2, {"weekday": 1, "startHour": 8, "startMinute": 0, "stopHour": 17, "stopMinute": 30}),
        ("put", 21, 3, "yearDay", 1, {
            "startYear": 26, "startMonth": 1, "startDay": 2, "startHour": 0, "startMinute": 0,
            "stopYear": 26, "stopMonth": 1, "stopDay": 9, "stopHour": 23, "stopMinute": 59,
        }),
        ("put", 21, 4, "dailyRepeating", 1, {
            "weekdays": [0, 5], "startHour": 8, "startMinute": 0, "durationHour": 9, "durationMinute": 30,
        }),
    ]


@pytest.mark.parametrize(("node_id", "extra", "message"), [
    (21, {"end_time": "07:00:00"}, "Invalid schedule"),  # stop before start
    (21, {"slot": 8}, "slot 8 does not exist"),  # the BE469 has 7 weekday slots
    (22, {"schedule_type": "daily_repeating", "weekdays": ["monday"], "duration": "01:00:00"}, "does not support"),  # the BE468 has none
])
async def test_set_lock_schedule_rejects_bad_requests(hass, service, setup, locks, node_id, extra, message) -> None:
    entry = await setup()
    await _settle(hass, service)
    data = {
        "device_id": _lock_device_id(hass, entry, node_id), "user_id": 3, "slot": 2, "schedule_type": "weekday",
        "weekday": "monday", "start_time": "08:00:00", "end_time": "17:30:00",
    }

    with pytest.raises(ServiceValidationError, match=message):
        await hass.services.async_call(DOMAIN, "set_lock_schedule", {**data, **extra}, blocking=True)
    assert locks.lock_calls == []


async def test_set_lock_schedule_validates_every_target_before_writing(hass, service, setup, locks) -> None:
    entry = await setup()
    await _settle(hass, service)

    with pytest.raises(ServiceValidationError, match="slot 6 does not exist"):  # BE469 has 7 slots, BE468 only 4
        await hass.services.async_call(DOMAIN, "set_lock_schedule", {
            "device_id": [_lock_device_id(hass, entry, 21), _lock_device_id(hass, entry, 22)], "user_id": 1, "slot": 6,
            "schedule_type": "weekday", "weekday": "monday", "start_time": "08:00:00", "end_time": "09:00:00",
        }, blocking=True)
    assert locks.lock_calls == []


async def test_schedule_services_need_a_lock_target(hass, service, setup, locks) -> None:
    entry = await setup()
    await _settle(hass, service)

    with pytest.raises(ServiceValidationError, match="No Z-Wave Alarm lock"):
        await hass.services.async_call(
            DOMAIN, "set_lock_schedules_enabled", {"device_id": _device(hass, entry, entry.entry_id).id, "user_id": 1, "enabled": True}, blocking=True
        )
    assert locks.lock_calls == []


@pytest.mark.parametrize("data", [
    {"user_id": 0}, {"user_id": 31}, {"slot": 0}, {"schedule_type": "hourly"}, {"weekday": "someday"}, {"start_time": "25:00:00"},
])
async def test_set_lock_schedule_rejects_bad_data(hass, service, setup, locks, data) -> None:
    entry = await setup()
    await _settle(hass, service)
    base = {"device_id": _lock_device_id(hass, entry), "user_id": 1, "slot": 1, "schedule_type": "weekday",
            "weekday": "monday", "start_time": "08:00:00", "end_time": "09:00:00"}

    with pytest.raises((vol.Invalid, ServiceValidationError)):
        await hass.services.async_call(DOMAIN, "set_lock_schedule", {**base, **data}, blocking=True)
    assert locks.lock_calls == []


async def test_year_day_schedule_outside_2000_2099_is_rejected(hass, service, setup, locks) -> None:
    entry = await setup()
    await _settle(hass, service)

    with pytest.raises(ServiceValidationError, match="2000 and 2099"):
        await hass.services.async_call(DOMAIN, "set_lock_schedule", {
            "device_id": _lock_device_id(hass, entry), "user_id": 1, "slot": 1, "schedule_type": "yearday",
            "start": "2100-01-01 00:00:00", "end": "2100-01-02 00:00:00",
        }, blocking=True)
    assert locks.lock_calls == []


async def test_clear_lock_schedule_and_enable_disable(hass, service, setup, locks) -> None:
    entry = await setup()
    await _settle(hass, service)
    device_id = _lock_device_id(hass, entry)

    await hass.services.async_call(
        DOMAIN, "clear_lock_schedule", {"device_id": device_id, "user_id": 3, "slot": 2, "schedule_type": "yearday"}, blocking=True
    )
    await hass.services.async_call(DOMAIN, "set_lock_schedules_enabled", {"device_id": device_id, "enabled": False, "user_id": 3}, blocking=True)
    await hass.services.async_call(DOMAIN, "set_lock_schedules_enabled", {"device_id": device_id, "enabled": True, "user_id": 4}, blocking=True)

    assert locks.lock_calls == [
        ("delete", 21, 3, "yearDay", 2),
        ("enabled", 21, 3, {"enabled": False}),
        ("enabled", 21, 4, {"enabled": True}),
    ]


async def test_get_lock_schedule_returns_the_slot(hass, service, setup, locks) -> None:
    entry = await setup()
    await _settle(hass, service)

    response = await hass.services.async_call(
        DOMAIN, "get_lock_schedule", {"device_id": _lock_device_id(hass, entry), "user_id": 3, "slot": 1, "schedule_type": "weekday"},
        blocking=True, return_response=True,
    )

    assert response == {"Front Door Lock": {"kind": "weekDay", "userId": 3, "slotId": 1, "schedule": locks.schedule}}
    assert locks.lock_calls == [("get", 21, 3, "weekDay", 1)]


async def test_schedule_service_maps_lock_errors(hass, service, setup, locks) -> None:
    entry = await setup()
    await _settle(hass, service)
    data = {"device_id": _lock_device_id(hass, entry), "user_id": 3, "slot": 1, "schedule_type": "weekday"}

    locks.lock_status = 400
    with pytest.raises(ServiceValidationError, match="bad_request"):
        await hass.services.async_call(DOMAIN, "clear_lock_schedule", data, blocking=True)
    locks.lock_status = 502
    with pytest.raises(HomeAssistantError, match="did not respond"):
        await hass.services.async_call(DOMAIN, "clear_lock_schedule", data, blocking=True)


SWITCH = "switch.z_wave_alarm_keypad_requires_pin_to_arm"


async def test_keypad_pin_switch_follows_the_snapshot(hass: HomeAssistant, service: FakeService, setup) -> None:
    service.keypad_settings = {"requireCodeToArm": True}
    await setup()
    await _settle(hass, service)

    assert hass.states.get(SWITCH).state == "on"


async def test_keypad_pin_switch_writes_the_setting_and_shows_it_at_once(hass: HomeAssistant, service: FakeService, setup) -> None:
    await setup()
    await _settle(hass, service)
    assert hass.states.get(SWITCH).state == "off"

    await hass.services.async_call("switch", "turn_on", {"entity_id": SWITCH}, blocking=True)
    assert service.keypad_settings_calls == [{"requireCodeToArm": True}]
    assert hass.states.get(SWITCH).state == "on"

    await hass.services.async_call("switch", "turn_off", {"entity_id": SWITCH}, blocking=True)
    assert service.keypad_settings_calls[-1] == {"requireCodeToArm": False}
    assert hass.states.get(SWITCH).state == "off"


async def test_keypad_pin_switch_follows_a_change_made_elsewhere(hass: HomeAssistant, service: FakeService, setup) -> None:
    await setup()
    await _settle(hass, service)

    await _push(hass, service, {"type": "keypad.settings", "settings": {"requireCodeToArm": True}})

    assert hass.states.get(SWITCH).state == "on"


async def test_keypad_pin_switch_refused_by_the_service_raises_and_stays_put(hass: HomeAssistant, service: FakeService, setup) -> None:
    service.keypad_settings_status = 403
    await setup()
    await _settle(hass, service)

    with pytest.raises(HomeAssistantError):
        await hass.services.async_call("switch", "turn_on", {"entity_id": SWITCH}, blocking=True)
    assert hass.states.get(SWITCH).state == "off"


async def test_no_keypad_pin_switch_without_keypads_or_on_an_older_service(hass: HomeAssistant, service: FakeService, setup) -> None:
    service.keypads = None
    await setup()
    await _settle(hass, service)
    assert hass.states.get(SWITCH) is None


async def test_no_keypad_pin_switch_when_the_service_has_no_keypad_settings(hass: HomeAssistant, service: FakeService, setup) -> None:
    service.keypad_settings = None
    await setup()
    await _settle(hass, service)
    assert hass.states.get(SWITCH) is None


# --- Lock lifecycle: a device exists only while the service reports (enrolls) the lock -----------------------------------


async def test_paired_locks_never_create_devices_or_entities(hass: HomeAssistant, service: FakeService, setup) -> None:
    """Paired-but-not-enrolled locks are only in `GET /locks/available`; the snapshot carries none, so none exist in HA."""
    service.locks = []
    entry = await setup()
    await _settle(hass, service)

    assert _device(hass, entry, f"{entry.entry_id}_lock_21") is None
    assert not [st for st in hass.states.async_all() if "_lock_" in st.entity_id or "door_lock" in st.entity_id]


async def test_enrolling_adds_and_unenrolling_removes_the_lock_device(hass: HomeAssistant, service: FakeService, setup) -> None:
    service.locks = []
    entry = await setup()
    await _settle(hass, service)

    await _push(hass, service, {"type": "lock.changed", "lock": copy.deepcopy(BE469)})
    assert _device(hass, entry, f"{entry.entry_id}_lock_21") is not None
    assert hass.states.get("sensor.front_door_lock_battery").state == "80"

    await _push(hass, service, {"type": "lock.removed", "nodeId": 21})
    assert _device(hass, entry, f"{entry.entry_id}_lock_21") is None
    assert hass.states.get("sensor.front_door_lock_battery") is None

    await _push(hass, service, {"type": "lock.changed", "lock": copy.deepcopy(BE469)})  # re-enrol
    assert _device(hass, entry, f"{entry.entry_id}_lock_21") is not None
    assert hass.states.get("sensor.front_door_lock_battery").state == "80"


async def test_only_the_unenrolled_lock_loses_its_device(hass: HomeAssistant, service: FakeService, setup, locks) -> None:
    entry = await setup()
    await _settle(hass, service)
    await _push(hass, service, {"type": "lock.removed", "nodeId": 21})
    assert _device(hass, entry, f"{entry.entry_id}_lock_21") is None
    assert _device(hass, entry, f"{entry.entry_id}_lock_{BE468['nodeId']}") is not None


async def test_stale_lock_device_is_pruned_on_the_first_snapshot(hass: HomeAssistant, service: FakeService, setup) -> None:
    """A lock unenrolled while HA was down must not linger as a device."""
    service.locks = []
    entry = MockConfigEntry(
        domain=DOMAIN, data={CONF_HOST: "127.0.0.1", CONF_PORT: service.port, CONF_SSL: False}, version=2,
        unique_id=f"127.0.0.1:{service.port}",
    )
    entry.add_to_hass(hass)
    dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={(DOMAIN, f"{entry.entry_id}_lock_21")}, name="Old lock"
    )
    await hass.config_entries.async_setup(entry.entry_id)
    await _settle(hass, service)
    assert _device(hass, entry, f"{entry.entry_id}_lock_21") is None
    await hass.config_entries.async_unload(entry.entry_id)


async def test_an_enrolled_lock_device_cannot_be_deleted_by_hand(hass: HomeAssistant, service: FakeService, setup, locks) -> None:
    from custom_components.zwave_alarm import async_remove_config_entry_device

    entry = await setup()
    await _settle(hass, service)
    assert not await async_remove_config_entry_device(hass, entry, _device(hass, entry, f"{entry.entry_id}_lock_21"))
    assert await async_remove_config_entry_device(hass, entry, _device(hass, entry, f"{entry.entry_id}_keypad_12"))
