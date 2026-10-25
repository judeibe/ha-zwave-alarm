"""Pure helpers over the open alarm events (`StreamState.alarm_events`), kept free of Home Assistant for unit tests."""

from __future__ import annotations

from typing import Any

# AlarmEvent.type, lower-cased for the enum sensor's state; "none" while no event is open.
EVENT_TYPES = ["burglary", "smoke", "co", "panic", "fire_medical", "duress", "sos", "flood_freeze"]
NO_EVENT = "none"


def current_event(events: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The newest open event, which is the one a person needs to deal with first."""
    return events[-1] if events else None


def event_state(events: list[dict[str, Any]]) -> str:
    event = current_event(events)
    return event["type"].lower() if event else NO_EVENT


def siren_sounding(events: list[dict[str, Any]]) -> bool:
    """True while any open event has its siren sounding (a silenced siren is not sounding)."""
    return any(e.get("sirenState") == "sounding" for e in events)


def event_attributes(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Attributes of the current event, plus how many are open; only the count when none is."""
    event = current_event(events)
    attrs: dict[str, Any] = {"open_events": len(events)}
    if event is None:
        return attrs
    return attrs | {
        "event_id": event["id"],
        "service": event.get("service"),
        "trigger_device_id": event.get("triggerDeviceId"),
        "siren_state": event.get("sirenState"),
        "dispatch_state": event.get("dispatchState"),
        "started_at": event.get("startedAt"),
        "cancelled_at": event.get("cancelledAt"),
        "details": event.get("details"),
    }
