"""Tracing for auditability and provenance (OpenTelemetry, Langfuse-compatible).

Every pipeline run is one trace: a root ``guardian.run`` span with one child span per stage
(connect, list_tools, static_check, tool_call, runtime_check, behavioral_check, a2a_hop,
enforcement) and one ``llm.complete`` span per model call (model, tokens, latency, cache hit,
slots tried). Spans are always written to ``logs/traces.jsonl`` so a run can be reconstructed
offline; when Langfuse keys are present they are also exported to Langfuse over OTLP:

    LANGFUSE_PUBLIC_KEY=pk-lf-...   LANGFUSE_SECRET_KEY=sk-lf-...
    LANGFUSE_HOST=https://cloud.langfuse.com        # EU cloud (default); US: https://us.cloud.langfuse.com; or your own URL

Any other OTLP backend works through the standard ``OTEL_EXPORTER_OTLP_ENDPOINT`` variable.
Google ADK emits its own spans into the same provider. Text is truncated before it is attached;
nothing leaves the machine unless one of the exporters above is configured.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import threading
from pathlib import Path
from typing import Any, Optional, Sequence

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor, SpanExporter, SpanExportResult

from src.config import resolve_path

log = logging.getLogger(__name__)
_LOCK = threading.Lock()
_PROVIDER: Optional[TracerProvider] = None
MAX_ATTR = 1200


def clip(value: Any, n: int = MAX_ATTR) -> str:
    s = value if isinstance(value, str) else json.dumps(value, default=str)
    return s if len(s) <= n else s[: n - 1] + "…"


class JsonlSpanExporter(SpanExporter):
    """Appends one JSON line per finished span (the offline provenance record)."""

    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        try:
            with _LOCK, self.path.open("a", encoding="utf-8") as fh:
                for s in spans:
                    ctx, parent = s.get_span_context(), s.parent
                    fh.write(json.dumps({
                        "trace_id": f"{ctx.trace_id:032x}", "span_id": f"{ctx.span_id:016x}",
                        "parent_id": f"{parent.span_id:016x}" if parent else None, "name": s.name,
                        "start_ns": s.start_time, "end_ns": s.end_time,
                        "duration_ms": round((s.end_time - s.start_time) / 1e6, 2) if s.end_time else None,
                        "status": s.status.status_code.name,
                        "attributes": {k: v for k, v in (s.attributes or {}).items()},
                        "events": [{"name": e.name, "attributes": dict(e.attributes or {})} for e in s.events],
                    }, default=str) + "\n")
            return SpanExportResult.SUCCESS
        except OSError as exc:      # never let tracing break a run
            log.warning("trace file write failed: %s", exc)
            return SpanExportResult.FAILURE

    def shutdown(self) -> None:  # noqa: D401
        return None


def langfuse_configured() -> bool:
    return bool(os.environ.get("LANGFUSE_PUBLIC_KEY") and os.environ.get("LANGFUSE_SECRET_KEY"))


def _remote_exporter() -> Optional[SpanExporter]:
    try:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    except Exception:       # exporter package missing: local file only
        return None
    if langfuse_configured():
        host = os.environ.get("LANGFUSE_HOST", "https://cloud.langfuse.com").rstrip("/")
        token = base64.b64encode(
            f"{os.environ['LANGFUSE_PUBLIC_KEY']}:{os.environ['LANGFUSE_SECRET_KEY']}".encode()).decode()
        return OTLPSpanExporter(endpoint=f"{host}/api/public/otel/v1/traces",
                                headers={"Authorization": f"Basic {token}",
                                         "x-langfuse-ingestion-version": "4"})   # without it traces show up ~10 min late
    if os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
        return OTLPSpanExporter()
    return None


def init_tracing(path: Optional[Path] = None, force: bool = False) -> TracerProvider:
    """Create the process-wide provider once (``force=True`` builds a fresh one, for tests)."""
    global _PROVIDER
    with _LOCK:
        if _PROVIDER is not None and not force:
            return _PROVIDER
        provider = TracerProvider(resource=Resource.create({"service.name": "mcp-guardian"}))
        provider.add_span_processor(SimpleSpanProcessor(JsonlSpanExporter(path or resolve_path("traces"))))
        remote = _remote_exporter()
        if remote is not None:
            provider.add_span_processor(BatchSpanProcessor(remote))
            log.info("tracing: also exporting to %s", "Langfuse" if langfuse_configured() else "OTLP endpoint")
        _PROVIDER = provider
        if not force:
            try:      # let Google ADK's own spans land in the same trace store
                trace.set_tracer_provider(provider)
            except Exception:        # a provider was already installed; ours still works directly
                pass
        return provider


def tracer() -> trace.Tracer:
    return init_tracing().get_tracer("mcp-guardian")


def current_trace_id() -> Optional[str]:
    ctx = trace.get_current_span().get_span_context()
    return f"{ctx.trace_id:032x}" if ctx and ctx.is_valid else None


def flush() -> None:
    if _PROVIDER is not None:
        _PROVIDER.force_flush()
