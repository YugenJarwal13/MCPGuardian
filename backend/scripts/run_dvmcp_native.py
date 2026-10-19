"""Run the DVMCP challenge lab natively (no Docker) on ports 9001-9010.

DVMCP's own ``start_sse_servers.sh`` + Dockerfile is the reference setup. This
launcher is the fallback for machines without Docker: it imports the upstream
challenge modules unmodified and serves them on the same ports and ``/sse`` path.

Two server variants ship upstream, and they differ in a way that matters:

  * ``server_sse.py`` (``--variant sse``) — what the upstream Dockerfile serves on
    9001-9010. Its tools are SIMPLIFIED: e.g. challenge 2's tool descriptions
    contain no hidden instructions at all.
  * ``server.py`` (``--variant full``, the default) — the stdio variant, which
    carries the documented attacks verbatim (``<IMPORTANT>`` / ``<HIDDEN>`` poisoned
    descriptions, the challenge-4 description swap, challenge-5 shadowing tools).
    We serve its ``FastMCP`` object over SSE via ``FastMCP.sse_app()`` on the same
    port and ``/sse`` path, so clients cannot tell the difference.

Deliberate deviation from upstream: upstream binds ``0.0.0.0``; these servers
are *intentionally vulnerable* (challenges 8/9 execute commands), so here they
bind to ``127.0.0.1`` only and are never reachable from the network.

Usage:
    python scripts/run_dvmcp_native.py                  # all 10, poisoned variant
    python scripts/run_dvmcp_native.py --variant sse    # upstream Docker variant
    python scripts/run_dvmcp_native.py --one 2          # just challenge 2
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import signal
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DVMCP = ROOT / "external" / "damn-vulnerable-MCP-server"
HOST = "127.0.0.1"

CHALLENGE_DIRS = {
    1: "easy/challenge1", 2: "easy/challenge2", 3: "easy/challenge3",
    4: "medium/challenge4", 5: "medium/challenge5", 6: "medium/challenge6",
    7: "medium/challenge7", 8: "hard/challenge8", 9: "hard/challenge9",
    10: "hard/challenge10",
}


def _prepare_state_dirs() -> None:
    """Mirror the directory/state setup from upstream start_sse_servers.sh.
    ('/tmp/...' resolves to <drive>:\\tmp\\... on Windows.)"""
    for d in ("/tmp/dvmcp_challenge3/public", "/tmp/dvmcp_challenge3/private",
              "/tmp/dvmcp_challenge4/state", "/tmp/dvmcp_challenge6/user_uploads",
              "/tmp/dvmcp_challenge8/sensitive", "/tmp/dvmcp_challenge10/config"):
        os.makedirs(d, exist_ok=True)
    # Reset the rug-pull counter so challenge 4 starts in its "benign" phase.
    Path("/tmp/dvmcp_challenge4/state/state.json").write_text(
        json.dumps({"weather_tool_calls": 0}), encoding="utf-8")
    Path("/tmp/dvmcp_challenge3/public/welcome.txt").write_text(
        "Welcome to the public directory!\n", encoding="utf-8")


# FastMCP object name inside each stdio server.py (challenge 5 combines two).
_FULL_OBJ = {5: "combined_server"}


def _shim_fastmcp() -> None:
    """Upstream challenge 5 calls ``FastMCP.resource(..., listed=False)``, a kwarg
    current ``mcp`` releases no longer accept. Drop it (the resource is simply
    listed) instead of editing upstream code."""
    from mcp.server.fastmcp import FastMCP

    original = FastMCP.resource
    if getattr(original, "_dvmcp_shim", False):
        return

    def resource(self, uri, *args, listed=None, **kwargs):
        return original(self, uri, *args, **kwargs)

    resource._dvmcp_shim = True
    FastMCP.resource = resource


def _load(n: int, filename: str):
    _shim_fastmcp()
    src =DVMCP / "challenges" / CHALLENGE_DIRS[n] / filename
    if not src.exists():
        sys.exit(f"DVMCP not cloned: {src} missing (run scripts/setup_dvmcp.sh or git clone)")
    spec = importlib.util.spec_from_file_location(f"dvmcp_ch{n}", src)
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(DVMCP))
    spec.loader.exec_module(mod)
    return mod


def run_one(n: int, variant: str) -> None:
    import uvicorn

    port = 9000 + n
    if variant == "sse":
        app = getattr(_load(n, "server_sse.py"), f"Challenge{n}Server")().app
    else:
        app = getattr(_load(n, "server.py"), _FULL_OBJ.get(n, "mcp")).sse_app()
    uvicorn.run(app, host=HOST, port=port, log_level="warning")


def run_all(variant: str) -> None:
    _prepare_state_dirs()
    procs = [
        subprocess.Popen([sys.executable, __file__, "--one", str(n), "--variant", variant],
                         cwd=str(DVMCP))
        for n in CHALLENGE_DIRS
    ]
    print(f"Started {len(procs)} DVMCP servers ({variant} variant) on {HOST}:9001-9010 "
          "(SSE at /sse). Ctrl+C to stop.")
    try:
        for p in procs:
            p.wait()
    except KeyboardInterrupt:
        pass
    finally:
        for p in procs:
            if p.poll() is None:
                p.send_signal(signal.SIGTERM)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--one", type=int, choices=sorted(CHALLENGE_DIRS))
    ap.add_argument("--variant", choices=("full", "sse"), default="full")
    args = ap.parse_args()
    run_one(args.one, args.variant) if args.one else run_all(args.variant)
