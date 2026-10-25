"""Tests for alarm_event_state.py's pure helpers."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "custom_components" / "zwave_alarm"))

from alarm_event_state import current_event, event_attributes, event_state, siren_sounding  # noqa: E402

BURGLARY = {"id": "a", "type": "BURGLARY", "startedAt": 1, "sirenState": "sounding", "dispatchState": "held",
            "service": None, "triggerDeviceId": "s1", "cancelledAt": None, "details": None}
SMOKE = {**BURGLARY, "id": "b", "type": "SMOKE", "startedAt": 2, "sirenState": "silenced"}


def test_no_open_event() -> None:
    assert current_event([]) is None
    assert event_state([]) == "none"
    assert siren_sounding([]) is False
    assert event_attributes([]) == {"open_events": 0}


def test_the_newest_open_event_is_the_current_one() -> None:
    assert event_state([BURGLARY, SMOKE]) == "smoke"
    attrs = event_attributes([BURGLARY, SMOKE])
    assert (attrs["open_events"], attrs["event_id"], attrs["siren_state"], attrs["dispatch_state"]) == (2, "b", "silenced", "held")


def test_siren_sounding_follows_any_open_event_not_just_the_newest() -> None:
    assert siren_sounding([BURGLARY, SMOKE]) is True
    assert siren_sounding([SMOKE]) is False
