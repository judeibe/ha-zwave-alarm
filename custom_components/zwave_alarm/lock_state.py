"""Pure helpers for Schlage lock entities and schedule services (BE469 / BE468).

Kept free of `homeassistant` imports for the same reason as the other `*_state.py`
modules, so they can be unit tested without Home Assistant.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol

PIN_LENGTH_MIN = 4
PIN_LENGTH_MAX = 8

ALARM_MODES = ("off", "alert", "tamper", "forced_entry")

# Sensitivity values the lock accepts: 1 is most sensitive, 5 least. 0 means the sensor isn't supported, so it has no option.
# 2 and 4 are undocumented intermediate values; they are exposed so a value the lock already holds is never hidden.
SENSITIVITY_OPTIONS = {1: "most_sensitive", 2: "high", 3: "medium", 4: "low", 5: "least_sensitive"}
SENSITIVITY_VALUES = {option: value for value, option in SENSITIVITY_OPTIONS.items()}

# Diagnostic counters (key in `diagnostics`), all read-only.
DIAGNOSTIC_COUNTERS = (
    "electronicTransitionCount",
    "mechanicalTransitionCount",
    "electronicFailedCount",
    "electronicHighPreloadTransitionCount",
)

# Schedule types the actions expose, and the service's `ScheduleKind` for each (also the `scheduleSlots` key).
CLIENT_SCHEDULE_KINDS = {"weekday": "weekDay", "yearday": "yearDay", "daily_repeating": "dailyRepeating"}
SCHEDULE_KINDS = tuple(CLIENT_SCHEDULE_KINDS)
# The service numbers weekdays 0 (Sunday) to 6 (Saturday); the actions take names.
WEEKDAYS = ("sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday")

_HOUR = vol.All(vol.Coerce(int), vol.Range(min=0, max=23))
_MINUTE = vol.All(vol.Coerce(int), vol.Range(min=0, max=59))
_YEAR = vol.All(vol.Coerce(int), vol.Range(min=0, max=99))  # two digits: 26 is 2026
_MONTH = vol.All(vol.Coerce(int), vol.Range(min=1, max=12))
_DAY = vol.All(vol.Coerce(int), vol.Range(min=1, max=31))
_WEEKDAY = vol.All(vol.Coerce(int), vol.Range(min=0, max=6))

# Field schemas per schedule type, in the service's encoding (mirrors zwave-js's ScheduleEntryLock*Schedule types).
SCHEDULE_FIELDS: dict[str, dict[str, Any]] = {
    "weekday": {
        "weekday": _WEEKDAY,
        "startHour": _HOUR,
        "startMinute": _MINUTE,
        "stopHour": _HOUR,
        "stopMinute": _MINUTE,
    },
    "yearday": {
        "startYear": _YEAR,
        "startMonth": _MONTH,
        "startDay": _DAY,
        "startHour": _HOUR,
        "startMinute": _MINUTE,
        "stopYear": _YEAR,
        "stopMonth": _MONTH,
        "stopDay": _DAY,
        "stopHour": _HOUR,
        "stopMinute": _MINUTE,
    },
    "daily_repeating": {
        "weekdays": vol.All([_WEEKDAY], vol.Length(min=1), vol.Unique()),
        "startHour": _HOUR,
        "startMinute": _MINUTE,
        "durationHour": _HOUR,
        "durationMinute": _MINUTE,
    },
}


def lock_supports(lock: dict[str, Any], setting: str) -> bool:
    """True when the lock lists `setting` as supported; the BE469-only ones are absent from a BE468's list."""
    supported = lock.get("supportedSettings")
    return isinstance(supported, list) and setting in supported


def lock_settings(lock: dict[str, Any]) -> dict[str, Any]:
    settings = lock.get("settings")
    return settings if isinstance(settings, dict) else {}


def lock_diagnostics(lock: dict[str, Any]) -> dict[str, Any]:
    diagnostics = lock.get("diagnostics")
    return diagnostics if isinstance(diagnostics, dict) else {}


def lock_is_online(lock: dict[str, Any]) -> bool:
    return lock.get("connectivityStatus") == "online"


def lock_battery_level(lock: dict[str, Any]) -> int | None:
    level = lock.get("batteryLevel")
    return level if isinstance(level, int) else None


def sensitivity_option(value: Any) -> str | None:
    """The select option for a sensitivity value; `None` for 0 (not supported) or anything unexpected."""
    return SENSITIVITY_OPTIONS.get(value) if isinstance(value, int) and not isinstance(value, bool) else None


def alarm_mode_option(value: Any) -> str | None:
    return value if value in ALARM_MODES else None


def occupied_slot_count(lock: dict[str, Any]) -> int | None:
    slots = lock_diagnostics(lock).get("occupiedUserSlots")
    return len(slots) if isinstance(slots, list) else None


def occupied_slots(lock: dict[str, Any]) -> list[int]:
    slots = lock_diagnostics(lock).get("occupiedUserSlots")
    return sorted(slot for slot in slots if isinstance(slot, int)) if isinstance(slots, list) else []


def decode_occupied_slots(raw: bytes | list[int]) -> list[int]:
    """Decode the 0x06 user-slot bit field: bytes 1-3 cover slots 1-24 and byte 4 covers 25-30, LSB lowest.

    The server already does this; it is here so the integration can surface a raw value if one is ever pushed.
    """
    data = list(raw)[:4]
    slots = [8 * index + bit + 1 for index, byte in enumerate(data) for bit in range(8) if byte >> bit & 1]
    return [slot for slot in slots if slot <= 30]


def pin_length_valid(code: str, pin_length: int) -> bool:
    """A user code is acceptable only when numeric and exactly as long as the lock's configured PIN length."""
    return PIN_LENGTH_MIN <= pin_length <= PIN_LENGTH_MAX and code.isdigit() and len(code) == pin_length


def validate_schedule(kind: str, fields: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalise one schedule's fields for `kind`; raises `vol.Invalid` on any problem.

    Start must be strictly before the end for weekday and year-day schedules, and a daily repeating
    schedule needs a non-zero duration, matching what the lock itself accepts.
    """
    if kind not in SCHEDULE_FIELDS:
        raise vol.Invalid(f"Unknown schedule type {kind!r}")
    schema = vol.Schema({vol.Required(key): validator for key, validator in SCHEDULE_FIELDS[kind].items()})
    unknown = sorted(set(fields) - set(SCHEDULE_FIELDS[kind]))
    if unknown:
        raise vol.Invalid(f"Fields not valid for a {kind} schedule: {', '.join(unknown)}")
    schedule = schema(fields)
    if kind == "weekday":
        if (schedule["startHour"], schedule["startMinute"]) >= (schedule["stopHour"], schedule["stopMinute"]):
            raise vol.Invalid("The start time must be before the stop time")
    elif kind == "yearday":
        start = tuple(schedule[key] for key in ("startYear", "startMonth", "startDay", "startHour", "startMinute"))
        stop = tuple(schedule[key] for key in ("stopYear", "stopMonth", "stopDay", "stopHour", "stopMinute"))
        if start >= stop:
            raise vol.Invalid("The start must be before the stop")
    elif schedule["durationHour"] == 0 and schedule["durationMinute"] == 0:
        raise vol.Invalid("The duration must be longer than zero")
    return schedule


def schedule_slot_count(lock: dict[str, Any], kind: str) -> int | None:
    """How many slots per user the lock offers for `kind`; `None` when the lock hasn't reported it."""
    slots = lock.get("scheduleSlots")
    count = slots.get(CLIENT_SCHEDULE_KINDS[kind]) if isinstance(slots, dict) else None
    return count if isinstance(count, int) and not isinstance(count, bool) else None


def schedule_from_service(kind: str, data: dict[str, Any]) -> dict[str, Any]:
    """Turn the schedule service's friendly inputs into Schedule Entry Lock fields (then validate them).

    `start_time`/`end_time` are `datetime.time`, `start`/`end` are `datetime.datetime` and `duration` is a
    `datetime.timedelta`, as coerced by the service schema; a missing input raises `vol.Invalid`. Weekday names
    become the service's 0 (Sunday) to 6 numbers and years become two digits (2026 is 26), so only 2000-2099 fit.
    """

    def need(*keys: str) -> list[Any]:
        missing = [key for key in keys if data.get(key) is None]
        if missing:
            raise vol.Invalid(f"A {kind} schedule needs: {', '.join(missing)}")
        return [data[key] for key in keys]

    if kind == "weekday":
        weekday, start, end = need("weekday", "start_time", "end_time")
        fields = {
            "weekday": WEEKDAYS.index(weekday),
            "startHour": start.hour, "startMinute": start.minute,
            "stopHour": end.hour, "stopMinute": end.minute,
        }
    elif kind == "yearday":
        start, end = need("start", "end")
        if not (2000 <= start.year <= 2099 and 2000 <= end.year <= 2099):
            raise vol.Invalid("Years must be between 2000 and 2099")
        fields = {
            "startYear": start.year % 100, "startMonth": start.month, "startDay": start.day,
            "startHour": start.hour, "startMinute": start.minute,
            "stopYear": end.year % 100, "stopMonth": end.month, "stopDay": end.day,
            "stopHour": end.hour, "stopMinute": end.minute,
        }
    elif kind == "daily_repeating":
        weekdays, start, duration = need("weekdays", "start_time", "duration")
        minutes = int(duration.total_seconds() // 60)
        fields = {
            "weekdays": [WEEKDAYS.index(day) for day in weekdays],
            "startHour": start.hour, "startMinute": start.minute,
            "durationHour": minutes // 60, "durationMinute": minutes % 60,
        }
    else:
        raise vol.Invalid(f"Unknown schedule type {kind!r}")
    return validate_schedule(kind, fields)
