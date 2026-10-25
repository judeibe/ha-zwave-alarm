"""Pure helpers for the enrolled sirens (`StreamState.sirens`), free of Home Assistant for unit tests."""

from __future__ import annotations

from typing import Any

# Only an OUTDOOR siren's duration is configurable; BASE and DOME are fixed at 600 s (spec, Timers).
OUTDOOR_MIN_SEC = 60
OUTDOOR_MAX_SEC = 600


def siren_label(siren: dict[str, Any]) -> str:
    return siren.get("name") or f"Siren {siren['nodeId']}"


def siren_is_configurable(siren: dict[str, Any]) -> bool:
    return siren.get("kind") == "OUTDOOR"
