"""Phase 2 — GuardedMCPClient.

Wraps a standard MCP ``ClientSession`` so every ``list_tools`` / ``call_tool``
passes through the Guardian pipeline before the caller sees it. The wrapped
session is duck-typed (any object exposing async ``list_tools`` / ``call_tool``),
so this module imports cleanly even when the ``mcp`` package is not installed —
useful for unit-testing the wrapper against a mock session.
"""
from __future__ import annotations

from typing import Any, Protocol


class _SessionLike(Protocol):
    async def list_tools(self) -> Any: ...
    async def call_tool(self, name: str, arguments: dict) -> Any: ...


class GuardedMCPClient:
    """Transparent, screening replacement for a raw MCP ``ClientSession``.

    The agent under protection does not opt in — it simply holds a
    ``GuardedMCPClient`` instead of a ``ClientSession`` and everything is
    screened. In its default (Phase 2) configuration the interceptor is a
    pass-through, so behaviour is identical to the raw session; later phases give
    the interceptor teeth without changing this wrapper's interface.
    """

    def __init__(self, session: _SessionLike, interceptor: "Any"):
        self._session = session
        self._interceptor = interceptor

    async def list_tools(self):
        raw_tools = await self._session.list_tools()
        return await self._interceptor.screen_tool_metadata(raw_tools)

    async def call_tool(self, name: str, arguments: dict):
        # Pre-call gate (allowlist / sensitive-scope / stored-verdict) happens
        # inside the interceptor. It may return a refusal result to hard-block,
        # in which case the underlying session.call_tool is never invoked.
        refusal = await self._interceptor.pre_call_check(name, arguments, self._session)
        if refusal is not None:
            return refusal
        response = await self._session.call_tool(name, arguments)
        return await self._interceptor.screen_tool_response(name, response)
