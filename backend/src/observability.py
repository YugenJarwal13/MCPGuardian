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


def langfuse_host() -> str:
    """``LANGFUSE_HOST`` (or ``LANGFUSE_BASE_URL``, the name Langfuse's own docs use)."""
    return (os.environ.get("LANGFUSE_HOST") or os.environ.get("LANGFUSE_BASE_URL")
            or "https://cloud.langfuse.com").rstrip("/")


def langfuse_configured() -> bool:
    return bool(os.environ.get("LANGFUSE_PUBLIC_KEY") and os.environ.get("LANGFUSE_SECRET_KEY"))


def _remote_exporter() -> Optional[SpanExporter]:
    try:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    except Exception:       # exporter package missing: local file only
        return None
    if langfuse_configured():
        host = langfuse_host()
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


# ---------------------------------------------------------------- security scores

def security_scores(stages: dict[str, dict], final: dict) -> list[dict]:
    """Evaluation scores for one run, derived only from what the run itself produced.

    ``stages`` maps stage -> {"status", "engine", "confidence", "reasoning"} for stages that finished;
    ``final`` is the ``done`` event's {"status", "decision", "flagged", "total"}.
    Scores: the decision, a 0-1 risk level (block 1, escalate 0.5, allow 0, inspection with flagged tools 0.5),
    one flag per inspection layer, whether a leaked credential was seen, and how much of the inspection was done
    by the language model rather than the regex fallback."""
    out: list[dict] = []

    def add(name: str, value: Any, kind: str, comment: str = "") -> None:
        out.append({"name": name, "value": value, "dataType": kind, **({"comment": comment[:400]} if comment else {})})

    decision = final.get("decision")
    if decision:
        add("guardian.decision", str(decision), "CATEGORICAL")
        d = str(decision)
        add("guardian.risk", 1.0 if d.startswith("block") or d == "escalate_denied"
            else 0.5 if d.startswith("escalate") else 0.0, "NUMERIC", "block 1, escalate 0.5, allow 0")
    elif final.get("total") is not None:                       # an inspection-only run
        flagged = int(final.get("flagged") or 0)
        add("guardian.decision", "inspection_flagged" if flagged else "inspection_clean", "CATEGORICAL")
        add("guardian.risk", 0.5 if flagged else 0.0, "NUMERIC", f"{flagged} of {final['total']} tools flagged")
    for stage, label in (("static_check", "static"), ("runtime_check", "runtime"), ("behavioral_check", "behavioral")):
        st = stages.get(stage)
        if st and st.get("status") in ("passed", "flagged", "blocked"):
            add(f"guardian.{label}_flagged", 1 if st["status"] != "passed" else 0, "BOOLEAN",
                (st.get("reasoning") or "")[:300])
    rt = stages.get("runtime_check")
    if rt and rt.get("status") in ("passed", "flagged"):
        add("guardian.credential_leak", 1 if (rt.get("reasoning") or "").startswith("Credential scan") else 0, "BOOLEAN")
    judged = [stages[x] for x in ("static_check", "runtime_check") if x in stages and stages[x].get("engine") not in (None, "none")]
    if judged:
        add("guardian.llm_coverage", round(sum(1 for j in judged if j["engine"] == "llm") / len(judged), 3), "NUMERIC",
            "share of inspection stages answered by the language model (the rest used regex rules)")
    return out


def send_scores(trace_id: str, scores: list[dict]) -> None:
    """Post scores to Langfuse in the background. A no-op unless Langfuse is configured; never raises."""
    if not (langfuse_configured() and scores):
        return

    def work() -> None:
        import urllib.request

        token = base64.b64encode(
            f"{os.environ['LANGFUSE_PUBLIC_KEY']}:{os.environ['LANGFUSE_SECRET_KEY']}".encode()).decode()
        for sc in scores:
            body = json.dumps({**sc, "traceId": trace_id, "id": f"{trace_id}-{sc['name']}"}).encode()
            req = urllib.request.Request(f"{langfuse_host()}/api/public/scores", data=body, method="POST",
                                         headers={"Authorization": f"Basic {token}", "Content-Type": "application/json"})
            try:
                urllib.request.urlopen(req, timeout=20).read()
            except Exception as exc:      # noqa: BLE001 - scoring must never affect a run
                log.warning("langfuse score %s not delivered: %s", sc["name"], exc)

    threading.Thread(target=work, name="langfuse-scores", daemon=True).start()
