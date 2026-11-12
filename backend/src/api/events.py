"""The event schema streamed over ``WS /ws/run``.

One event per stage transition: a ``started`` event before a stage begins and a
result event (``passed`` / ``flagged`` / ``blocked`` / ``error``) after it. Every
event is ALSO written through ``log_decision`` so the Streamlit audit dashboard
and the live UI read from one source of truth.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from opentelemetry import context as otel_context
from opentelemetry import trace

from src.audit import log_decision
from src.observability import clip, environment, hash_user, send_scores, security_scores, tracer
from src.usage import RUN_USAGE, RunUsage

# Langfuse observation type of each stage: the inspections are guardrails, the real call is a tool.
STAGE_TYPE = {"static_check": "guardrail", "runtime_check": "guardrail", "behavioral_check": "guardrail",
              "enforcement": "guardrail", "tool_call": "tool"}

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
            "guardian.run_id": run_id, "guardian.server_id": server_id,
            "langfuse.observation.type": "chain",
            "langfuse.trace.name": "guardian.run",
            "langfuse.trace.tags": ["mcp-guardian", environment(), server_id[:60]],
            "langfuse.trace.metadata.server_id": server_id,
            "langfuse.session.id": run_id, "input.value": f"Guardian run on {server_id}"})
        self.usage = RunUsage()              # every model call in this run adds its tokens and cost here
        RUN_USAGE.set(self.usage)
        self._summary: dict[str, dict] = {}      # stage -> outcome, turned into Langfuse scores at the end
        self.trace_id = f"{self._root.get_span_context().trace_id:032x}"
        self._root_ctx = trace.set_span_in_context(self._root)
        self._spans: dict[str, tuple[Any, Any]] = {}      # stage -> (span, context token)
        self._closed = False
        self.scrub = lambda value: value     # set to redact credentials from everything that leaves the run

    # -- tracing ---------------------------------------------------------------
    def set_user(self, identifier: str) -> None:
        """Attribute the run to a visitor for Langfuse's per-user views, by a hash: the address is never stored."""
        self._root.set_attribute("langfuse.user.id", hash_user(identifier))

    def _open_stage(self, stage: str, message: str) -> None:
        if stage in self._spans:
            return
        attrs = {"guardian.stage": stage, "input.value": clip(message)}
        if STAGE_TYPE.get(stage):
            attrs["langfuse.observation.type"] = STAGE_TYPE[stage]
        if self.tool_name:
            attrs["guardian.tool_name"] = self.tool_name
        span = tracer().start_span(f"guardian.{stage}", context=self._root_ctx, attributes=attrs)
        token = otel_context.attach(trace.set_span_in_context(span))     # LLM spans nest under the stage
        self._spans[stage] = (span, token)

    def _close_stage(self, stage: str, status: str, message: str, engine: str, mm: dict,
                     detail: dict, elapsed: float) -> None:
        pair = self._spans.pop(stage, None)
        if pair is None:
            return
        span, token = pair
        self._summary[stage] = {"status": status, "engine": engine, "confidence": detail.get("confidence"),
                                "reasoning": detail.get("reasoning")}
        span.set_attribute("guardian.status", status)
        span.set_attribute("guardian.engine", engine)
        span.set_attribute("output.value", clip(message))
        span.set_attribute("guardian.elapsed_ms", elapsed)
        if mm.get("model"):
            # not gen_ai.*: those make Langfuse classify the stage as a model call; the real calls are llm.complete
            span.set_attribute("guardian.model", mm["model"])
            span.set_attribute("guardian.provider", mm.get("provider") or "")
        for key in ("verdict", "confidence", "requested_scope", "z_score", "case_id", "final_decision"):
            if detail.get(key) is not None:
                span.set_attribute(f"guardian.{key}", detail[key] if isinstance(detail[key], (int, float)) else str(detail[key]))
        if detail.get("reasoning"):
            span.set_attribute("guardian.reasoning", clip(detail["reasoning"]))
        if detail.get("flagged_phrases"):
            span.set_attribute("guardian.flagged_phrases", clip(detail["flagged_phrases"]))
        if status in ("flagged", "blocked", "error"):
            span.set_status(trace.Status(trace.StatusCode.ERROR if status == "error" else trace.StatusCode.OK))
            span.set_attribute("langfuse.observation.level", "ERROR" if status == "error" else "WARNING")
            span.set_attribute("langfuse.observation.status_message", clip(message, 300))
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
        message, detail = self.scrub(message), self.scrub(detail)
        if status == "started":
            self._stage_start[stage] = now
            elapsed = 0.0
        else:
            elapsed = (now - self._stage_start.get(stage, now)) * 1000
        mm = model_meta or {}
        if stage == "tool_call" and status == "started" and (detail or {}).get("arguments") is not None:
            request = clip({"server": self._server_id, "tool": self.tool_name, "arguments": detail["arguments"]}, 3000)
            self._root.set_attribute("langfuse.trace.input", request)
            self._root.set_attribute("input.value", request)
        if status == "started":
            self._open_stage(stage, message)
        elif status != "escalate" and stage != "done":
            self._close_stage(stage, status, message, engine, mm, detail or {}, elapsed)
        elif status == "escalate" and stage in self._spans:
            self._spans[stage][0].add_event("human_decision_requested", {"message": clip(message, 300)})
        if stage == "done":
            self._root.set_attribute("guardian.final_status", status)
            self._root.set_attribute("guardian.final_decision", str((detail or {}).get("final_decision", "")))
            d = detail or {}
            tools = d.get("tools") or []
            outcome = clip({"status": status, "decision": d.get("final_decision"), "summary": message}, 2000)
            self._root.set_attribute("output.value", outcome)
            self._root.set_attribute("langfuse.trace.output", outcome)
            self._root.set_attribute("langfuse.trace.metadata.usage", json.dumps(self.usage.as_dict()))
            if self.tool_name:
                self._root.set_attribute("guardian.tool_name", self.tool_name)
            send_scores(self.trace_id, security_scores(self._summary, {
                "status": status, "decision": d.get("final_decision"),
                "total": len(tools) if d.get("inspect_only") else None,
                "flagged": sum(1 for t in tools if t.get("verdict") != "clean")}, self.usage))
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
