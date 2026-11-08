"""Optional access key for the API.

Set ``GUARDIAN_ACCESS_KEY`` and every run, every tool listing and every reset needs that key (WebSocket first
message field ``access_key``, or the ``X-Access-Key`` header on HTTP). Left unset, nothing changes, which is right
for local use. ``/health`` and the server list stay open so the page can tell a visitor that a key is needed.
This is a single shared secret, not user accounts."""
from __future__ import annotations

import hmac
import os
import time

from fastapi import Header, HTTPException

_FAILS: dict[str, list[float]] = {}
MAX_FAILS, WINDOW_S = 8, 300


def required_key() -> str:
    return os.environ.get("GUARDIAN_ACCESS_KEY", "").strip()


def access_required() -> bool:
    return bool(required_key())


def key_ok(candidate: object) -> bool:
    key = required_key()
    return not key or (isinstance(candidate, str) and hmac.compare_digest(candidate.encode(), key.encode()))


def throttled(client: str) -> bool:
    """True once a client has sent too many wrong keys recently (guessing protection)."""
    now = time.time()
    fails = [t for t in _FAILS.get(client, []) if now - t < WINDOW_S]
    _FAILS[client] = fails
    return len(fails) >= MAX_FAILS


def record_failure(client: str) -> None:
    _FAILS.setdefault(client, []).append(time.time())


def reset() -> None:
    _FAILS.clear()


def require_access(x_access_key: str | None = Header(default=None)) -> None:
    """FastAPI dependency for the HTTP endpoints that do work."""
    if not key_ok(x_access_key):
        raise HTTPException(401, "An access key is required.")
