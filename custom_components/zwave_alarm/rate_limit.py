"""Pure helpers for what a person sees when the service refuses or rate-limits a request, free of Home Assistant."""

from __future__ import annotations

from typing import Any

MASK = "****"


def too_many_requests_message(retry_after: float | None) -> str:
    """The 429 (10 failed disarms per IP per minute, or logins) in words, with the wait when the service said how long."""
    if retry_after is not None and retry_after >= 1:
        seconds = int(retry_after) if retry_after == int(retry_after) else int(retry_after) + 1
        return f"Too many attempts. Try again in {seconds} second{'' if seconds == 1 else 's'}."
    return "Too many attempts. Wait a minute and try again."


def mask_secrets(text: str, secrets: tuple[Any, ...]) -> str:
    """`text` with every secret (a code the caller sent) replaced, so a service message that echoed one can't leak it."""
    for secret in secrets:
        if isinstance(secret, str) and len(secret) >= 4:
            text = text.replace(secret, MASK)
    return text
