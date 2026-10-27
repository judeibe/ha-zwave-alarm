"""Tests for rate_limit.py's pure helpers."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "custom_components" / "zwave_alarm"))

from rate_limit import mask_secrets, too_many_requests_message  # noqa: E402


@pytest.mark.parametrize(
    ("retry_after", "expected"),
    [(42, "Try again in 42 seconds."), (1, "Try again in 1 second."), (59.2, "Try again in 60 seconds."), (None, "Wait a minute"), (0, "Wait a minute")],
)
def test_the_wait_is_stated_when_the_service_said_it(retry_after, expected) -> None:
    assert expected in too_many_requests_message(retry_after)


def test_mask_secrets_hides_every_occurrence_and_ignores_missing_or_short_values() -> None:
    assert mask_secrets("4821 and 4821 again, not 99", ("4821", None, "99")) == "**** and **** again, not 99"
    assert mask_secrets("nothing here", ("4821",)) == "nothing here"
    assert mask_secrets("x", ()) == "x"
