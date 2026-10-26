"""Pure helpers for the lock mode settings, lock sync results and lock events, free of Home Assistant for unit tests."""

from __future__ import annotations

from typing import Any

MODES = ("disarmed", "armed_home", "armed_away")
# What a lock does when the alarm enters a mode: nothing (`None` on the wire), lock the bolt, or unlock it.
ACTION_OPTIONS = ["none", "lock", "unlock"]
MODE_SWITCHES = (
    ("armOnLockWithCode", "arm_on_lock_with_code", "mdi:lock-check"),
    ("armOnOneTouch", "arm_on_one_touch", "mdi:gesture-tap-button"),
    ("disarmOnUnlock", "disarm_on_unlock", "mdi:lock-open-check"),
)
LOCK_EVENT_KINDS = ["locked", "unlocked", "armed", "disarmed", "jammed"]


def mode_settings(lock: dict[str, Any] | None) -> dict[str, Any] | None:
    """The lock's `modeSettings`, or `None` for a lock (or a service older than 3.7.0) that does not report them."""
    value = lock.get("modeSettings") if lock else None
    return value if isinstance(value, dict) else None


def action_option(settings: dict[str, Any] | None, mode: str) -> str | None:
    if settings is None:
        return None
    action = (settings.get("actions") or {}).get(mode)
    return action if action in ("lock", "unlock") else "none"


def action_value(option: str) -> str | None:
    return None if option == "none" else option


def sync_summary(sync: list[dict[str, Any]], names: dict[int, str] | None = None) -> list[dict[str, Any]]:
    """Each lock's result in snake case, with the lock's name when known. A failed one carries the service's message.

    The service's message never contains a code, and nothing here adds one.
    """
    names = names or {}
    return [
        {
            "node_id": s["nodeId"],
            "lock": names.get(s["nodeId"], f"Lock {s['nodeId']}"),
            "slot": s.get("slot"),
            "status": s["status"],
            **({"message": s["message"]} if s.get("message") else {}),
        }
        for s in sync
    ]


def failed_locks(sync: list[dict[str, Any]]) -> list[str]:
    return [s["lock"] for s in sync if s["status"] == "failed"]


def lock_event_payload(event: dict[str, Any]) -> tuple[int, str, dict[str, Any]] | None:
    """Split a `lock.event` into `(node_id, kind, attributes)`, or `None` for an unknown kind (clients must ignore those)."""
    kind = event.get("kind")
    if kind not in LOCK_EVENT_KINDS or "nodeId" not in event:
        return None
    return event["nodeId"], kind, {"user_id": event.get("userId"), "method": event.get("method")}
