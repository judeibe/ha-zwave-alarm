"""Pure mapping from this service's AlarmPanel.mode to Home Assistant's
alarm_control_panel state strings.

Split out from alarm_control_panel.py so it can be unit tested without Home
Assistant installed: the `homeassistant` package's dependency pins are
incompatible with this repo's Python version (same constraint noted in
the README's "Testing" note), so anything worth testing here avoids
importing it.
"""

from __future__ import annotations

# AlarmMode values (src/alarm/panel-repository.ts) mapped to the string
# values of homeassistant.components.alarm_control_panel.AlarmControlPanelState.
# 'arming' is the exit delay before an arm takes effect; 'alarm_pending' is
# the entry delay before a breach becomes a full 'alarm_triggered'.
_MODE_TO_STATE: dict[str, str] = {
    "disarmed": "disarmed",
    "arming": "arming",
    "armed_away": "armed_away",
    "armed_home": "armed_home",
    "alarm_pending": "pending",
    "alarm_triggered": "triggered",
}


def map_panel_mode(mode: str) -> str:
    """Map an AlarmPanel.mode value to a Home Assistant alarm state string."""
    try:
        return _MODE_TO_STATE[mode]
    except KeyError as err:
        raise ValueError(f"Unknown AlarmPanel mode: {mode!r}") from err


def panel_attributes(panel: dict, zones: list[dict]) -> dict:
    """Extra state attributes for the alarm_control_panel entity.

    `disarmed_zones` lists the zones a zone-restricted guest has disarmed
    while the panel stays armed (FR-010a); `triggered_by` names the zone and
    sensor behind the current alarm, when the service reported one.
    """
    names = {zone["id"]: zone["name"] for zone in zones}
    triggered_by = panel.get("triggeredBy") or {}
    return {
        "armed_mode": panel.get("armedMode"),
        "pending_delay_ends_at": panel.get("pendingDelayEndsAt"),
        "disarmed_zones": [names.get(zone_id, zone_id) for zone_id in panel.get("disarmedZoneIds") or []],
        "triggered_by_zone": names.get(triggered_by.get("zoneId"), triggered_by.get("zoneId")),
        "triggered_by_sensor_id": triggered_by.get("sensorId"),
        "exit_ends_at": panel.get("exitEndsAt"),
        "entry_ends_at": panel.get("entryEndsAt"),
        "bypassed_device_ids": list(panel.get("bypassedDeviceIds") or []),
    }


FAULT_REASONS = {
    "open": "open",
    "offline": "offline",
    "tampered": "tampered",
    "not_set_up": "not set up",
    "updating": "updating",
}


def describe_faulted(faulted: list[dict]) -> str:
    """`Front door (open), Garage (offline)`: the sensors an arm was refused for, as one readable line."""
    return ", ".join(
        f"{f.get('name') or f.get('sensorId')} ({FAULT_REASONS.get(f.get('reason'), f.get('reason') or 'faulted')})"
        for f in faulted
    )
