"""On-demand DVMCP lab: start one challenge server when it is picked, stop it when it has been idle.

The ten lab servers are deliberately vulnerable. Running them all costs ~200 MB, which a small hosted instance
does not have, and a demo only ever uses one at a time. With ``GUARDIAN_LAB=lazy`` this manager starts the one
challenge that a run or a tool listing asks for (bound to 127.0.0.1, as always) and keeps at most
``GUARDIAN_LAB_MAX`` of them alive; the least recently used one is stopped to make room, and any server idle for
``GUARDIAN_LAB_IDLE_S`` seconds is stopped by a background reaper.

Other values of ``GUARDIAN_LAB``: ``on`` (all ten started by the container entrypoint) and ``off`` / unset
(nothing is managed here; locally, ``start-lab.cmd`` starts the lab by hand).
"""
from __future__ import annotations

import asyncio
import contextlib
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent          # backend/
LAUNCHER = ROOT / "scripts" / "run_dvmcp_native.py"
LAB_DIR = ROOT / "external" / "damn-vulnerable-MCP-server"
HOST = "127.0.0.1"


class LabError(RuntimeError):
    """A lab server could not be started (message is shown in the UI)."""


def mode() -> str:
    v = os.environ.get("GUARDIAN_LAB", "").strip().lower()
    return v if v in ("on", "lazy", "off") else "off"


def lazy() -> bool:
    return mode() == "lazy"


def installed() -> bool:
    return (LAB_DIR / "challenges").is_dir() and LAUNCHER.is_file()


def _int_env(name: str, default: int, low: int) -> int:
    try:
        return max(low, int(os.environ.get(name, default)))
    except ValueError:
        return default


def max_running() -> int:
    return _int_env("GUARDIAN_LAB_MAX", 3, 1)


def idle_seconds() -> int:
    return _int_env("GUARDIAN_LAB_IDLE_S", 600, 30)


def start_timeout() -> int:
    return _int_env("GUARDIAN_LAB_START_S", 45, 5)


def port_up(port: int) -> bool:
    try:
        with socket.create_connection((HOST, port), timeout=0.3):
            return True
    except OSError:
        return False


class LabManager:
    def __init__(self) -> None:
        self._procs: dict[int, subprocess.Popen] = {}
        self._last: dict[int, float] = {}
        self._lock = asyncio.Lock()
        self._reaper: asyncio.Task | None = None

    # -- starting ------------------------------------------------------------------------------------------------
    async def ensure(self, number: int) -> None:
        """Make sure challenge ``number`` is listening on 900N, starting it if needed. Raises LabError."""
        port = 9000 + number
        async with self._lock:
            self._last[number] = time.monotonic()
            proc = self._procs.get(number)
            if proc is not None and proc.poll() is not None:
                self._procs.pop(number, None)                    # it exited on its own
            if port_up(port):
                return
            if not installed():
                raise LabError("The DVMCP lab is not installed on this server.")
            self._make_room(keep=number)
            self._procs[number] = self._spawn(number)
            deadline = time.monotonic() + start_timeout()
            while time.monotonic() < deadline:
                if self._procs[number].poll() is not None:
                    self._procs.pop(number, None)
                    raise LabError(f"Challenge {number} server exited while starting.")
                if port_up(port):
                    return
                await asyncio.sleep(0.25)
            self._stop(number)
            raise LabError(f"Challenge {number} server did not start within {start_timeout()} s.")

    def touch(self, number: int) -> None:
        if number in self._procs:
            self._last[number] = time.monotonic()

    def _spawn(self, number: int) -> subprocess.Popen:
        return subprocess.Popen([sys.executable, str(LAUNCHER), "--one", str(number)], cwd=str(LAB_DIR),
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def _make_room(self, keep: int) -> None:
        running = [n for n, p in self._procs.items() if p.poll() is None and n != keep]
        while len(running) >= max_running():
            oldest = min(running, key=lambda n: self._last.get(n, 0.0))
            self._stop(oldest)
            running.remove(oldest)

    # -- stopping ------------------------------------------------------------------------------------------------
    def _stop(self, number: int) -> None:
        proc = self._procs.pop(number, None)
        self._last.pop(number, None)
        if proc is None or proc.poll() is not None:
            return
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()

    def reap_idle(self) -> list[int]:
        now, limit = time.monotonic(), idle_seconds()
        stale = [n for n in list(self._procs) if now - self._last.get(n, now) > limit]
        for n in stale:
            self._stop(n)
        return stale

    def running(self) -> list[int]:
        return sorted(n for n, p in self._procs.items() if p.poll() is None)

    def start_reaper(self) -> None:
        if self._reaper is None:
            self._reaper = asyncio.create_task(self._reap_loop())

    async def _reap_loop(self) -> None:
        while True:
            await asyncio.sleep(30)
            self.reap_idle()

    async def shutdown(self) -> None:
        if self._reaper is not None:
            self._reaper.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._reaper
            self._reaper = None
        for n in list(self._procs):
            self._stop(n)


MANAGER = LabManager()


async def ensure_for(spec) -> None:
    """Start the lab server behind ``spec`` when running on demand (no-op for every other mode and spec)."""
    if lazy() and spec.port is not None:
        await MANAGER.ensure(spec.port - 9000)
