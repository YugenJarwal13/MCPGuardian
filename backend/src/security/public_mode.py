"""Protections that matter once the app is reachable by strangers (``GUARDIAN_PUBLIC=1``).

* custom server URLs must resolve only to public internet addresses (no loopback, private, link-local,
  reserved ranges): the "check any server" page otherwise lets anyone make this server connect to its own
  network (SSRF);
* per-visitor limits on runs per hour and on simultaneous runs;
* a daily budget of runs that may use the AI inspectors; once spent, runs continue on the regex rules and
  say so, instead of failing or silently burning the API key.

All limits are in-memory and per process. Locally (``GUARDIAN_PUBLIC`` unset) nothing here applies.
"""
from __future__ import annotations

import ipaddress
import os
import socket
import threading
import time
from collections import defaultdict, deque
from urllib.parse import urlparse

INTERNAL_MSG = ("Local and internal addresses can't be checked from the public site. "
                "Run MCP Guardian locally for those.")


def public_mode() -> bool:
    return os.environ.get("GUARDIAN_PUBLIC", "").strip().lower() in ("1", "true", "yes")


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def check_public_target(url: str) -> str | None:
    """Return an error message if ``url`` may not be contacted from a public deployment, else None."""
    host = (urlparse(url).hostname or "").lower()
    if host == "localhost" or host.endswith((".local", ".internal", ".localhost")):
        return INTERNAL_MSG
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return "That host name could not be resolved."
    for info in infos:
        if not ipaddress.ip_address(info[4][0]).is_global:
            return INTERNAL_MSG
    return None


# DVMCP challenges whose tools do nothing dangerous when executed. Challenges 3-10 read files, touch
# environment/state, or run commands by design; on a public host (which holds an API key in its
# environment) they may only be INSPECTED, never called.
EXECUTABLE_DVMCP = frozenset({"dvmcp-ch1", "dvmcp-ch2"})
INSPECT_ONLY_NOTE = ("This DVMCP challenge is deliberately dangerous when executed (file access or command "
                     "execution), so the public demo only inspects it and never calls its tools. "
                     "Run MCP Guardian locally to see the full call.")


def restrict_execution(req: dict) -> str | None:
    """In public mode, turn a call on a dangerous lab server into an inspection. Returns a note or None."""
    sid = str(req.get("server_id") or "")
    if sid.startswith("dvmcp-") and sid not in EXECUTABLE_DVMCP and not req.get("inspect_only"):
        req["inspect_only"] = True
        return INSPECT_ONLY_NOTE
    return None


class RunLimiter:
    def __init__(self, per_hour: int, concurrent: int, llm_runs_per_day: int):
        self.per_hour, self.concurrent, self.llm_per_day = per_hour, concurrent, llm_runs_per_day
        self._hits: dict[str, deque] = defaultdict(deque)
        self._active: dict[str, int] = defaultdict(int)
        self._llm_day = ""
        self._llm_used = 0
        self._lock = threading.Lock()

    def acquire(self, client: str) -> str | None:
        """Reserve a run slot. Returns an error message when the visitor is over a limit."""
        now = time.time()
        with self._lock:
            hits = self._hits[client]
            while hits and now - hits[0] > 3600:
                hits.popleft()
            if len(hits) >= self.per_hour:
                return f"Rate limit: at most {self.per_hour} runs per hour per visitor. Please try again later."
            if self._active[client] >= self.concurrent:
                return "A run is already in progress for you. Wait for it to finish."
            hits.append(now)
            self._active[client] += 1
        return None

    def release(self, client: str) -> None:
        with self._lock:
            self._active[client] = max(0, self._active[client] - 1)

    def take_llm_run(self) -> bool:
        """True while today's AI-inspector budget lasts (resets at 00:00 UTC, like the provider's quota)."""
        today = time.strftime("%Y-%m-%d", time.gmtime())
        with self._lock:
            if self._llm_day != today:
                self._llm_day, self._llm_used = today, 0
            if self._llm_used >= self.llm_per_day:
                return False
            self._llm_used += 1
            return True

    def llm_runs_left(self) -> int:
        today = time.strftime("%Y-%m-%d", time.gmtime())
        with self._lock:
            return self.llm_per_day if self._llm_day != today else max(0, self.llm_per_day - self._llm_used)


_LIMITER: RunLimiter | None = None


def limiter() -> RunLimiter:
    global _LIMITER
    if _LIMITER is None:
        _LIMITER = RunLimiter(_int("GUARDIAN_RUNS_PER_HOUR", 12), _int("GUARDIAN_CONCURRENT_RUNS", 2),
                              _int("GUARDIAN_LLM_RUNS_PER_DAY", 10))
    return _LIMITER


def reset_limiter() -> None:
    global _LIMITER
    _LIMITER = None
