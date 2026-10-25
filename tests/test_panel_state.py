"""Tests for panel_state.map_panel_mode (T036)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "custom_components" / "zwave_alarm"))

from panel_state import map_panel_mode  # noqa: E402


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        ("disarmed", "disarmed"),
        ("arming", "arming"),
        ("armed_away", "armed_away"),
        ("armed_home", "armed_home"),
        ("alarm_pending", "pending"),
        ("alarm_triggered", "triggered"),
    ],
)
def test_maps_every_alarm_mode(mode: str, expected: str) -> None:
    assert map_panel_mode(mode) == expected


def test_raises_on_unknown_mode() -> None:
    with pytest.raises(ValueError, match="unknown_mode"):
        map_panel_mode("unknown_mode")


def test_describe_faulted_names_each_sensor_with_its_reason() -> None:
    from panel_state import describe_faulted

    faulted = [
        {"sensorId": "a", "name": "Front door", "reason": "open"},
        {"sensorId": "b", "name": "Garage", "reason": "not_set_up"},
        {"sensorId": "c", "reason": "weird"},
    ]
    assert describe_faulted(faulted) == "Front door (open), Garage (not set up), c (weird)"


def test_panel_attributes_include_timers_and_bypassed_devices() -> None:
    from panel_state import panel_attributes

    attrs = panel_attributes({"mode": "arming", "exitEndsAt": 10, "entryEndsAt": None, "bypassedDeviceIds": ["s1"]}, [])
    assert (attrs["exit_ends_at"], attrs["entry_ends_at"], attrs["bypassed_device_ids"]) == (10, None, ["s1"])
    assert panel_attributes({"mode": "disarmed"}, [])["bypassed_device_ids"] == []


def test_describe_faulted_says_tampered() -> None:
    from panel_state import describe_faulted

    assert describe_faulted([{"sensorId": "a", "name": "Back door", "reason": "tampered"}]) == "Back door (tampered)"
