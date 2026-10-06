"""Pure keypad logic: state folding and event payload mapping, tested without Home Assistant."""

from custom_components.zwave_alarm.coordinator_state import StreamState, apply_event
from custom_components.zwave_alarm.keypad_state import keypad_battery_level, keypad_event_payload, keypad_is_online

KEYPAD = {"nodeId": 12, "connectivityStatus": "online", "batteryLevel": 87}


def _state(keypads=None) -> StreamState:
    return StreamState(panel={"mode": "disarmed"}, zones=[], keypads=keypads or [])


def test_snapshot_carries_keypads() -> None:
    state = apply_event(_state(), {"type": "snapshot", "panel": {"mode": "disarmed"}, "zones": [], "keypads": [KEYPAD]})
    assert state.keypads == [KEYPAD]


def test_snapshot_without_keypads_clears_them() -> None:
    state = apply_event(_state([KEYPAD]), {"type": "snapshot", "panel": {"mode": "disarmed"}, "zones": []})
    assert state.keypads == []


def test_keypad_changed_adds_then_replaces() -> None:
    state = apply_event(_state(), {"type": "keypad.changed", "keypad": KEYPAD})
    assert state.keypads == [KEYPAD]
    updated = {**KEYPAD, "batteryLevel": 10, "connectivityStatus": "offline"}
    state = apply_event(state, {"type": "keypad.changed", "keypad": updated})
    assert state.keypads == [updated]


def test_keypad_changed_keeps_nodes_sorted_and_other_state() -> None:
    other = {**KEYPAD, "nodeId": 3}
    state = apply_event(_state([KEYPAD]), {"type": "keypad.changed", "keypad": other})
    assert [k["nodeId"] for k in state.keypads] == [3, 12]
    assert state.panel == {"mode": "disarmed"}


def test_panel_changed_preserves_keypads() -> None:
    state = apply_event(
        _state([KEYPAD]),
        {"type": "panel.changed", "mode": "armed_away", "pendingDelayEndsAt": None, "disarmedZoneIds": []},
    )
    assert state.keypads == [KEYPAD]


def test_keypad_event_does_not_change_state() -> None:
    state = _state([KEYPAD])
    assert apply_event(state, {"type": "keypad.event", "nodeId": 12, "input": {"kind": "arm_away"}}) is state


def test_event_payload_for_each_known_kind() -> None:
    for kind in ("code_entered", "arm_away", "arm_home", "disarm", "cancel"):
        event = {"type": "keypad.event", "nodeId": 12, "adapterId": "ring-keypad-v2", "input": {"kind": kind}}
        assert keypad_event_payload(event) == (12, kind, {"adapter_id": "ring-keypad-v2"})


def test_emergency_payload_carries_the_emergency_kind() -> None:
    event = {"nodeId": 12, "adapterId": "a", "input": {"kind": "emergency", "emergency": "fire"}}
    assert keypad_event_payload(event) == (12, "emergency", {"adapter_id": "a", "emergency": "fire"})


def test_payload_never_forwards_a_code() -> None:
    event = {"nodeId": 12, "input": {"kind": "code_entered", "code": "1234"}}
    assert "1234" not in str(keypad_event_payload(event))


def test_unknown_or_malformed_events_are_ignored() -> None:
    assert keypad_event_payload({"nodeId": 12, "input": {"kind": "wave_hello"}}) is None
    assert keypad_event_payload({"nodeId": 12, "input": {}}) is None
    assert keypad_event_payload({"nodeId": 12}) is None
    assert keypad_event_payload({"input": {"kind": "arm_away"}}) is None


def test_online_and_battery_helpers() -> None:
    assert keypad_is_online(KEYPAD)
    assert not keypad_is_online({"connectivityStatus": "offline"})
    assert keypad_battery_level(KEYPAD) == 87
    assert keypad_battery_level({"batteryLevel": None}) is None
    assert keypad_battery_level({}) is None
