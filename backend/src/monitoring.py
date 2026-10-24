"""Task monitoring through framework callbacks.

CrewAI and Google ADK both call back into the application as agents work. These hooks record the
intermediate outputs, the execution flow and any errors in the same audit trail the pipeline events
use (``logs/audit_trail.jsonl``, layer ``crewai_callback`` / ``adk_callback`` / ``error``) and attach
them to the active trace span, so a failure can be debugged from either place.

All hooks are exception-safe: monitoring must never break a run.
"""
from __future__ import annotations

import logging
from typing import Any

from opentelemetry import trace

from src.audit import log_decision
from src.observability import clip, current_trace_id

log = logging.getLogger(__name__)


def _record(layer: str, event: str, **fields: Any) -> None:
    try:
        tid = current_trace_id()
        log_decision({"layer": layer, "event": event, **({"trace_id": tid} if tid else {}),
                      **{k: clip(v, 600) if isinstance(v, str) else v for k, v in fields.items()}})
        span = trace.get_current_span()
        if span.is_recording():
            span.add_event(f"{layer}.{event}", {k: clip(str(v), 300) for k, v in fields.items()})
    except Exception as exc:      # noqa: BLE001 - monitoring must not raise
        log.debug("monitoring hook failed: %s", exc)


def record_error(layer: str, where: str, exc: BaseException) -> None:
    _record("error", f"{layer}_error", where=where, error_type=type(exc).__name__, message=str(exc)[:300])
    try:
        span = trace.get_current_span()
        if span.is_recording():
            span.record_exception(exc)
    except Exception:      # noqa: BLE001
        pass


# ------------------------------------------------------------------ CrewAI
def crew_step_callback(role: str):
    """Called after every reasoning step of an inspection agent."""
    def step(step_output: Any = None) -> None:
        text = getattr(step_output, "output", None) or getattr(step_output, "text", None) or str(step_output)
        _record("crewai_callback", "agent_step", agent=role, kind=type(step_output).__name__, output=text)
    return step


def crew_task_callback(role: str):
    """Called when an inspection task finishes, with its (structured) output."""
    def done(task_output: Any = None) -> None:
        pyd = getattr(task_output, "pydantic", None)
        _record("crewai_callback", "task_finished", agent=role,
                verdict=getattr(pyd, "verdict", None), confidence=getattr(pyd, "confidence", None),
                output=getattr(task_output, "raw", "") or "")
    return done


# --------------------------------------------------------------------- ADK
# ADK invokes these with keyword arguments (callback_context=..., llm_request=...), so accept both forms.
def _ctx_name(args: tuple, kwargs: dict) -> str:
    ctx = kwargs.get("callback_context") or (args[0] if args else None)
    return str(getattr(ctx, "agent_name", "") or getattr(getattr(ctx, "_invocation_context", None), "agent", None) or "")


def adk_before_model(*args: Any, **kwargs: Any) -> None:
    _record("adk_callback", "before_model", agent=_ctx_name(args, kwargs))
    return None


def adk_after_model(*args: Any, **kwargs: Any) -> None:
    resp = kwargs.get("llm_response") or (args[1] if len(args) > 1 else None)
    parts = getattr(getattr(resp, "content", None), "parts", None) or []
    text = " ".join(getattr(p, "text", "") or "" for p in parts)
    _record("adk_callback", "after_model", agent=_ctx_name(args, kwargs), output=text)
    return None


def adk_on_model_error(*args: Any, **kwargs: Any) -> None:
    err = kwargs.get("error") or (args[2] if len(args) > 2 else None)
    _record("error", "adk_model_error", agent=_ctx_name(args, kwargs),
            error_type=type(err).__name__, message=str(err)[:300])
    return None        # let ADK's normal error handling continue


def adk_before_agent(*args: Any, **kwargs: Any) -> None:
    _record("adk_callback", "agent_started", agent=_ctx_name(args, kwargs))
    return None


def adk_after_agent(*args: Any, **kwargs: Any) -> None:
    _record("adk_callback", "agent_finished", agent=_ctx_name(args, kwargs))
    return None


def adk_after_tool(*args: Any, **kwargs: Any) -> None:
    tool = kwargs.get("tool") or (args[0] if args else None)
    _record("adk_callback", "after_tool", tool=getattr(tool, "name", str(tool)),
            output=str(kwargs.get("tool_response", "")))
    return None


def adk_on_tool_error(*args: Any, **kwargs: Any) -> None:
    tool = kwargs.get("tool") or (args[0] if args else None)
    err = kwargs.get("error")
    _record("error", "adk_tool_error", tool=getattr(tool, "name", str(tool)),
            error_type=type(err).__name__, message=str(err)[:300])
    return None


ADK_MONITORING = {
    "before_agent_callback": adk_before_agent, "after_agent_callback": adk_after_agent,
    "before_model_callback": adk_before_model, "after_model_callback": adk_after_model,
    "on_model_error_callback": adk_on_model_error,
}
ADK_TOOL_MONITORING = {"after_tool_callback": adk_after_tool, "on_tool_error_callback": adk_on_tool_error}
