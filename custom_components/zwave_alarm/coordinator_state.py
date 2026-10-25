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

from dataclasses import dataclass, field, replace
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
    # KeypadSummary dicts (keypad contract v1.1); the snapshot's `keypads` is optional, so older services leave this empty.
    keypads: list[dict[str, Any]] = field(default_factory=list)
    # Enrolled locks only (LockSummary dicts, Schlage lock contract): paired-only locks are never sent here, only listed
    # by the admin-only `GET /locks/available`. The snapshot's `locks` is optional, so older services leave this empty.
    locks: list[dict[str, Any]] = field(default_factory=list)
    # KeypadSettings dict (`requireCodeToArm`); the snapshot's `keypadSettings` is optional, so older services leave this unset.
    keypad_settings: dict[str, Any] | None = None
    # Per armed mode entry/exit delay, `{"armed_home": {"entryDelaySec": 60, "exitDelaySec": 60}, "armed_away": {...}}`
    # (server 3.0.0+); the snapshot's `modes` is absent on older services, which leaves this unset.
    modes: dict[str, dict[str, int]] | None = None
    # AlarmEvent dicts that are still open (`endedAt` null), oldest first. The snapshot's `alarmEvents` is absent on a
    # service older than 3.2.0, which leaves this empty.
    alarm_events: list[dict[str, Any]] = field(default_factory=list)
    # Enrolled Siren dicts (`nodeId`, `kind`, `name`, `durationSec`, `createdAt`); the snapshot's `sirens` is absent on a
    # service older than 3.3.0, which leaves this empty.
    sirens: list[dict[str, Any]] = field(default_factory=list)


def _find_sensor(zones: list[dict[str, Any]], sensor_id: str) -> dict[str, Any] | None:
    for zone in zones:
        for sensor in zone["sensors"]:
            if sensor["id"] == sensor_id:
                return sensor
    return None


def _with_sensor_update(state: StreamState, sensor_id: str, changes: dict[str, Any]) -> StreamState:
    """Return `state` with `changes` applied to one sensor, copying only the affected zone/sensor dicts.

    The input state is never mutated, so the result is a new object for the
    coordinator to publish. An unknown `sensor_id` returns `state` unchanged.
    """
    for zone_index, zone in enumerate(state.zones):
        for sensor_index, sensor in enumerate(zone["sensors"]):
            if sensor["id"] != sensor_id:
                continue
            sensors = [*zone["sensors"]]
            sensors[sensor_index] = {**sensor, **changes}
            zones = [*state.zones]
            zones[zone_index] = {**zone, "sensors": sensors}
            return replace(state, zones=zones)
    return state


def apply_event(state: StreamState, event: dict[str, Any]) -> StreamState:
    """Apply one server->client event (contracts/websocket-events.md) to `state`, returning the new state."""
    event_type = event.get("type")

    if event_type == "snapshot":
        return StreamState(
            panel=event["panel"],
            zones=event["zones"],
            keypads=event.get("keypads") or [],
            locks=event.get("locks") or [],
            keypad_settings=event.get("keypadSettings"),
            modes=event.get("modes"),
            alarm_events=[e for e in event.get("alarmEvents") or [] if e.get("endedAt") is None],
            sirens=event.get("sirens") or [],
        )

    if event_type == "siren.changed":
        siren = event["siren"]
        sirens = [x for x in state.sirens if x["nodeId"] != siren["nodeId"]]
        return replace(state, sirens=sorted([*sirens, siren], key=lambda x: x["nodeId"]))

    if event_type == "siren.removed":
        return replace(state, sirens=[x for x in state.sirens if x["nodeId"] != event["nodeId"]])

    if event_type == "alarm.event":
        # Sent on creation and on every change; an event that ended is no longer open.
        changed = event["event"]
        others = [e for e in state.alarm_events if e["id"] != changed["id"]]
        if changed.get("endedAt") is not None:
            return replace(state, alarm_events=others)
        return replace(state, alarm_events=sorted([*others, changed], key=lambda e: e["startedAt"]))

    if event_type == "keypad.settings":
        return replace(state, keypad_settings=event["settings"])

    if event_type == "lock.changed":
        lock = event["lock"]
        locks = [lk for lk in state.locks if lk["nodeId"] != lock["nodeId"]]
        return replace(state, locks=sorted([*locks, lock], key=lambda lk: lk["nodeId"]))

    if event_type == "lock.removed":
        # Sent when a lock is unenrolled and when its node leaves the Z-Wave network.
        return replace(state, locks=[lk for lk in state.locks if lk["nodeId"] != event["nodeId"]])

    if event_type == "keypad.changed":
        keypad = event["keypad"]
        keypads = [k for k in state.keypads if k["nodeId"] != keypad["nodeId"]]
        return replace(state, keypads=sorted([*keypads, keypad], key=lambda k: k["nodeId"]))

    if event_type == "panel.changed":
        if state.panel is None:
            return state
        panel = {
            **state.panel,
            "mode": event["mode"],
            "pendingDelayEndsAt": event["pendingDelayEndsAt"],
            "disarmedZoneIds": event.get("disarmedZoneIds", []),
            "triggeredBy": event.get("triggeredBy"),
            "exitEndsAt": event.get("exitEndsAt"),
            "entryEndsAt": event.get("entryEndsAt"),
            "bypassedDeviceIds": event.get("bypassedDeviceIds", []),
        }
        # `armedMode` is only on the REST panel, not the push channel; a mode
        # change that leaves the armed family makes any earlier value stale.
        if event["mode"] == "disarmed":
            panel["armedMode"] = None
        return replace(state, panel=panel, modes=event.get("modes", state.modes))

    if event_type == "sensor.changed":
        return _with_sensor_update(
            state, event["sensorId"], {"currentState": event["currentState"], "category": event["category"]}
        )

    if event_type == "sensor.fault":
        return _with_sensor_update(
            state,
            event["sensorId"],
            {
                "connectivityStatus": event["connectivityStatus"],
                "batteryLevel": event["batteryLevel"],
                # Absent on a service older than 3.3.0: keep what the snapshot said.
                **({"tampered": event["tampered"]} if "tampered" in event else {}),
            },
        )

    # `event.recorded` and `keypad.event` carry no panel/zone/sensor/keypad state (the coordinator
    # forwards them to the event entities instead), and any future event type this
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
            "exitEndsAt": panel.get("exitEndsAt"),
            "entryEndsAt": panel.get("entryEndsAt"),
            "bypassedDeviceIds": panel.get("bypassedDeviceIds", []),
        },
    )
