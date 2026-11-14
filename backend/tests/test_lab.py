"""The on-demand DVMCP lab: starts the picked challenge only, caps how many stay up, reaps idle ones."""
from __future__ import annotations

import asyncio
import subprocess
import sys
import time

import pytest

from src.api import lab


class _Fake:
    def __init__(self):
        self.stopped = False

    def poll(self):
        return 0 if self.stopped else None

    def terminate(self):
        self.stopped = True

    def wait(self, timeout=None):
        return 0

    def kill(self):
        self.stopped = True


def test_modes(monkeypatch):
    monkeypatch.setenv("GUARDIAN_LAB", "lazy")
    assert lab.lazy() and lab.mode() == "lazy"
    monkeypatch.setenv("GUARDIAN_LAB", "bogus")
    assert lab.mode() == "off" and not lab.lazy()


def test_only_the_picked_server_starts_and_the_oldest_is_evicted(monkeypatch):
    monkeypatch.setenv("GUARDIAN_LAB_MAX", "2")
    monkeypatch.setattr(lab, "installed", lambda: True)
    up: set[int] = set()
    mgr = lab.LabManager()
    spawned: list[int] = []

    def spawn(n):
        spawned.append(n)
        up.add(9000 + n)
        p = _Fake()
        orig = p.terminate
        p.terminate = lambda: (up.discard(9000 + n), orig())
        return p

    monkeypatch.setattr(mgr, "_spawn", spawn)
    monkeypatch.setattr(lab, "port_up", lambda port: port in up)

    async def go():
        await mgr.ensure(2)
        await mgr.ensure(2)                      # already up: not started again
        await mgr.ensure(5)
        await mgr.ensure(7)                      # over the cap: the least recently used (2) is stopped

    asyncio.run(go())
    assert spawned == [2, 5, 7] and mgr.running() == [5, 7]


def test_idle_servers_are_reaped(monkeypatch):
    monkeypatch.setenv("GUARDIAN_LAB_IDLE_S", "30")
    mgr = lab.LabManager()
    mgr._procs[3] = _Fake()
    mgr._last[3] = time.monotonic() - 100
    assert mgr.reap_idle() == [3] and mgr.running() == []


def test_a_server_that_never_comes_up_is_an_error(monkeypatch):
    monkeypatch.setenv("GUARDIAN_LAB_START_S", "5")
    monkeypatch.setattr(lab, "installed", lambda: True)
    mgr = lab.LabManager()
    monkeypatch.setattr(mgr, "_spawn", lambda n: subprocess.Popen([sys.executable, "-c", "raise SystemExit(1)"]))
    monkeypatch.setattr(lab, "port_up", lambda p: False)
    with pytest.raises(lab.LabError):
        asyncio.run(mgr.ensure(4))
    assert mgr.running() == []
