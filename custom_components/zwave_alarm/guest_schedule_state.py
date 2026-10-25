"""Pure validation for a guest's keypad schedule, free of Home Assistant for unit tests.

The service re-checks everything; this only gives a clear message before a request is sent.
"""

from __future__ import annotations

import re
from typing import Any

GUEST_WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class InvalidSchedule(ValueError):
    """The schedule can't be valid; the message says why."""


def normalize_time(value: str | None) -> str | None:
    """`08:00` or `08:00:00` (a Home Assistant time selector) to `08:00`; None stays None."""
    if value is None:
        return None
    text = str(value)
    if re.fullmatch(r"\d{2}:\d{2}:\d{2}", text):
        text = text[:5]
    if not _HHMM.match(text):
        raise InvalidSchedule("Times must look like 08:00.")
    return text


def check_schedule(days: list[str] | None, all_day: bool, start: str | None, end: str | None) -> None:
    """Raise `InvalidSchedule` for a schedule the service would refuse. Pass the merged values for an update."""
    if days is not None:
        if not days:
            raise InvalidSchedule("Pick at least one day.")
        if len(set(days)) != len(days):
            raise InvalidSchedule("A day can only be listed once.")
        if bad := [d for d in days if d not in GUEST_WEEKDAYS]:
            raise InvalidSchedule(f"Unknown day: {bad[0]}. Use mon, tue, wed, thu, fri, sat or sun.")
    if all_day:
        return
    if start is None or end is None:
        raise InvalidSchedule("A schedule that is not all day needs a start and an end time.")
    if start == end:
        raise InvalidSchedule("The start and end time must differ.")  # an end before the start is an overnight window


def schedule_fields(data: dict[str, Any]) -> dict[str, Any]:
    """The client's keyword arguments from a service or websocket payload; only what was given."""
    fields: dict[str, Any] = {}
    for key in ("name", "days", "all_day", "time_zone"):
        if key in data:
            fields[key] = data[key]
    for key in ("start", "end"):
        if key in data:
            fields[key] = normalize_time(data[key])
    return fields
