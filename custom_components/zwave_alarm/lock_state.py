"""Pure helpers for Schlage lock entities and schedule services (BE469 / BE468).

Kept free of `homeassistant` imports for the same reason as the other `*_state.py`
modules, so they can be unit tested without Home Assistant.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol

CAPABILITY_ALARM_CONFIG = "alarm_config"  # BE469 only: alarm mode, sensitivities and local-controls parameters

# Boolean parameters shared by the BE468 and BE469 (config key -> switch translation key).
BOOLEAN_CONFIG_KEYS = ("beeper", "vacationMode", "lockAndLeave", "autoLock")

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

SCHEDULE_KINDS = ("weekday", "yearday", "daily_repeating")
WEEKDAYS = ("sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday")

_HOUR = vol.All(vol.Coerce(int), vol.Range(min=0, max=23))
_MINUTE = vol.All(vol.Coerce(int), vol.Range(min=0, max=59))
_YEAR = vol.All(vol.Coerce(int), vol.Range(min=2000, max=2099))
_MONTH = vol.All(vol.Coerce(int), vol.Range(min=1, max=12))
_DAY = vol.All(vol.Coerce(int), vol.Range(min=1, max=31))
_WEEKDAY = vol.In(WEEKDAYS)

# Field schemas per schedule kind, mirroring zwave-js's ScheduleEntryLock*Schedule types.
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


def lock_has_alarm_config(lock: dict[str, Any]) -> bool:
    """True for locks with the BE469-only alarm parameters (0x07-0x0B); the BE468 lacks them."""
    return CAPABILITY_ALARM_CONFIG in lock.get("capabilities", [])


def normalise_lock(lock: dict[str, Any]) -> dict[str, Any]:
    """Return `lock` in the one shape the entities read, whichever spelling the service and client use.

    The service reports `settings`, `supportedSettings`, `localControls` and `diagnostics.occupiedUserSlots`; the
    client's typed models say `config`, `capabilities` (`alarm`) and `diagnostics.occupiedSlots`, and
    `scheduleSlots` is keyed `weekDay` or `weekday`. Reading both here keeps every entity on a single shape, and the
    original keys are left alone. The BE469-only parameters are detected from `supportedSettings` when the lock
    lists them, else from the capabilities, else from the model.
    """
    raw_settings = lock.get("settings") if isinstance(lock.get("settings"), dict) else lock.get("config")
    config = dict(raw_settings) if isinstance(raw_settings, dict) else {}
    if "localControlsEnabled" in config:
        config.setdefault("localControls", config.pop("localControlsEnabled"))

    diagnostics = dict(lock_diagnostics(lock))
    if "occupiedUserSlots" in diagnostics:
        diagnostics.setdefault("occupiedSlots", diagnostics["occupiedUserSlots"])

    slots = dict(lock["scheduleSlots"]) if isinstance(lock.get("scheduleSlots"), dict) else {}
    if "weekday" in slots:
        slots.setdefault("weekDay", slots["weekday"])

    capabilities = [c for c in lock.get("capabilities", []) if c not in ("alarm", CAPABILITY_ALARM_CONFIG)]
    supported = lock.get("supportedSettings")
    if isinstance(supported, list):
        alarm = "alarmMode" in supported
    else:
        alarm = bool({"alarm", CAPABILITY_ALARM_CONFIG} & set(lock.get("capabilities", []))) or lock.get("model") == "BE469"
    if alarm:
        capabilities.append(CAPABILITY_ALARM_CONFIG)

    return {**lock, "config": config, "diagnostics": diagnostics, "scheduleSlots": slots, "capabilities": capabilities}


def lock_config(lock: dict[str, Any]) -> dict[str, Any]:
    config = lock.get("config")
    return config if isinstance(config, dict) else {}


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
    slots = lock_diagnostics(lock).get("occupiedSlots")
    return len(slots) if isinstance(slots, list) else None


def occupied_slots(lock: dict[str, Any]) -> list[int]:
    slots = lock_diagnostics(lock).get("occupiedSlots")
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


# `scheduleSlots` key per schedule kind (the Schedule Entry Lock `getNumSlots` result).
SLOT_COUNT_KEYS = {"weekday": "weekDay", "yearday": "yearDay", "daily_repeating": "dailyRepeating"}
# The client's `ScheduleKind` for each kind the services expose.
CLIENT_SCHEDULE_KINDS = {"weekday": "weekday", "yearday": "yearDay", "daily_repeating": "dailyRepeating"}


def schedule_slot_count(lock: dict[str, Any], kind: str) -> int | None:
    """How many slots per user the lock offers for `kind`; `None` when the lock hasn't reported it."""
    slots = lock.get("scheduleSlots")
    count = slots.get(SLOT_COUNT_KEYS[kind]) if isinstance(slots, dict) else None
    return count if isinstance(count, int) and not isinstance(count, bool) else None


def schedule_from_service(kind: str, data: dict[str, Any]) -> dict[str, Any]:
    """Turn the schedule service's friendly inputs into Schedule Entry Lock fields (then validate them).

    `start_time`/`end_time` are `datetime.time`, `start`/`end` are `datetime.datetime` and `duration` is a
    `datetime.timedelta`, as coerced by the service schema; a missing input raises `vol.Invalid`.
    """

    def need(*keys: str) -> list[Any]:
        missing = [key for key in keys if data.get(key) is None]
        if missing:
            raise vol.Invalid(f"A {kind} schedule needs: {', '.join(missing)}")
        return [data[key] for key in keys]

    if kind == "weekday":
        weekday, start, end = need("weekday", "start_time", "end_time")
        fields = {
            "weekday": weekday,
            "startHour": start.hour, "startMinute": start.minute,
            "stopHour": end.hour, "stopMinute": end.minute,
        }
    elif kind == "yearday":
        start, end = need("start", "end")
        fields = {
            "startYear": start.year, "startMonth": start.month, "startDay": start.day,
            "startHour": start.hour, "startMinute": start.minute,
            "stopYear": end.year, "stopMonth": end.month, "stopDay": end.day,
            "stopHour": end.hour, "stopMinute": end.minute,
        }
    elif kind == "daily_repeating":
        weekdays, start, duration = need("weekdays", "start_time", "duration")
        minutes = int(duration.total_seconds() // 60)
        fields = {
            "weekdays": list(weekdays),
            "startHour": start.hour, "startMinute": start.minute,
            "durationHour": minutes // 60, "durationMinute": minutes % 60,
        }
    else:
        raise vol.Invalid(f"Unknown schedule type {kind!r}")
    return validate_schedule(kind, fields)
