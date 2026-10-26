"""Tests for coordinator_state.py's pure event-application/backoff logic (T039)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "custom_components" / "zwave_alarm"))

from coordinator_state import (  # noqa: E402
    RECONNECT_BASE_DELAY,
    RECONNECT_MAX_DELAY,
    StreamState,
    apply_event,
    merge_panel,
    next_backoff,
    references_unknown_sensor,
    security_event_payload,
)


def _sensor(sensor_id: str, category: str = "intrusion", state: str = "normal", **overrides) -> dict:
    sensor = {
        "id": sensor_id,
        "category": category,
        "currentState": state,
        "connectivityStatus": "online",
        "batteryLevel": 100,
    }
    sensor.update(overrides)
    return sensor


def _zone(zone_id: str, sensors: list[dict]) -> dict:
    return {"id": zone_id, "name": zone_id, "sensors": sensors}


def test_snapshot_replaces_entire_state() -> None:
    state = StreamState(panel={"mode": "disarmed", "pendingDelayEndsAt": None}, zones=[])
    event = {
        "type": "snapshot",
        "panel": {"mode": "armed_away", "pendingDelayEndsAt": None},
        "zones": [_zone("z1", [_sensor("s1")])],
    }

    new_state = apply_event(state, event)

    assert new_state.panel == {"mode": "armed_away", "pendingDelayEndsAt": None}
    assert new_state.zones == [_zone("z1", [_sensor("s1")])]


def test_panel_changed_updates_mode_and_pending_delay() -> None:
    state = StreamState(panel={"mode": "arming", "pendingDelayEndsAt": 123}, zones=[])
    event = {"type": "panel.changed", "mode": "armed_away", "pendingDelayEndsAt": None, "triggeredBy": None}

    new_state = apply_event(state, event)

    assert new_state.panel == {
        "mode": "armed_away",
        "pendingDelayEndsAt": None,
        "disarmedZoneIds": [],
        "triggeredBy": None,
        "exitEndsAt": None,
        "entryEndsAt": None,
        "bypassedDeviceIds": [],
    }


def test_panel_changed_carries_disarmed_zones_and_trigger() -> None:
    state = StreamState(panel={"mode": "armed_away", "pendingDelayEndsAt": None, "disarmedZoneIds": []}, zones=[])
    trigger = {"sensorId": "s1", "zoneId": "z2"}
    event = {
        "type": "panel.changed",
        "mode": "alarm_triggered",
        "pendingDelayEndsAt": None,
        "disarmedZoneIds": ["z1"],
        "triggeredBy": trigger,
    }

    panel = apply_event(state, event).panel

    assert panel["disarmedZoneIds"] == ["z1"]
    assert panel["triggeredBy"] == trigger


def test_panel_changed_to_disarmed_clears_armed_mode() -> None:
    state = StreamState(panel={"mode": "armed_home", "armedMode": "armed_home", "disarmedZoneIds": ["z1"]}, zones=[])
    event = {"type": "panel.changed", "mode": "disarmed", "pendingDelayEndsAt": None, "disarmedZoneIds": []}

    panel = apply_event(state, event).panel

    assert panel["armedMode"] is None
    assert panel["disarmedZoneIds"] == []


def test_panel_changed_is_noop_before_any_snapshot() -> None:
    state = StreamState(panel=None, zones=[])
    event = {"type": "panel.changed", "mode": "armed_away", "pendingDelayEndsAt": None, "triggeredBy": None}

    new_state = apply_event(state, event)

    assert new_state.panel is None


def test_sensor_changed_updates_matching_sensor_only() -> None:
    state = StreamState(
        panel=None,
        zones=[_zone("z1", [_sensor("s1"), _sensor("s2")])],
    )
    event = {"type": "sensor.changed", "sensorId": "s1", "zoneId": "z1", "currentState": "breached", "category": "intrusion"}

    new_state = apply_event(state, event)

    sensors = {s["id"]: s for s in new_state.zones[0]["sensors"]}
    assert sensors["s1"]["currentState"] == "breached"
    assert sensors["s2"]["currentState"] == "normal"


def test_sensor_events_do_not_mutate_the_original_state() -> None:
    state = StreamState(panel=None, zones=[_zone("z1", [_sensor("s1"), _sensor("s2")]), _zone("z2", [_sensor("s3")])])
    changed = {"type": "sensor.changed", "sensorId": "s1", "zoneId": "z1", "currentState": "breached", "category": "intrusion"}
    fault = {"type": "sensor.fault", "sensorId": "s1", "connectivityStatus": "offline", "batteryLevel": 8}

    after_change = apply_event(state, changed)
    after_fault = apply_event(after_change, fault)

    assert after_change is not state
    assert after_change.zones is not state.zones
    assert state.zones[0]["sensors"][0]["currentState"] == "normal"
    assert after_change.zones[0]["sensors"][0]["currentState"] == "breached"
    # Untouched zones are shared, not copied.
    assert after_change.zones[1] is state.zones[1]
    assert after_change.zones[0]["sensors"][1] is state.zones[0]["sensors"][1]
    assert after_change.zones[0]["sensors"][0]["connectivityStatus"] == "online"
    assert after_fault.zones[0]["sensors"][0]["batteryLevel"] == 8
    assert after_fault.zones[0]["sensors"][0]["currentState"] == "breached"


def test_sensor_changed_unknown_sensor_id_is_noop() -> None:
    state = StreamState(panel=None, zones=[_zone("z1", [_sensor("s1")])])
    event = {"type": "sensor.changed", "sensorId": "unknown", "zoneId": "z1", "currentState": "breached", "category": "intrusion"}

    new_state = apply_event(state, event)

    assert new_state.zones[0]["sensors"][0]["currentState"] == "normal"


def test_sensor_fault_updates_connectivity_and_battery() -> None:
    state = StreamState(panel=None, zones=[_zone("z1", [_sensor("s1")])])
    event = {"type": "sensor.fault", "sensorId": "s1", "connectivityStatus": "offline", "batteryLevel": 8}

    new_state = apply_event(state, event)

    sensor = new_state.zones[0]["sensors"][0]
    assert sensor["connectivityStatus"] == "offline"
    assert sensor["batteryLevel"] == 8


def test_event_recorded_and_unknown_types_are_noop() -> None:
    state = StreamState(panel={"mode": "disarmed", "pendingDelayEndsAt": None}, zones=[_zone("z1", [_sensor("s1")])])

    for event in (
        {"type": "event.recorded", "event": {"id": "e1", "type": "lockout", "occurredAt": "2026-01-01T00:00:00Z"}},
        {"type": "something.unrecognized"},
    ):
        new_state = apply_event(state, event)
        assert new_state.panel == state.panel
        assert new_state.zones == state.zones


def test_merge_panel_overwrites_mode_and_pending_delay() -> None:
    state = StreamState(panel={"mode": "arming", "pendingDelayEndsAt": 123}, zones=[])

    new_state = merge_panel(state, {"mode": "armed_away", "pendingDelayEndsAt": None})

    assert new_state.panel["mode"] == "armed_away"
    assert new_state.panel["pendingDelayEndsAt"] is None


def test_merge_panel_keeps_zone_restricted_disarm_and_armed_mode() -> None:
    state = StreamState(panel=None, zones=[])
    rest_panel = {
        "mode": "armed_away",
        "pendingDelayEndsAt": None,
        "armedMode": "armed_away",
        "disarmedZoneIds": ["z1"],
        "triggeredBy": None,
    }

    panel = merge_panel(state, rest_panel).panel

    assert panel["disarmedZoneIds"] == ["z1"]
    assert panel["armedMode"] == "armed_away"


def test_merge_panel_works_when_no_prior_panel_exists() -> None:
    state = StreamState(panel=None, zones=[])

    new_state = merge_panel(state, {"mode": "disarmed", "pendingDelayEndsAt": None})

    assert new_state.panel["mode"] == "disarmed"
    assert new_state.panel["disarmedZoneIds"] == []


def test_references_unknown_sensor() -> None:
    state = StreamState(panel=None, zones=[_zone("z1", [_sensor("s1")])])

    assert references_unknown_sensor(state, {"type": "sensor.changed", "sensorId": "new"}) is True
    assert references_unknown_sensor(state, {"type": "sensor.fault", "sensorId": "new"}) is True
    assert references_unknown_sensor(state, {"type": "sensor.changed", "sensorId": "s1"}) is False
    assert references_unknown_sensor(state, {"type": "panel.changed", "mode": "disarmed"}) is False


def test_security_event_payload_exposes_details_for_cleared_by() -> None:
    event = {
        "type": "event.recorded",
        "event": {"id": "e1", "type": "alarm_cleared", "occurredAt": 5, "details": "Cleared by Owner"},
    }

    assert security_event_payload(event) == (
        "alarm_cleared",
        {"event_id": "e1", "occurred_at": 5, "details": "Cleared by Owner", "actor": None, "device_id": None, "device_name": None},
    )


def test_security_event_payload_carries_who_and_which_device() -> None:
    event = {
        "type": "event.recorded",
        "event": {"id": "e2", "type": "tamper", "occurredAt": 6, "details": "Cover removed", "actor": "Alex",
                  "deviceId": "s1", "deviceName": "Front door"},
    }
    _, attrs = security_event_payload(event)
    assert (attrs["actor"], attrs["device_id"], attrs["device_name"]) == ("Alex", "s1", "Front door")


_SCHEDULE = {"id": "m1", "name": "Night", "mode": "armed_home", "time": "22:00", "days": ["mon"], "enabled": True, "timeZone": None, "lastRunAt": None}


def test_snapshot_carries_mode_schedules_and_the_stream_changes_them() -> None:
    state = apply_event(
        StreamState(panel=None, zones=[]), {"type": "snapshot", "panel": {"mode": "disarmed"}, "zones": [], "modeSchedules": [_SCHEDULE]}
    )
    assert state.mode_schedules == [_SCHEDULE]
    state = apply_event(state, {"type": "mode-schedule.changed", "schedule": {**_SCHEDULE, "enabled": False}})
    state = apply_event(state, {"type": "mode-schedule.changed", "schedule": {**_SCHEDULE, "id": "m2", "name": "Morning", "time": "06:30"}})
    assert [(x["id"], x["enabled"]) for x in state.mode_schedules] == [("m2", True), ("m1", False)]  # by time of day
    assert [x["id"] for x in apply_event(state, {"type": "mode-schedule.removed", "id": "m2"}).mode_schedules] == ["m1"]


def test_a_snapshot_from_an_older_service_has_no_mode_schedules() -> None:
    state = apply_event(StreamState(panel=None, zones=[]), {"type": "snapshot", "panel": {"mode": "disarmed"}, "zones": []})
    assert state.mode_schedules == []


def test_next_backoff_doubles_from_base_up_to_cap() -> None:
    assert next_backoff(0) == RECONNECT_BASE_DELAY
    assert next_backoff(1) == RECONNECT_BASE_DELAY * 2
    assert next_backoff(2) == RECONNECT_BASE_DELAY * 4
    assert next_backoff(3) == RECONNECT_BASE_DELAY * 8


def test_next_backoff_caps_at_max_delay() -> None:
    assert next_backoff(10) == RECONNECT_MAX_DELAY
    assert next_backoff(100) == RECONNECT_MAX_DELAY


_MODES = {"armed_home": {"entryDelaySec": 60, "exitDelaySec": 60}, "armed_away": {"entryDelaySec": 45, "exitDelaySec": 30}}


def test_snapshot_carries_per_mode_delays() -> None:
    state = apply_event(StreamState(panel=None, zones=[]), {"type": "snapshot", "panel": {"mode": "disarmed"}, "zones": [], "modes": _MODES})
    assert state.modes == _MODES


def test_snapshot_from_an_older_service_leaves_modes_unset() -> None:
    state = apply_event(StreamState(panel=None, zones=[]), {"type": "snapshot", "panel": {"mode": "disarmed"}, "zones": []})
    assert state.modes is None


def test_panel_changed_updates_modes_and_keeps_them_when_absent() -> None:
    start = StreamState(panel={"mode": "disarmed"}, zones=[], modes=_MODES)
    changed = {"type": "panel.changed", "mode": "arming", "pendingDelayEndsAt": 1}
    assert apply_event(start, changed).modes == _MODES
    new_modes = {**_MODES, "armed_home": {"entryDelaySec": 10, "exitDelaySec": 20}}
    assert apply_event(start, {**changed, "modes": new_modes}).modes == new_modes


def _alarm_event(event_id: str, started: int, **changes) -> dict:
    return {"id": event_id, "type": "BURGLARY", "startedAt": started, "sirenState": "sounding", "endedAt": None, **changes}


def test_snapshot_keeps_only_the_open_alarm_events() -> None:
    open_event, ended = _alarm_event("a", 1), _alarm_event("b", 2, endedAt=5)
    state = apply_event(
        StreamState(panel=None, zones=[]),
        {"type": "snapshot", "panel": {"mode": "disarmed"}, "zones": [], "alarmEvents": [open_event, ended]},
    )
    assert state.alarm_events == [open_event]


def test_alarm_event_adds_updates_and_closes_an_event() -> None:
    state = StreamState(panel=None, zones=[])
    state = apply_event(state, {"type": "alarm.event", "event": _alarm_event("a", 1)})
    state = apply_event(state, {"type": "alarm.event", "event": _alarm_event("b", 2, type="SMOKE")})
    state = apply_event(state, {"type": "alarm.event", "event": _alarm_event("a", 1, sirenState="silenced")})
    assert [(e["id"], e["sirenState"]) for e in state.alarm_events] == [("a", "silenced"), ("b", "sounding")]

    state = apply_event(state, {"type": "alarm.event", "event": _alarm_event("a", 1, endedAt=9)})
    assert [e["id"] for e in state.alarm_events] == ["b"]


def test_a_snapshot_from_an_older_service_has_no_alarm_events() -> None:
    state = apply_event(StreamState(panel=None, zones=[]), {"type": "snapshot", "panel": {"mode": "disarmed"}, "zones": []})
    assert state.alarm_events == []


_SIREN = {"nodeId": 14, "kind": "OUTDOOR", "name": "Garden", "durationSec": 180, "createdAt": 1}


def test_snapshot_carries_the_enrolled_sirens() -> None:
    state = apply_event(
        StreamState(panel=None, zones=[]), {"type": "snapshot", "panel": {"mode": "disarmed"}, "zones": [], "sirens": [_SIREN]}
    )
    assert state.sirens == [_SIREN]


def test_siren_changed_adds_or_replaces_and_siren_removed_drops() -> None:
    state = apply_event(StreamState(panel=None, zones=[]), {"type": "siren.changed", "siren": _SIREN})
    state = apply_event(state, {"type": "siren.changed", "siren": {**_SIREN, "durationSec": 300}})
    state = apply_event(state, {"type": "siren.changed", "siren": {**_SIREN, "nodeId": 3, "kind": "BASE", "durationSec": 600}})
    assert [(s["nodeId"], s["durationSec"]) for s in state.sirens] == [(3, 600), (14, 300)]
    assert apply_event(state, {"type": "siren.removed", "nodeId": 3}).sirens == [{**_SIREN, "durationSec": 300}]


def test_sensor_fault_carries_tampered_and_keeps_it_when_absent() -> None:
    state = StreamState(panel=None, zones=[_zone("z1", [_sensor("s1", tampered=False)])])
    fault = {"type": "sensor.fault", "sensorId": "s1", "connectivityStatus": "online", "batteryLevel": 90}
    assert apply_event(state, {**fault, "tampered": True}).zones[0]["sensors"][0]["tampered"] is True
    assert apply_event(state, fault).zones[0]["sensors"][0]["tampered"] is False


def test_sensor_updated_merges_what_the_service_returned() -> None:
    state = StreamState(panel=None, zones=[_zone("z1", [_sensor("s1", chirpTone="double_beep")])])
    new = apply_event(state, {"type": "sensor.updated", "sensor": {"id": "s1", "chirpTone": "doorbell"}})
    assert new.zones[0]["sensors"][0]["chirpTone"] == "doorbell"
    assert new.zones[0]["sensors"][0]["batteryLevel"] == 100  # the rest is kept
    assert apply_event(state, {"type": "sensor.updated", "sensor": {"id": "nope", "chirpTone": "none"}}) == state
