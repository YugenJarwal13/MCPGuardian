"""The event schema streamed over ``WS /ws/run``.

One event per stage transition: a ``started`` event before a stage begins and a
result event (``passed`` / ``flagged`` / ``blocked`` / ``error``) after it. Every
event is ALSO written through ``log_decision`` so the Streamlit audit dashboard
and the live UI read from one source of truth.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from src.audit import log_decision

Stage = Literal["connect", "list_tools", "static_check", "tool_call", "runtime_check",
                "behavioral_check", "a2a_hop", "enforcement", "done"]
Status = Literal["started", "passed", "flagged", "blocked", "escalate", "error"]
Engine = Literal["llm", "heuristic", "heuristic_fallback", "none"]

STAGES: list[str] = ["connect", "list_tools", "static_check", "tool_call", "runtime_check",
                     "behavioral_check", "a2a_hop", "enforcement", "done"]


class PipelineEvent(BaseModel):
    run_id: str
    stage: Stage
    status: Status
    message: str
    detail: dict[str, Any] = Field(default_factory=dict)
    engine: Engine = "none"
    elapsed_ms: float = 0.0
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class EventEmitter:
    """Builds events, times each stage, logs them to the audit trail and hands
    them to ``send`` (the WebSocket)."""

    def __init__(self, run_id: str, send, server_id: str, tool_name: Optional[str] = None):
        self.run_id = run_id
        self._send = send
        self._server_id = server_id
        self.tool_name = tool_name
        self._stage_start: dict[str, float] = {}

    async def emit(self, stage: str, status: str, message: str,
                   detail: Optional[dict] = None, engine: str = "none") -> PipelineEvent:
        now = time.monotonic()
        if status == "started":
            self._stage_start[stage] = now
            elapsed = 0.0
        else:
            elapsed = (now - self._stage_start.get(stage, now)) * 1000
        event = PipelineEvent(run_id=self.run_id, stage=stage, status=status, message=message,
                              detail=detail or {}, engine=engine, elapsed_ms=round(elapsed, 2))
        log_decision({"layer": "pipeline_event", "run_id": self.run_id,
                      "server_id": self._server_id, "tool_name": self.tool_name,
                      "stage": stage, "status": status, "message": message,
                      "engine": engine, "elapsed_ms": event.elapsed_ms, "detail": event.detail})
        await self._send(event.model_dump())
        return event
