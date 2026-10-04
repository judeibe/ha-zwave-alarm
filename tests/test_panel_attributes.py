"""Tests for the zone-restricted-guest / trigger attributes added to the panel and zone entities (FR-010a)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "custom_components" / "zwave_alarm"))

from fault_state import faulted_sensors  # noqa: E402
from panel_state import panel_attributes  # noqa: E402
from zone_state import zone_is_disarmed  # noqa: E402

ZONES = [{"id": "z1", "name": "Downstairs", "sensors": []}, {"id": "z2", "name": "Garage", "sensors": []}]


def test_panel_attributes_resolve_zone_names() -> None:
    panel = {
        "mode": "alarm_triggered",
        "armedMode": "armed_away",
        "pendingDelayEndsAt": None,
        "disarmedZoneIds": ["z1"],
        "triggeredBy": {"sensorId": "s9", "zoneId": "z2"},
    }

    assert panel_attributes(panel, ZONES) == {
        "armed_mode": "armed_away",
        "pending_delay_ends_at": None,
        "disarmed_zones": ["Downstairs"],
        "triggered_by_zone": "Garage",
        "triggered_by_sensor_id": "s9",
    }


def test_panel_attributes_tolerate_missing_fields_and_unknown_zone() -> None:
    attributes = panel_attributes({"mode": "disarmed", "disarmedZoneIds": ["gone"]}, ZONES)

    assert attributes["disarmed_zones"] == ["gone"]
    assert attributes["armed_mode"] is None
    assert attributes["triggered_by_zone"] is None


def test_zone_is_disarmed() -> None:
    panel = {"disarmedZoneIds": ["z1"]}

    assert zone_is_disarmed("z1", panel) is True
    assert zone_is_disarmed("z2", panel) is False
    assert zone_is_disarmed("z1", None) is False
    assert zone_is_disarmed("z1", {}) is False


def test_faulted_sensors_reports_zone_and_reasons() -> None:
    zones = [
        {
            "name": "Hall",
            "sensors": [
                {"name": "Door", "connectivityStatus": "offline", "batteryLevel": 5},
                {"name": "Motion", "connectivityStatus": "online", "batteryLevel": 80},
                {"name": "Window", "connectivityStatus": "online", "batteryLevel": 10},
            ],
        }
    ]

    assert faulted_sensors(zones) == [
        {"name": "Door", "zone": "Hall", "reasons": ["offline", "low_battery"]},
        {"name": "Window", "zone": "Hall", "reasons": ["low_battery"]},
    ]
