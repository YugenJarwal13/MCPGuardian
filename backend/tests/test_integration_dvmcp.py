"""Phase 2 — plumbing proof.

Two levels:
1. A mock-session unit test that ALWAYS runs: proves the no-op interceptor is a
   faithful pass-through (list_tools and call_tool return unchanged).
2. A live-DVMCP integration test that SKIPS when the lab is not running: connects
   GuardedMCPClient to challenge port 9001 and asserts both calls return normally
   with the interceptor in its default no-op configuration.
"""
from __future__ import annotations

import socket

import pytest

from src.config import settings
from src.mcp_gateway.client_wrapper import GuardedMCPClient
from src.mcp_gateway.interceptor import GuardianInterceptor


class _FakeSession:
    """Minimal stand-in for an MCP ClientSession."""

    def __init__(self):
        self.call_count = 0

    async def list_tools(self):
        return {"tools": [{"name": "echo", "description": "returns input"}]}

    async def call_tool(self, name, arguments):
        self.call_count += 1
        return {"tool": name, "arguments": arguments, "content": "ok"}


async def test_noop_interceptor_is_passthrough():
    session = _FakeSession()
    client = GuardedMCPClient(session, GuardianInterceptor())  # all components None

    tools = await client.list_tools()
    assert tools == {"tools": [{"name": "echo", "description": "returns input"}]}

    result = await client.call_tool("echo", {"text": "hi"})
    assert result["tool"] == "echo"
    assert result["content"] == "ok"
    assert session.call_count == 1  # the underlying call actually happened


def _port_open(host: str, port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


@pytest.mark.asyncio
async def test_dvmcp_port_9001_noop_roundtrip():
    dv = settings().get("dvmcp", {})
    host, port = dv.get("host", "localhost"), dv.get("port_start", 9001)
    if not _port_open(host, port):
        pytest.skip(f"DVMCP not running on {host}:{port} (run scripts/setup_dvmcp.sh)")

    from mcp import ClientSession
    from mcp.client.sse import sse_client

    async with sse_client(f"http://{host}:{port}/sse") as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            client = GuardedMCPClient(session, GuardianInterceptor())
            listed = await client.list_tools()
            assert listed.tools  # returns normally
            first = listed.tools[0]
            result = await client.call_tool(first.name, {})
            assert result is not None  # poisoned tool "works" — nothing inspects yet
