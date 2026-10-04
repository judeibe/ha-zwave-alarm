"""Pure state-application and backoff helpers for the WebSocket coordinator (T039).

Split out of coordinator.py for the same reason panel_state.py/zone_state.py/
fault_state.py were split out of their entity modules (see the README's "Testing" note
docstring): the `homeassistant` package can't be installed in this
environment, so anything worth unit testing has to avoid importing it --
coordinator.py itself subclasses `homeassistant.helpers.update_coordinator.
DataUpdateCoordinator` and is therefore only verifiable here via
`py_compile`/wheel-source inspection, same as the entity modules.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

# Exponential backoff for stream reconnects (contracts/ha-custom-component.md's
# "retries with backoff" requirement): 5s, 10s, 20s, 40s, then capped at 60s.
RECONNECT_BASE_DELAY = 5
RECONNECT_MAX_DELAY = 60


def next_backoff(attempt: int, base: float = RECONNECT_BASE_DELAY, max_delay: float = RECONNECT_MAX_DELAY) -> float:
    """Delay in seconds before the `attempt`-th reconnect retry (0-indexed), doubling from `base` up to `max_delay`."""
    return min(base * (2**attempt), max_delay)


@dataclass
class StreamState:
    """The latest panel + zones state as pushed over the WebSocket channel.

    Mirrors the `snapshot` event's shape (contracts/websocket-events.md) --
    `zones` is the same list-of-Zone-with-joined-sensors shape `GET
    /api/v1/zones` already returns, so it can be handed directly to
    panel_state.map_panel_mode / zone_state.zone_is_breached /
    fault_state.count_faulted_sensors, sharing one shape between the
    poll-based (T036-T038 fallback paths) and push-based (T039) code.
    """

    panel: dict[str, Any] | None
    zones: list[dict[str, Any]]


def _find_sensor(zones: list[dict[str, Any]], sensor_id: str) -> dict[str, Any] | None:
    for zone in zones:
        for sensor in zone["sensors"]:
            if sensor["id"] == sensor_id:
                return sensor
    return None


def apply_event(state: StreamState, event: dict[str, Any]) -> StreamState:
    """Apply one server->client event (contracts/websocket-events.md) to `state`, returning the new state."""
    event_type = event.get("type")

    if event_type == "snapshot":
        return StreamState(panel=event["panel"], zones=event["zones"])

    if event_type == "panel.changed":
        if state.panel is None:
            return state
        panel = {
            **state.panel,
            "mode": event["mode"],
            "pendingDelayEndsAt": event["pendingDelayEndsAt"],
            "disarmedZoneIds": event.get("disarmedZoneIds", []),
            "triggeredBy": event.get("triggeredBy"),
        }
        # `armedMode` is only on the REST panel, not the push channel; a mode
        # change that leaves the armed family makes any earlier value stale.
        if event["mode"] == "disarmed":
            panel["armedMode"] = None
        return replace(state, panel=panel)

    if event_type == "sensor.changed":
        sensor = _find_sensor(state.zones, event["sensorId"])
        if sensor is not None:
            sensor["currentState"] = event["currentState"]
            sensor["category"] = event["category"]
        return state

    if event_type == "sensor.fault":
        sensor = _find_sensor(state.zones, event["sensorId"])
        if sensor is not None:
            sensor["connectivityStatus"] = event["connectivityStatus"]
            sensor["batteryLevel"] = event["batteryLevel"]
        return state

    # `event.recorded` carries no panel/zone/sensor state (the coordinator
    # forwards it to the event entity instead), and any future event type this
    # client doesn't yet recognize is ignored rather than raising -- matching
    # src/api/ws.ts's own "ignore unrecognized messages" precedent for this
    # read-only channel.
    return state


def references_unknown_sensor(state: StreamState, event: dict[str, Any]) -> bool:
    """True when a `sensor.changed`/`sensor.fault` names a sensor absent from `state.zones`.

    The push channel has no zone/sensor "created" event, so this is the signal
    that an administrator added a sensor (or zone) after the last snapshot and
    the zone list must be re-fetched.
    """
    if event.get("type") not in ("sensor.changed", "sensor.fault"):
        return False
    return _find_sensor(state.zones, event["sensorId"]) is None


def security_event_payload(event: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Split an `event.recorded` event into `(event_type, attributes)` for the HA event entity.

    `details` carries e.g. "Cleared by <name>" on `alarm_cleared`, which is
    how an automation tells recipients the alarm was cleared and by whom
    (User Story 3).
    """
    recorded = event["event"]
    return recorded["type"], {
        "event_id": recorded.get("id"),
        "occurred_at": recorded.get("occurredAt"),
        "details": recorded.get("details"),
    }


def merge_panel(state: StreamState, panel: dict[str, Any]) -> StreamState:
    """Overwrite `state.panel` with a fresh AlarmPanel dict from an arm/disarm REST response.

    Used by alarm_control_panel.py's optimistic update after a successful
    arm/disarm call, so the UI reflects the change immediately rather than
    waiting for the WebSocket's own `panel.changed` echo of the same change.
    """
    return replace(
        state,
        panel={
            "mode": panel["mode"],
            "pendingDelayEndsAt": panel.get("pendingDelayEndsAt"),
            "armedMode": panel.get("armedMode"),
            "disarmedZoneIds": panel.get("disarmedZoneIds", []),
            "triggeredBy": panel.get("triggeredBy"),
        },
    )
