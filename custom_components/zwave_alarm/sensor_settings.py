"""Per-sensor settings (chime, sensor kind, entryway) shared by the subentry flow and the entities.

Pure helpers over a `Sensor` dict, split out like zone_state.py so they unit test without Home Assistant.
The service owns the allowlist of Ring-supported devices and persists these fields; this module only maps
the service's camelCase wire fields to the snake_case names the user sees.
"""

from __future__ import annotations

from typing import Any

SUBENTRY_SENSOR = "sensor"
SUBENTRY_LOCK = "lock"

SENSOR_KINDS = ["door", "window", "interior"]
CHIME_SOUNDS = ["double_beep", "guitar", "wind_chimes", "bing_bong", "doorbell"]  # the service's chirp tones, less "none"

# snake_case setting -> wire field on `PATCH /sensors/{id}`
SENSOR_WIRE_FIELDS = {
    "chime_enabled": "chimeEnabled",
    "chime_sound": "chimeSound",
    "sensor_kind": "sensorKind",
    "entryway": "entryway",
    "is_interior": "isInterior",
    "quick_exit_enabled": "quickExitEnabled",
}
CHIME_FIELDS = ("chime_enabled", "chime_sound")  # the service rejects these on life-safety sensors (400)
DEFAULT_SETTINGS: dict[str, Any] = {
    "chime_enabled": False,
    "chime_sound": "double_beep",
    "sensor_kind": "door",
    "entryway": "",
    "is_interior": False,
    "quick_exit_enabled": False,
}


def settings_from_sensor(sensor: dict[str, Any]) -> dict[str, Any]:
    """The sensor's current settings, falling back to the legacy `chirpTone`/`placement` fields on an older service."""
    settings = {key: sensor[wire] for key, wire in SENSOR_WIRE_FIELDS.items() if sensor.get(wire) is not None}
    if "quick_exit_enabled" not in settings and sensor.get("quickEntrySupported") is not None:  # a service older than quick exit
        settings["quick_exit_enabled"] = sensor["quickEntrySupported"]
    tone = sensor.get("chirpTone")
    if "chime_sound" not in settings and tone not in (None, "none"):
        settings["chime_sound"] = tone
    if "chime_enabled" not in settings and tone is not None:
        settings["chime_enabled"] = tone != "none"
    return {**DEFAULT_SETTINGS, **settings}


def to_wire(settings: dict[str, Any]) -> dict[str, Any]:
    """Settings as `PATCH /sensors/{id}` fields. An interior sensor is always `is_interior`, and `entryway` is trimmed."""
    out = {SENSOR_WIRE_FIELDS[k]: v for k, v in settings.items() if k in SENSOR_WIRE_FIELDS}
    if settings.get("sensor_kind") == "interior":
        out["isInterior"] = True
    if isinstance(out.get("entryway"), str):
        out["entryway"] = out["entryway"].strip()[:60] or None  # the service wants 1..60 chars; null clears
    return out


def has_chime(sensor: dict[str, Any]) -> bool:
    """Intrusion sensors only: a life-safety sensor has no chime."""
    return sensor.get("category") != "life-safety"


def sensor_device_class(kind: str | None) -> str:
    """Binary-sensor device class for a sensor kind."""
    return {"door": "door", "window": "window", "interior": "motion"}.get(kind or "", "door")
