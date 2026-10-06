"""Pure helpers for keypad entities (keypad contract v1.1).

Kept free of `homeassistant` imports for the same reason as the other
`*_state.py` modules, so they can be unit tested without Home Assistant.
"""

from __future__ import annotations

from typing import Any

# keypad.event `input.kind` values this integration surfaces; any other kind is ignored (the contract says clients must).
KEYPAD_EVENT_TYPES = ["code_entered", "arm_away", "arm_home", "disarm", "cancel", "emergency"]


def keypad_event_payload(event: dict[str, Any]) -> tuple[int, str, dict[str, Any]] | None:
    """Split a `keypad.event` into `(node_id, event_type, attributes)`, or `None` for an unknown or malformed kind.

    The server never sends the entered code, and nothing here would forward it anyway.
    """
    keypad_input = event.get("input")
    kind = keypad_input.get("kind") if isinstance(keypad_input, dict) else None
    if kind not in KEYPAD_EVENT_TYPES or "nodeId" not in event:
        return None
    attributes: dict[str, Any] = {"adapter_id": event.get("adapterId")}
    if kind == "emergency":
        attributes["emergency"] = keypad_input.get("emergency")
    return event["nodeId"], kind, attributes


def keypad_is_online(keypad: dict[str, Any]) -> bool:
    return keypad.get("connectivityStatus") == "online"


def keypad_battery_level(keypad: dict[str, Any]) -> int | None:
    """Battery percentage, or `None` when the keypad doesn't report one."""
    level = keypad.get("batteryLevel")
    return level if isinstance(level, int) else None
