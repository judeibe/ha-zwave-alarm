"""Pure Schlage lock logic: state folding, option mapping, slot decoding and schedule validation."""

from datetime import datetime, time, timedelta

import pytest
import voluptuous as vol

from custom_components.zwave_alarm.coordinator_state import StreamState, apply_event
from custom_components.zwave_alarm.lock_state import (
    decode_occupied_slots,
    lock_battery_level,
    lock_supports,
    occupied_slot_count,
    occupied_slots,
    pin_length_valid,
    schedule_from_service,
    schedule_slot_count,
    sensitivity_option,
    alarm_mode_option,
    validate_schedule,
)

BE469 = {
    "nodeId": 21,
    "supportedSettings": ["beeper", "pinLength", "alarmMode", "localControls"],
    "batteryLevel": 80,
    "settings": {"pinLength": 4},
    "diagnostics": {"occupiedUserSlots": [9, 1, 2]},
}
BE468 = {"nodeId": 22, "supportedSettings": ["beeper", "pinLength"]}


def _state(locks=None) -> StreamState:
    return StreamState(panel={"mode": "disarmed"}, zones=[], locks=locks or [])


def test_snapshot_carries_locks_and_defaults_to_none() -> None:
    event = {"type": "snapshot", "panel": {"mode": "disarmed"}, "zones": [], "locks": [BE469]}
    assert apply_event(_state(), event).locks == [BE469]
    del event["locks"]
    assert apply_event(_state([BE469]), event).locks == []


def test_lock_changed_adds_replaces_and_sorts() -> None:
    state = apply_event(_state([BE469]), {"type": "lock.changed", "lock": BE468})
    assert [lk["nodeId"] for lk in state.locks] == [21, 22]
    updated = {**BE469, "batteryLevel": 10}
    state = apply_event(state, {"type": "lock.changed", "lock": updated})
    assert state.locks == [updated, BE468]
    assert state.panel == {"mode": "disarmed"}


def test_other_events_preserve_locks() -> None:
    state = apply_event(
        _state([BE469]),
        {"type": "panel.changed", "mode": "armed_away", "pendingDelayEndsAt": None, "disarmedZoneIds": [], "triggeredBy": None},
    )
    assert state.locks == [BE469]


def test_settings_are_gated_on_supported_settings() -> None:
    assert lock_supports(BE469, "alarmMode") and lock_supports(BE469, "localControls")
    assert lock_supports(BE468, "beeper")
    assert not lock_supports(BE468, "alarmMode")  # BE469 only
    assert not lock_supports({}, "beeper")
    assert not lock_supports({"supportedSettings": None}, "beeper")


def test_battery_and_slot_accessors_tolerate_missing_data() -> None:
    assert lock_battery_level(BE469) == 80
    assert lock_battery_level(BE468) is None
    assert occupied_slots(BE469) == [1, 2, 9]
    assert occupied_slot_count(BE469) == 3
    assert occupied_slot_count(BE468) is None
    assert occupied_slots(BE468) == []


@pytest.mark.parametrize(
    ("value", "option"),
    [(0, None), (1, "most_sensitive"), (2, "high"), (3, "medium"), (4, "low"), (5, "least_sensitive"), (6, None), (True, None), (None, None)],
)
def test_sensitivity_option(value, option) -> None:
    assert sensitivity_option(value) == option


def test_alarm_mode_option_rejects_unknown_modes() -> None:
    assert alarm_mode_option("forced_entry") == "forced_entry"
    assert alarm_mode_option("siren") is None


def test_decode_occupied_slots_bit_layout() -> None:
    assert decode_occupied_slots([0, 0, 0, 0]) == []
    assert decode_occupied_slots([0b00000101, 0, 0, 0]) == [1, 3]  # LSB is the lowest slot
    assert decode_occupied_slots([0, 0, 0b10000000, 0]) == [24]
    assert decode_occupied_slots([0, 0, 0, 0b00100001]) == [25, 30]  # byte 4 covers slots 25-30
    assert decode_occupied_slots([0, 0, 0, 0b11000000]) == []  # bits past slot 30 are padding
    assert decode_occupied_slots(bytes([255, 255, 255, 63])) == list(range(1, 31))


@pytest.mark.parametrize(("code", "length", "ok"), [
    ("1234", 4, True), ("12345678", 8, True), ("123", 3, False), ("123456789", 9, False),
    ("1234", 6, False), ("12a4", 4, False), ("", 4, False),
])
def test_pin_length_valid(code, length, ok) -> None:
    assert pin_length_valid(code, length) is ok


def test_weekday_schedule_validates_and_coerces() -> None:
    fields = {"weekday": "1", "startHour": "8", "startMinute": 0, "stopHour": 17, "stopMinute": 30}
    assert validate_schedule("weekday", fields) == {
        "weekday": 1, "startHour": 8, "startMinute": 0, "stopHour": 17, "stopMinute": 30,
    }


@pytest.mark.parametrize("change", [
    {"weekday": 7}, {"startHour": 24}, {"stopMinute": 60}, {"startHour": 18}, {"stopHour": 8, "stopMinute": 0},
])
def test_weekday_schedule_rejects_bad_values(change) -> None:
    fields = {"weekday": 1, "startHour": 8, "startMinute": 0, "stopHour": 17, "stopMinute": 30, **change}
    with pytest.raises(vol.Invalid):
        validate_schedule("weekday", fields)


def test_yearday_schedule_requires_start_before_stop() -> None:
    fields = {
        "startYear": 26, "startMonth": 1, "startDay": 2, "startHour": 0, "startMinute": 0,
        "stopYear": 26, "stopMonth": 1, "stopDay": 9, "stopHour": 23, "stopMinute": 59,
    }
    assert validate_schedule("yearday", fields) == fields
    with pytest.raises(vol.Invalid):  # four-digit years are the integration's input, not the service's
        validate_schedule("yearday", {**fields, "startYear": 2026})
    with pytest.raises(vol.Invalid):
        validate_schedule("yearday", {**fields, "stopDay": 2, "stopHour": 0, "stopMinute": 0})
    with pytest.raises(vol.Invalid):
        validate_schedule("yearday", {**fields, "startMonth": 13})


def test_daily_repeating_schedule() -> None:
    fields = {"weekdays": [1, 5], "startHour": 8, "startMinute": 0, "durationHour": 9, "durationMinute": 30}
    assert validate_schedule("daily_repeating", fields) == fields
    for bad in ({"weekdays": []}, {"weekdays": [1, 1]}, {"weekdays": [7]}, {"durationHour": 0, "durationMinute": 0}):
        with pytest.raises(vol.Invalid):
            validate_schedule("daily_repeating", {**fields, **bad})


def test_schedule_rejects_missing_unknown_and_foreign_fields() -> None:
    with pytest.raises(vol.Invalid):
        validate_schedule("weekday", {"weekday": "monday"})
    with pytest.raises(vol.Invalid, match="not valid"):
        validate_schedule("weekday", {"weekday": "monday", "startHour": 1, "startMinute": 0, "stopHour": 2, "stopMinute": 0, "weekdays": []})
    with pytest.raises(vol.Invalid):
        validate_schedule("hourly", {})


def test_schedule_slot_count_reads_per_kind_counts() -> None:
    lock = {"scheduleSlots": {"weekDay": 7, "yearDay": 4, "dailyRepeating": 0}}
    assert [schedule_slot_count(lock, k) for k in ("weekday", "yearday", "daily_repeating")] == [7, 4, 0]
    assert schedule_slot_count({"scheduleSlots": {"weekDay": 7}}, "daily_repeating") is None
    assert schedule_slot_count({}, "weekday") is None


def test_schedule_from_service_builds_each_kind() -> None:
    assert schedule_from_service("weekday", {"weekday": "friday", "start_time": time(8, 15), "end_time": time(17, 0)}) == {
        "weekday": 5, "startHour": 8, "startMinute": 15, "stopHour": 17, "stopMinute": 0,
    }
    assert schedule_from_service("yearday", {"start": datetime(2026, 1, 2, 9, 30), "end": datetime(2026, 2, 3, 18, 45)}) == {
        "startYear": 26, "startMonth": 1, "startDay": 2, "startHour": 9, "startMinute": 30,
        "stopYear": 26, "stopMonth": 2, "stopDay": 3, "stopHour": 18, "stopMinute": 45,
    }
    assert schedule_from_service(
        "daily_repeating", {"weekdays": ["monday", "friday"], "start_time": time(8, 0), "duration": timedelta(hours=9, minutes=30)}
    ) == {"weekdays": [1, 5], "startHour": 8, "startMinute": 0, "durationHour": 9, "durationMinute": 30}


def test_schedule_from_service_reports_missing_and_invalid_input() -> None:
    with pytest.raises(vol.Invalid, match="end_time"):
        schedule_from_service("weekday", {"weekday": "friday", "start_time": time(8, 0)})
    with pytest.raises(vol.Invalid, match="start"):
        schedule_from_service("weekday", {"weekday": "friday", "start_time": time(18, 0), "end_time": time(8, 0)})
    with pytest.raises(vol.Invalid):  # a day or more doesn't fit the hour field
        schedule_from_service("daily_repeating", {"weekdays": ["monday"], "start_time": time(8, 0), "duration": timedelta(days=1)})
    with pytest.raises(vol.Invalid):
        schedule_from_service("nonsense", {})


def test_schedule_from_service_rejects_years_outside_2000_2099() -> None:
    with pytest.raises(vol.Invalid, match="2000 and 2099"):
        schedule_from_service("yearday", {"start": datetime(1999, 1, 1), "end": datetime(2100, 1, 1)})
