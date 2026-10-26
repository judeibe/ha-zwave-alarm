"""Tests for lock_mode_state.py's pure helpers."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "custom_components" / "zwave_alarm"))

from lock_mode_state import (  # noqa: E402
    action_option,
    action_value,
    failed_locks,
    lock_event_payload,
    mode_settings,
    sync_summary,
)

SETTINGS = {"armOnLockWithCode": True, "armOnOneTouch": False, "disarmOnUnlock": False,
            "actions": {"disarmed": None, "armed_home": "lock", "armed_away": "unlock"}}


def test_mode_settings_is_none_for_a_lock_that_does_not_report_them() -> None:
    assert mode_settings({"nodeId": 44}) is None
    assert mode_settings(None) is None
    assert mode_settings({"modeSettings": SETTINGS}) == SETTINGS


def test_action_options_map_null_to_none_and_back() -> None:
    assert [action_option(SETTINGS, m) for m in ("disarmed", "armed_home", "armed_away")] == ["none", "lock", "unlock"]
    assert action_option(None, "disarmed") is None
    assert action_option({"actions": {}}, "armed_home") == "none"
    assert (action_value("none"), action_value("lock"), action_value("unlock")) == (None, "lock", "unlock")


def test_sync_summary_names_the_lock_and_keeps_a_failure_reason_only() -> None:
    sync = [{"nodeId": 44, "slot": 3, "status": "synced"}, {"nodeId": 9, "slot": 3, "status": "failed", "message": "asleep"}]
    summary = sync_summary(sync, {44: "Front door"})
    assert summary == [
        {"node_id": 44, "lock": "Front door", "slot": 3, "status": "synced"},
        {"node_id": 9, "lock": "Lock 9", "slot": 3, "status": "failed", "message": "asleep"},
    ]
    assert failed_locks(summary) == ["Lock 9"]
    assert sync_summary([]) == []


def test_lock_event_payload_splits_known_kinds_and_ignores_others() -> None:
    event = {"type": "lock.event", "nodeId": 44, "kind": "armed", "userId": "u1", "method": "keypad"}
    assert lock_event_payload(event) == (44, "armed", {"user_id": "u1", "method": "keypad"})
    assert lock_event_payload({**event, "kind": "exploded"}) is None
    assert lock_event_payload({"type": "lock.event", "kind": "locked"}) is None
    assert lock_event_payload({**event, "kind": "locked", "userId": None, "method": "manual"})[2] == {"user_id": None, "method": "manual"}
