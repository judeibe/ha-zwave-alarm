"""The security event entity must know every kind the service can record, or HA drops those events silently."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "custom_components" / "zwave_alarm"))

from coordinator_state import security_event_payload  # noqa: E402,F401

EVENT_SOURCE = (ROOT / "custom_components" / "zwave_alarm" / "event.py").read_text()
HISTORY_PAGE = (ROOT / "panel" / "src" / "pages" / "HistoryPage.tsx").read_text()


def _entity_types() -> set[str]:
    block = re.search(r"SECURITY_EVENT_TYPES = \[(.*?)\]", EVENT_SOURCE, re.S)
    assert block, "SECURITY_EVENT_TYPES not found in event.py"
    return set(re.findall(r'"([a-z_]+)"', block.group(1)))


def _history_page_types() -> set[str]:
    kinds = re.search(r"const KINDS: \[string, string\]\[\] = \[(.*?)\n\];", HISTORY_PAGE, re.S)
    assert kinds, "KINDS not found in HistoryPage.tsx"
    return {t for group in re.findall(r'\["([a-z_,]+)",', kinds.group(1)) for t in group.split(",")}


def test_every_kind_the_history_page_can_show_is_known_to_the_event_entity() -> None:
    missing = _history_page_types() - _entity_types()
    assert not missing, f"the History page filters by kinds the event entity would drop: {sorted(missing)}"


def test_the_lock_kinds_are_known() -> None:
    assert {"lock_locked", "lock_unlocked", "lock_jammed", "lock_offline", "lock_online"} <= _entity_types()


def test_the_parsing_finds_something() -> None:
    assert len(_entity_types()) > 25 and len(_history_page_types()) > 15
