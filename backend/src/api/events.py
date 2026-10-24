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

from opentelemetry import context as otel_context
from opentelemetry import trace

from src.audit import log_decision
from src.observability import clip, tracer

Stage = Literal["connect", "list_tools", "static_check", "tool_call", "runtime_check",
                "behavioral_check", "a2a_hop", "enforcement", "done"]
Status = Literal["started", "passed", "flagged", "blocked", "escalate", "error"]
Engine = Literal["llm", "heuristic", "heuristic_fallback", "timeout", "none"]

STAGES: list[str] = ["connect", "list_tools", "static_check", "tool_call", "runtime_check",
                     "behavioral_check", "a2a_hop", "enforcement", "done"]


class PipelineEvent(BaseModel):
    run_id: str
    stage: Stage
    status: Status
    message: str
    detail: dict[str, Any] = Field(default_factory=dict)
    engine: Engine = "none"
    trace_id: Optional[str] = None      # ties this event to its trace (Langfuse / logs/traces.jsonl)
    provider: Optional[str] = None      # which model answered (LLM verdicts only)
    model: Optional[str] = None
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
        # one trace per run: a root span, plus one child span per stage while that stage is open
        self._root = tracer().start_span("guardian.run", attributes={
            "guardian.run_id": run_id, "guardian.server_id": server_id})
        self.trace_id = f"{self._root.get_span_context().trace_id:032x}"
        self._root_ctx = trace.set_span_in_context(self._root)
        self._spans: dict[str, tuple[Any, Any]] = {}      # stage -> (span, context token)
        self._closed = False

    # -- tracing ---------------------------------------------------------------
    def _open_stage(self, stage: str, message: str) -> None:
        if stage in self._spans:
            return
        span = tracer().start_span(f"guardian.{stage}", context=self._root_ctx,
                                   attributes={"guardian.stage": stage, "input.value": clip(message)})
        token = otel_context.attach(trace.set_span_in_context(span))     # LLM spans nest under the stage
        self._spans[stage] = (span, token)

    def _close_stage(self, stage: str, status: str, message: str, engine: str, mm: dict,
                     detail: dict, elapsed: float) -> None:
        pair = self._spans.pop(stage, None)
        if pair is None:
            return
        span, token = pair
        span.set_attribute("guardian.status", status)
        span.set_attribute("guardian.engine", engine)
        span.set_attribute("output.value", clip(message))
        span.set_attribute("guardian.elapsed_ms", elapsed)
        if mm.get("model"):
            span.set_attribute("gen_ai.request.model", mm["model"])
            span.set_attribute("gen_ai.system", mm.get("provider") or "")
        for key in ("verdict", "confidence", "requested_scope", "z_score", "case_id", "final_decision"):
            if detail.get(key) is not None:
                span.set_attribute(f"guardian.{key}", detail[key] if isinstance(detail[key], (int, float)) else str(detail[key]))
        if detail.get("reasoning"):
            span.set_attribute("guardian.reasoning", clip(detail["reasoning"]))
        if detail.get("flagged_phrases"):
            span.set_attribute("guardian.flagged_phrases", clip(detail["flagged_phrases"]))
        if status in ("flagged", "blocked", "error"):
            span.set_status(trace.Status(trace.StatusCode.ERROR if status == "error" else trace.StatusCode.OK))
        try:
            otel_context.detach(token)
        except Exception:      # noqa: BLE001 - token from another context: harmless
            pass
        span.end()

    def finish(self) -> None:
        """End any span still open (a run that was cut short) and the root span. Idempotent."""
        if self._closed:
            return
        self._closed = True
        for stage in list(self._spans):
            self._close_stage(stage, "error", "run ended before this stage finished", "none", {}, {}, 0.0)
        self._root.end()

    async def emit(self, stage: str, status: str, message: str,
                   detail: Optional[dict] = None, engine: str = "none",
                   model_meta: Optional[dict] = None) -> PipelineEvent:
        now = time.monotonic()
        if status == "started":
            self._stage_start[stage] = now
            elapsed = 0.0
        else:
            elapsed = (now - self._stage_start.get(stage, now)) * 1000
        mm = model_meta or {}
        if status == "started":
            self._open_stage(stage, message)
        elif status != "escalate" and stage != "done":
            self._close_stage(stage, status, message, engine, mm, detail or {}, elapsed)
        elif status == "escalate" and stage in self._spans:
            self._spans[stage][0].add_event("human_decision_requested", {"message": clip(message, 300)})
        if stage == "done":
            self._root.set_attribute("guardian.final_status", status)
            self._root.set_attribute("guardian.final_decision", str((detail or {}).get("final_decision", "")))
            self._root.set_attribute("output.value", clip(message))
        event = PipelineEvent(run_id=self.run_id, stage=stage, status=status, message=message,
                              detail=detail or {}, engine=engine, trace_id=self.trace_id, provider=mm.get("provider"),
                              model=mm.get("model"), elapsed_ms=round(elapsed, 2))
        log_decision({"layer": "pipeline_event", "run_id": self.run_id,
                      "server_id": self._server_id, "tool_name": self.tool_name,
                      "trace_id": self.trace_id, "stage": stage, "status": status, "message": message,
                      "engine": engine, "provider": event.provider, "model": event.model,
                      "elapsed_ms": event.elapsed_ms, "detail": event.detail})
        await self._send(event.model_dump())
        return event
