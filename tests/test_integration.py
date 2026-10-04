"""End-to-end tests: a real Home Assistant core against a fake Z-Wave Alarm service (REST + WebSocket)."""

from __future__ import annotations

import asyncio
import copy
from typing import Any

import pytest
from aiohttp import WSMsgType, web
from aiohttp.test_utils import TestServer
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_ACCESS_TOKEN, CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.zwave_alarm.const import CONF_SSL, DOMAIN

TOKEN = "good-token"
SENSOR = {
    "id": "s1", "zwaveNodeId": 2, "zoneId": "z1", "name": "Front door", "category": "intrusion",
    "currentState": "normal", "batteryLevel": 90, "connectivityStatus": "online", "updatedAt": 0,
}
ZONES = [{"id": "z1", "name": "Downstairs", "sensors": [SENSOR]}]
PANEL = {"mode": "armed_away", "pendingDelayEndsAt": None, "disarmedZoneIds": []}


class FakeService:
    """Serves /panel, /zones, /panel/disarm and /stream; tests push messages via `broadcast`."""

    def __init__(self) -> None:
        self.zones = copy.deepcopy(ZONES)
        self.sockets: list[web.WebSocketResponse] = []
        self.connected = asyncio.Event()
        self.disarm_response: dict[str, Any] = {"mode": "disarmed", "pendingDelayEndsAt": None}
        self.disarm_calls: list[dict] = []

    def _authorized(self, request: web.Request) -> bool:
        return request.headers.get("Authorization") == f"Bearer {TOKEN}"

    async def panel(self, request: web.Request) -> web.Response:
        if not self._authorized(request):
            return web.json_response({"error": {"code": "unauthorized", "message": "no"}}, status=401)
        return web.json_response(PANEL)

    async def zones_handler(self, request: web.Request) -> web.Response:
        return web.json_response(self.zones)

    async def disarm(self, request: web.Request) -> web.Response:
        self.disarm_calls.append(await request.json())
        return web.json_response(self.disarm_response)

    async def stream(self, request: web.Request) -> web.StreamResponse:
        if not self._authorized(request):
            return web.Response(status=401)
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        self.sockets.append(ws)
        await ws.send_json({"type": "snapshot", "panel": PANEL, "zones": copy.deepcopy(self.zones)})
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

    async def _setup(token: str = TOKEN) -> MockConfigEntry:
        entry = MockConfigEntry(
            domain=DOMAIN,
            data={CONF_HOST: "127.0.0.1", CONF_PORT: service.port, CONF_ACCESS_TOKEN: token, CONF_SSL: False},
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


async def test_rejected_token_starts_reauth(hass: HomeAssistant, service: FakeService, setup) -> None:
    entry = await setup(token="revoked")
    await asyncio.sleep(0.2)
    await hass.async_block_till_done()

    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert [f["context"]["source"] for f in flows] == ["reauth"]
    assert hass.states.get("alarm_control_panel.zwave_alarm").state == "unavailable"

    result = await hass.config_entries.flow.async_configure(flows[0]["flow_id"], {CONF_ACCESS_TOKEN: "still-bad"})
    assert result["errors"] == {"base": "invalid_auth"}
    result = await hass.config_entries.flow.async_configure(flows[0]["flow_id"], {CONF_ACCESS_TOKEN: TOKEN})
    assert result["type"] == "abort" and result["reason"] == "reauth_successful"
    assert entry.data[CONF_ACCESS_TOKEN] == TOKEN
