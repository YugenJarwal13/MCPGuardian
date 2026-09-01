"""Phase 2 — GuardianInterceptor (orchestration point).

This is the one file touched in almost every subsequent phase, so its interface
is fixed early and its body is filled in incrementally:

    Phase 3  -> screen_tool_metadata  runs the static-analysis crew
    Phase 4  -> screen_tool_response  runs the runtime-inspection crew
    Phase 5  -> screen_tool_response  also updates the behavioural fingerprint
    Phase 6  -> pre_call_check        combines verdicts + enforces allow/block/escalate

Keep it thin — it should read like a sequence diagram, not hold business logic.
In its default configuration (all components ``None``) every method is a
pass-through, so the Phase 0 MCP hello-world works unchanged when routed through
``GuardedMCPClient(session, GuardianInterceptor())``.
"""
from __future__ import annotations

from typing import Any, Optional


class GuardianInterceptor:
    def __init__(
        self,
        static_crew: Optional[Any] = None,
        runtime_crew: Optional[Any] = None,
        anomaly_agent: Optional[Any] = None,
        enforcement_callback: Optional[Any] = None,
    ):
        self._static_crew = static_crew                    # wired in Phase 3
        self._runtime_crew = runtime_crew                  # wired in Phase 4
        self._anomaly_agent = anomaly_agent                # wired in Phase 5
        self._enforcement_callback = enforcement_callback  # wired in Phase 6

    async def screen_tool_metadata(self, tools: Any) -> Any:
        if self._static_crew is None:
            return tools  # Phase 2: no-op pass-through
        # Phase 3+: run each tool through the static-analysis crew, attach the
        # verdict as tool metadata, let enforcement decide whether to hide/flag it.
        raise NotImplementedError("wired in Phase 3")

    async def pre_call_check(self, name: str, arguments: dict, session: Any) -> Optional[Any]:
        if self._enforcement_callback is None:
            return None  # Phase 2: never short-circuits
        # Phase 6+: check the tool's last known verdict + allowlist.yaml; return a
        # refusal CallToolResult here to hard-block, or None to proceed.
        raise NotImplementedError("wired in Phase 6")

    async def screen_tool_response(self, name: str, response: Any) -> Any:
        if self._runtime_crew is None:
            return response  # Phase 2: no-op pass-through
        # Phase 4+: run the response through the runtime-inspection agent;
        # Phase 5+: also update/check the behavioural fingerprint;
        # Phase 6+: let enforcement decide allow/redact/block, and always append a
        # decision record to logs/audit_trail.jsonl regardless of outcome.
        raise NotImplementedError("wired in Phase 4")
