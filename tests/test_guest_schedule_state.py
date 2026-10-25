"""Tests for guest_schedule_state.py's pure validation."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "custom_components" / "zwave_alarm"))

from guest_schedule_state import InvalidSchedule, check_schedule, normalize_time, schedule_fields  # noqa: E402


@pytest.mark.parametrize(("raw", "expected"), [("08:00", "08:00"), ("08:00:00", "08:00"), ("23:59:30", "23:59"), (None, None)])
def test_normalize_time(raw, expected) -> None:
    assert normalize_time(raw) == expected


@pytest.mark.parametrize("raw", ["8:00", "24:00", "08:60", "noon", ""])
def test_normalize_time_rejects_other_shapes(raw) -> None:
    with pytest.raises(InvalidSchedule):
        normalize_time(raw)


def test_a_timed_schedule_needs_distinct_start_and_end() -> None:
    check_schedule(["mon"], False, "08:00", "17:30")
    check_schedule(["mon"], False, "22:00", "06:00")  # overnight
    with pytest.raises(InvalidSchedule, match="differ"):
        check_schedule(["mon"], False, "08:00", "08:00")
    with pytest.raises(InvalidSchedule, match="start and an end"):
        check_schedule(["mon"], False, "08:00", None)


def test_an_all_day_schedule_needs_no_times() -> None:
    check_schedule(["sat", "sun"], True, None, None)


@pytest.mark.parametrize(("days", "message"), [([], "at least one"), (["mon", "mon"], "once"), (["funday"], "Unknown day")])
def test_days_are_checked(days, message) -> None:
    with pytest.raises(InvalidSchedule, match=message):
        check_schedule(days, True, None, None)


def test_schedule_fields_keeps_only_what_was_given_and_trims_times() -> None:
    assert schedule_fields({"name": "Cleaners", "start": "08:00:00", "time_zone": "America/Chicago", "other": 1}) == {
        "name": "Cleaners",
        "start": "08:00",
        "time_zone": "America/Chicago",
    }


def test_check_mode_schedule_checks_only_what_is_given() -> None:
    from guest_schedule_state import check_mode_schedule

    check_mode_schedule(None, None, None)
    check_mode_schedule("armed_home", "22:00:00", ["mon"])
    with pytest.raises(InvalidSchedule, match="mode"):
        check_mode_schedule("armed_night", None, None)
    with pytest.raises(InvalidSchedule, match="Times"):
        check_mode_schedule(None, "10pm", None)
    with pytest.raises(InvalidSchedule, match="at least one"):
        check_mode_schedule(None, None, [])
