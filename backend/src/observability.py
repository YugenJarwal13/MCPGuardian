"""Tracing for auditability, provenance and cost (OpenTelemetry, Langfuse-compatible).

Every pipeline run is one trace:

    guardian.run                           the whole run (chain)
      guardian.connect / list_tools        MCP connection and tools/list
      guardian.static_check                inspection of the tool descriptions (guardrail)
        static_inspector (CrewAI)          one agent run per tool
          static_inspector.llm             the model call: model, messages, tokens, cost (generation)
      guardian.tool_call                   the policy gate and the real call
        mcp.call_tool                      the call to the MCP server: arguments in, reply out (tool)
      guardian.runtime_check               inspection of the reply (guardrail)
        runtime_inspector (CrewAI) / runtime_inspector.llm
      guardian.behavioral_check            drift statistics, and (only when drift is flagged)
        behaviour_judge (ADK) / behaviour_judge.llm
      guardian.a2a_hop                     the verdict sent to the ADK case manager over A2A
        case_manager (ADK)                 the case manager's own spans, joined by trace-context propagation
      guardian.enforcement                 allow / block / escalate

Everything is written to ``logs/traces.jsonl`` (rotated) and, when Langfuse keys are present, exported to Langfuse
over OTLP. Between the spans and either destination sits one sanitising step: credential-like values are masked in
every string, ADK's spans are given the names, types and model fields Langfuse needs, and nothing leaves the process
unmasked. Configuration (all optional):

    LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY      enable the Langfuse export
    LANGFUSE_HOST or LANGFUSE_BASE_URL             default https://cloud.langfuse.com (US: https://us.cloud.langfuse.com)
    OTEL_EXPORTER_OTLP_ENDPOINT                    any other OTLP backend instead
    GUARDIAN_ENVIRONMENT                           "local" or "production" (default: production in public mode)
    GUARDIAN_VERSION                               release label shown in Langfuse (default "dev")
    GUARDIAN_TRACE_SAMPLE_RATIO                    0..1, share of runs traced (default 1)
    GUARDIAN_TRACE_FILE                            "off" to skip the local JSONL file (default on)
    GUARDIAN_TRACE_FILE_MAX_MB                     rotate the file at this size (default 25, 3 backups)
    GUARDIAN_TRACE_QUEUE / GUARDIAN_TRACE_DELAY_MS batching of the export (defaults 4096 / 2000)
    GUARDIAN_REF_PRICE_IN_PER_M / _OUT_PER_M       reference prices for the estimated cost score (0.30 / 1.20)

Text is truncated and masked before it is attached; nothing leaves the machine unless an exporter above is set up.
"""
from __future__ import annotations

import atexit
import base64
import hashlib
import json
import logging
import os
import socket
import threading
import time
from pathlib import Path
from typing import Any, Optional, Sequence

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import Event, ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter, SpanExportResult
from opentelemetry.sdk.trace.sampling import ALWAYS_ON, ParentBased, TraceIdRatioBased

from src.config import resolve_path

log = logging.getLogger(__name__)
_LOCK = threading.Lock()
_PROVIDER: Optional[TracerProvider] = None
_ATEXIT = False
MAX_ATTR = 1200
HARD_CAP = 20000          # no single attribute, even a prompt, is ever larger than this


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def _mask(text: str) -> str:
    from src.security.secret_scan import redact_text

    return redact_text(text)


def clip(value: Any, n: int = MAX_ATTR) -> str:
    """Text for a span attribute: JSON for structures, masked of credentials, cut to ``n`` characters."""
    s = value if isinstance(value, str) else json.dumps(value, default=str)
    s = _mask(s)
    return s if len(s) <= n else s[: n - 1] + "…"


# ------------------------------------------------------------------------------------------ export health

class ExportStats:
    """What an exporter has done, so a silent export failure shows up in /health instead of nowhere."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.exported = 0
        self.failed = 0
        self.last_ok: Optional[float] = None
        self.last_error: Optional[str] = None
        self._last_warned = 0.0

    def ok(self, n: int) -> None:
        self.exported += n
        self.last_ok = time.time()

    def fail(self, n: int, why: str) -> None:
        self.failed += n
        self.last_error = why[:200]
        if time.time() - self._last_warned > 60:      # one warning a minute, not one per batch
            self._last_warned = time.time()
            log.warning("tracing: %s export failed (%s)", self.name, why)

    def as_dict(self) -> dict:
        return {"exported_spans": self.exported, "failed_spans": self.failed, "last_error": self.last_error,
                "last_success_age_s": round(time.time() - self.last_ok, 1) if self.last_ok else None}


STATS: dict[str, ExportStats] = {}


# ------------------------------------------------------------------------------------------ sanitising step

_AGENTS = {"behavioral_anomaly_judge": "behaviour_judge", "pipeline_manager": "case_manager"}


def _clean_value(value: Any) -> Any:
    if isinstance(value, str):
        value = _mask(value)
        return value if len(value) <= HARD_CAP else value[: HARD_CAP - 1] + "…"
    if isinstance(value, (list, tuple)):
        return type(value)(_clean_value(v) for v in value)
    return value


def _enrich_adk(name: str, attrs: dict) -> str:
    """Give Google ADK's own spans the names and fields Langfuse needs to show them as agents and model calls."""
    agent = _AGENTS.get(str(attrs.get("gen_ai.agent.name") or ""), attrs.get("gen_ai.agent.name"))
    model = str(attrs.get("gen_ai.request.model") or "")
    if name.startswith("generate_content") and model:
        bare = model.split("/", 1)[1] if model.startswith("openrouter/") else model
        attrs["langfuse.observation.type"] = "generation"
        attrs["langfuse.observation.model.name"] = bare
        attrs["gen_ai.request.model"] = bare          # Langfuse reads this one first; ADK's carries a provider prefix
        if bare.endswith(":free"):
            attrs["langfuse.observation.cost_details"] = json.dumps({"total": 0.0})     # free tier: the real cost is 0
        tin, tout = attrs.get("gen_ai.usage.input_tokens"), attrs.get("gen_ai.usage.output_tokens")
        if tin is not None and tout is not None:
            from src.usage import reference_cost

            attrs["langfuse.observation.metadata.reference_cost_usd"] = f"{reference_cost(int(tin), int(tout)):.6f}"
        attrs["guardian.agent"] = agent or "adk"
        return f"{agent or 'adk'}.llm"
    if name == "call_llm":
        attrs["langfuse.observation.type"] = "span"          # ADK's wrapper around the real call, not a second call
        return "adk.call_llm"
    if name.startswith("invoke_agent"):
        attrs["langfuse.observation.type"] = "agent"
        attrs["guardian.agent"] = agent or "adk"
        return f"{agent or 'adk'} (ADK)"
    return name


def prepare_span(span: ReadableSpan) -> ReadableSpan:
    """A masked, enriched copy of a finished span. Never mutates the original."""
    attrs = {k: _clean_value(v) for k, v in (span.attributes or {}).items()}
    name = _enrich_adk(span.name, attrs) if "gen_ai.operation.name" in attrs or span.name == "call_llm" else span.name
    events = tuple(Event(e.name, {k: _clean_value(v) for k, v in (e.attributes or {}).items()}, e.timestamp)
                   for e in span.events)
    return ReadableSpan(name=name, context=span.context, parent=span.parent, resource=span.resource,
                        attributes=attrs, events=events, links=span.links, kind=span.kind, status=span.status,
                        start_time=span.start_time, end_time=span.end_time,
                        instrumentation_scope=span.instrumentation_scope)


class SanitizingExporter(SpanExporter):
    """Wraps a real exporter: masks credentials, enriches ADK spans, and keeps count of what got through."""

    def __init__(self, inner: SpanExporter, name: str) -> None:
        self.inner = inner
        self.stats = STATS.setdefault(name, ExportStats(name))

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        try:
            ready = [prepare_span(s) for s in spans]
        except Exception as exc:          # noqa: BLE001 - a bad span must never stop the others being exported
            self.stats.fail(len(spans), f"could not prepare spans: {type(exc).__name__}")
            return SpanExportResult.FAILURE
        try:
            result = self.inner.export(ready)
        except Exception as exc:          # noqa: BLE001
            self.stats.fail(len(ready), f"{type(exc).__name__}: {exc}")
            return SpanExportResult.FAILURE
        if result == SpanExportResult.SUCCESS:
            self.stats.ok(len(ready))
        else:
            self.stats.fail(len(ready), "the destination rejected the batch")
        return result

    def shutdown(self) -> None:
        self.inner.shutdown()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return getattr(self.inner, "force_flush", lambda *_: True)(timeout_millis)


class JsonlSpanExporter(SpanExporter):
    """Appends one JSON line per finished span (the offline provenance record). Rotates by size."""

    def __init__(self, path: Path, max_bytes: Optional[int] = None, backups: int = 3):
        self.path = path
        self.max_bytes = max_bytes if max_bytes is not None else _env_int("GUARDIAN_TRACE_FILE_MAX_MB", 25) * 1024 * 1024
        self.backups = backups
        path.parent.mkdir(parents=True, exist_ok=True)

    def _rotate(self) -> None:
        if not self.path.exists() or self.path.stat().st_size < self.max_bytes:
            return
        for i in range(self.backups, 0, -1):
            src = self.path.with_name(f"{self.path.name}.{i - 1}") if i > 1 else self.path
            dst = self.path.with_name(f"{self.path.name}.{i}")
            if src.exists():
                if dst.exists():
                    dst.unlink()
                src.rename(dst)

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        try:
            with _LOCK:
                self._rotate()
                with self.path.open("a", encoding="utf-8") as fh:
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


# ------------------------------------------------------------------------------------------ configuration

def langfuse_host() -> str:
    """``LANGFUSE_HOST`` (or ``LANGFUSE_BASE_URL``, the name Langfuse's own docs use)."""
    return (os.environ.get("LANGFUSE_HOST") or os.environ.get("LANGFUSE_BASE_URL")
            or "https://cloud.langfuse.com").rstrip("/")


def langfuse_configured() -> bool:
    if os.environ.get("PYTEST_CURRENT_TEST") and not os.environ.get("GUARDIAN_TEST_LANGFUSE"):
        return False         # the test suite must never write fake runs into a real Langfuse project
    return bool(os.environ.get("LANGFUSE_PUBLIC_KEY") and os.environ.get("LANGFUSE_SECRET_KEY"))


def environment() -> str:
    from src.security.public_mode import public_mode

    return os.environ.get("GUARDIAN_ENVIRONMENT") or ("production" if public_mode() else "local")


def sample_ratio() -> float:
    try:
        return min(1.0, max(0.0, float(os.environ.get("GUARDIAN_TRACE_SAMPLE_RATIO", 1))))
    except ValueError:
        return 1.0


def _remote_exporter() -> Optional[SpanExporter]:
    try:
        from opentelemetry.exporter.otlp.proto.http import Compression
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    except Exception:       # exporter package missing: local file only
        return None
    if langfuse_configured():
        token = base64.b64encode(
            f"{os.environ['LANGFUSE_PUBLIC_KEY']}:{os.environ['LANGFUSE_SECRET_KEY']}".encode()).decode()
        return SanitizingExporter(OTLPSpanExporter(
            endpoint=f"{langfuse_host()}/api/public/otel/v1/traces", timeout=10, compression=Compression.Gzip,
            headers={"Authorization": f"Basic {token}", "x-langfuse-ingestion-version": "4"}), "langfuse")
    if os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
        return SanitizingExporter(OTLPSpanExporter(timeout=10, compression=Compression.Gzip), "otlp")
    return None


def _batch(exporter: SpanExporter, delay_ms: Optional[int] = None) -> BatchSpanProcessor:
    return BatchSpanProcessor(exporter, max_queue_size=_env_int("GUARDIAN_TRACE_QUEUE", 4096),
                              schedule_delay_millis=delay_ms or _env_int("GUARDIAN_TRACE_DELAY_MS", 2000),
                              max_export_batch_size=512, export_timeout_millis=15000)


def _resource() -> Resource:
    env = environment()
    version = os.environ.get("GUARDIAN_VERSION", "dev")
    return Resource.create({
        "service.name": "mcp-guardian", "service.version": version,
        "service.instance.id": f"{socket.gethostname()}-{os.getpid()}",
        "deployment.environment": env, "langfuse.environment": env, "langfuse.release": version})


def init_tracing(path: Optional[Path] = None, force: bool = False) -> TracerProvider:
    """Create the process-wide provider once (``force=True`` builds a fresh one, for tests)."""
    global _PROVIDER, _ATEXIT
    with _LOCK:
        if _PROVIDER is not None and not force:
            return _PROVIDER
        ratio = sample_ratio()
        provider = TracerProvider(resource=_resource(),
                                  sampler=ALWAYS_ON if ratio >= 1 else ParentBased(TraceIdRatioBased(ratio)))
        if path is not None or os.environ.get("GUARDIAN_TRACE_FILE", "on").lower() != "off":
            provider.add_span_processor(_batch(SanitizingExporter(JsonlSpanExporter(path or resolve_path("traces")), "file"),
                                               delay_ms=500))
        remote = _remote_exporter()
        if remote is not None:
            if langfuse_configured() and _PROJECT["url"] is None:
                threading.Thread(target=_lookup_project_url, name="langfuse-project", daemon=True).start()
            provider.add_span_processor(_batch(remote))
            log.info("tracing: also exporting to %s", "Langfuse" if langfuse_configured() else "an OTLP endpoint")
        _PROVIDER = provider
        if not force:
            try:      # let Google ADK's own spans land in the same trace store
                trace.set_tracer_provider(provider)
            except Exception:        # a provider was already installed; ours still works directly
                pass
            if not _ATEXIT:
                atexit.register(shutdown_tracing)
                _ATEXIT = True
        return provider


def tracer() -> trace.Tracer:
    return init_tracing().get_tracer("mcp-guardian")


def current_trace_id() -> Optional[str]:
    ctx = trace.get_current_span().get_span_context()
    return f"{ctx.trace_id:032x}" if ctx and ctx.is_valid else None


def flush(timeout_ms: int = 10000) -> None:
    if _PROVIDER is not None:
        _PROVIDER.force_flush(timeout_ms)
    _join_score_threads(timeout_ms / 1000)


def shutdown_tracing() -> None:
    """Send everything still queued, then stop the exporters. Called when the API stops and at interpreter exit."""
    global _PROVIDER
    provider, _PROVIDER = _PROVIDER, None
    _join_score_threads(5)
    if provider is not None:
        try:
            provider.force_flush(10000)
            provider.shutdown()
        except Exception as exc:       # noqa: BLE001
            log.warning("tracing shutdown: %s", exc)


_PROJECT: dict[str, Optional[str]] = {"url": None}


def _lookup_project_url() -> None:
    """Ask Langfuse which project these keys belong to, so the web app can link straight to it. Runs once, in the background."""
    import urllib.request

    url = langfuse_host()
    try:
        token = base64.b64encode(
            f"{os.environ['LANGFUSE_PUBLIC_KEY']}:{os.environ['LANGFUSE_SECRET_KEY']}".encode()).decode()
        req = urllib.request.Request(f"{url}/api/public/projects", headers={"Authorization": f"Basic {token}"})
        data = json.load(urllib.request.urlopen(req, timeout=10)).get("data") or []
        if data:
            url = f"{url}/project/{data[0]['id']}"
    except Exception as exc:       # noqa: BLE001 - the link then goes to Langfuse's home, where the project can be chosen
        log.info("langfuse project lookup failed: %s", exc)
    _PROJECT["url"] = url


def langfuse_project_url() -> Optional[str]:
    """Where to open this app's traces in Langfuse: ``LANGFUSE_PROJECT_URL``, else the project found from the keys,
    else Langfuse's home. ``None`` when Langfuse is not configured. Never makes a network call itself."""
    if not langfuse_configured():
        return None
    explicit = os.environ.get("LANGFUSE_PROJECT_URL", "").strip().rstrip("/")
    return explicit or _PROJECT["url"] or langfuse_host()


def dashboard_link_visible() -> bool:
    """The link is for the owner: shown locally, hidden on a public deployment unless ``GUARDIAN_SHOW_LANGFUSE_LINK=on``."""
    from src.security.public_mode import public_mode

    flag = os.environ.get("GUARDIAN_SHOW_LANGFUSE_LINK", "").strip().lower()
    return flag in ("1", "on", "true", "yes") if flag else not public_mode()


def status() -> dict:
    """For /health: what is configured and whether exports are actually succeeding."""
    return {"file": os.environ.get("GUARDIAN_TRACE_FILE", "on").lower() != "off", "langfuse": langfuse_configured(),
            "dashboard_url": langfuse_project_url() if dashboard_link_visible() else None,
            "environment": environment(), "sample_ratio": sample_ratio(),
            "exports": {name: s.as_dict() for name, s in STATS.items()}}


def hash_user(identifier: str) -> str:
    """A stable, non-reversible visitor id for Langfuse's per-user views (the address itself is never stored)."""
    salt = os.environ.get("GUARDIAN_TRACE_SALT", "mcp-guardian")
    return hashlib.sha256(f"{salt}:{identifier}".encode()).hexdigest()[:16]


# ------------------------------------------------------------------------------------------ security scores

def security_scores(stages: dict[str, dict], final: dict, usage: Any = None) -> list[dict]:
    """Evaluation scores for one run, derived only from what the run itself produced.

    ``stages`` maps stage -> {"status", "engine", "confidence", "reasoning"} for stages that finished;
    ``final`` is the ``done`` event's {"status", "decision", "flagged", "total"}; ``usage`` is the run's
    ``RunUsage`` (model calls, tokens, cost per agent).
    Scores: the decision, a 0-1 risk level (block 1, escalate 0.5, allow 0, inspection with flagged tools 0.5),
    one flag per inspection layer, whether a leaked credential was seen, how much of the inspection the language
    model did rather than the regex fallback, and the run's model usage and cost."""
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
    if usage is not None:
        from src.usage import reference_price_label, reference_cost

        t = usage.totals()
        add("guardian.model_calls", t.calls, "NUMERIC", f"{t.cached} more answers came from the local cache")
        if t.calls:
            add("guardian.tokens_total", t.tokens_in + t.tokens_out, "NUMERIC", f"{t.tokens_in} in, {t.tokens_out} out")
            if t.cost_known:
                add("guardian.cost_usd", round(t.cost_usd, 6), "NUMERIC", "as reported by the provider (0 for free-tier models)")
            add("guardian.reference_cost_usd", round(reference_cost(t.tokens_in, t.tokens_out), 6), "NUMERIC",
                f"estimate: these tokens at {reference_price_label()}")
            for agent, u in usage.agents.items():
                if u.calls:
                    add(f"guardian.tokens.{agent}", u.tokens_in + u.tokens_out, "NUMERIC", f"{u.calls} call(s)")
    return out


_SCORE_THREADS: list[threading.Thread] = []


def _join_score_threads(seconds: float) -> None:
    deadline = time.time() + seconds
    for t in list(_SCORE_THREADS):
        t.join(max(0.0, deadline - time.time()))
    _SCORE_THREADS[:] = [t for t in _SCORE_THREADS if t.is_alive()]


def send_scores(trace_id: str, scores: list[dict]) -> None:
    """Post scores to Langfuse in the background (retried, never raising). A no-op unless Langfuse is configured."""
    if not (langfuse_configured() and scores):
        return
    stats = STATS.setdefault("langfuse_scores", ExportStats("langfuse_scores"))

    def work() -> None:
        import urllib.request

        token = base64.b64encode(
            f"{os.environ['LANGFUSE_PUBLIC_KEY']}:{os.environ['LANGFUSE_SECRET_KEY']}".encode()).decode()
        for sc in scores:
            body = json.dumps({**sc, "traceId": trace_id, "id": f"{trace_id}-{sc['name']}"}).encode()
            req = urllib.request.Request(f"{langfuse_host()}/api/public/scores", data=body, method="POST",
                                         headers={"Authorization": f"Basic {token}", "Content-Type": "application/json"})
            for attempt in range(3):
                try:
                    urllib.request.urlopen(req, timeout=20).read()
                    stats.ok(1)
                    break
                except Exception as exc:      # noqa: BLE001 - scoring must never affect a run
                    if attempt == 2:
                        stats.fail(1, f"{sc['name']}: {type(exc).__name__}")
                    else:
                        time.sleep(1.5 * (attempt + 1))

    t = threading.Thread(target=work, name="langfuse-scores", daemon=True)
    _SCORE_THREADS.append(t)
    t.start()
