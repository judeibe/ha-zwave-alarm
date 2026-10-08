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

    async def stream(self, request: web.Request) -> web.StreamResponse:
        self._note(request)
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        self.sockets.append(ws)
        snapshot = {"type": "snapshot", "panel": PANEL, "zones": copy.deepcopy(self.zones)}
        if self.keypads is not None:
            snapshot["keypads"] = copy.deepcopy(self.keypads)
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

    device = dr.async_get(hass).async_get_device_by_identifier((DOMAIN, f"{entry.entry_id}_keypad_12"), entry.entry_id)
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
    return dr.async_get(hass).async_get_device_by_identifier((DOMAIN, f"{entry.entry_id}_keypad_{node_id}"), entry.entry_id).id


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
    panel_device = dr.async_get(hass).async_get_device_by_identifier((DOMAIN, entry.entry_id), entry.entry_id)

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
