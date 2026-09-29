"""Phase 11.3 — the ADK PipelineManager served as a real A2A endpoint.

``google.adk.a2a.utils.agent_to_a2a.to_a2a`` turns the case-manager ADK agent
into an A2A (JSON-RPC over HTTP) Starlette app: it publishes an agent card at
``/.well-known/agent-card.json`` and accepts ``message/send``. We hand it the
PipelineManager's OWN ``Runner`` so every case the A2A server receives lands in
the same ADK session service that ``PipelineManager.get_case`` reads.

Run standalone (durable SQLite-backed ADK sessions):
    python -m src.a2a_bridge.a2a_server            # http://127.0.0.1:8765
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import socket
from typing import AsyncIterator

import uvicorn
from google.adk.a2a.utils.agent_to_a2a import to_a2a

from src.adk_layer.pipeline_manager import PipelineManager

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765


def build_a2a_app(manager: PipelineManager, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT):
    return to_a2a(manager.agent, host=host, port=port, runner=manager.runner)


def free_port() -> int:
    with socket.socket() as s:
        s.bind((DEFAULT_HOST, 0))
        return s.getsockname()[1]


@contextlib.asynccontextmanager
async def serve_in_background(
    manager: PipelineManager, host: str = DEFAULT_HOST, port: int | None = None
) -> AsyncIterator[str]:
    """Run the A2A server inside the current event loop (a real HTTP listener
    on a real socket) and yield its base URL. Used by the API and tests."""
    port = port or free_port()
    server = uvicorn.Server(uvicorn.Config(build_a2a_app(manager, host, port), host=host,
                                           port=port, log_level="warning", lifespan="on"))
    task = asyncio.create_task(server.serve())
    try:
        for _ in range(200):
            if server.started:
                break
            if task.done():
                task.result()  # surface the startup error
            await asyncio.sleep(0.05)
        else:
            raise RuntimeError("A2A server did not start")
        yield f"http://{host}:{port}"
    finally:
        server.should_exit = True
        await task


def main() -> None:
    from src.config import resolve_path

    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default=DEFAULT_HOST)
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = ap.parse_args()
    db = resolve_path("fingerprint_db").with_name("cases.db")
    manager = PipelineManager(db_path=str(db))
    print(f"A2A case manager on http://{args.host}:{args.port} (ADK sessions: {db})")
    uvicorn.run(build_a2a_app(manager, args.host, args.port), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
