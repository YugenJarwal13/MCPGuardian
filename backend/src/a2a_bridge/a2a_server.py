"""The ADK PipelineManager served as a real A2A endpoint.

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


class TraceContextMiddleware:
    """Pure ASGI middleware: adopts the caller's W3C trace context, so everything the case manager does while
    handling a message is a child of the pipeline's ``a2a_hop`` span instead of the start of a new trace."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        from opentelemetry import context as otel_context
        from opentelemetry.propagate import extract

        carrier = {k.decode("latin-1"): v.decode("latin-1") for k, v in scope.get("headers", [])}
        token = otel_context.attach(extract(carrier))
        try:
            await self.app(scope, receive, send)
        finally:
            otel_context.detach(token)


def build_a2a_app(manager: PipelineManager, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT):
    app = to_a2a(manager.agent, host=host, port=port, runner=manager.runner)
    app.add_middleware(TraceContextMiddleware)
    return app


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
