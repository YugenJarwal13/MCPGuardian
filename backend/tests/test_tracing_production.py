"""Production behaviour of the tracing: masking, ADK enrichment, rotation, export health, sampling, trace
propagation across the A2A hop, per-agent usage and the scores built from it. No network; Langfuse is never contacted."""
from __future__ import annotations

import asyncio
import json

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SpanExportResult

import src.observability as obs
from src.observability import init_tracing, prepare_span, tracer
from src.usage import CURRENT_AGENT, RUN_USAGE, RunUsage

LEAK = "api key: epro_api_5f4e3d2c1b0a9z8y7x and eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.5TxfEAVbZRGbKnXaL9Lrx9NqXSNFw2ac"


@pytest.fixture()
def provider(tmp_path):
    path = tmp_path / "t.jsonl"
    p = init_tracing(path=path, force=True)
    yield p, path
    p.shutdown()
    obs._PROVIDER = None


def _spans(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _finished(name, attrs=None):
    """One real finished span, captured through an in-memory processor."""
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    mem = InMemorySpanExporter()
    tp = TracerProvider()
    tp.add_span_processor(SimpleSpanProcessor(mem))
    with tp.get_tracer("t").start_as_current_span(name) as sp:
        for k, v in (attrs or {}).items():
            sp.set_attribute(k, v)
        sp.add_event("exception", {"exception.message": f"failed calling https://x.test/mcp?apikey=abcd1234efgh5678"})
    return mem.get_finished_spans()[0]


def test_credentials_are_masked_in_every_attribute_and_event():
    span = prepare_span(_finished("mcp.call_tool", {"output.value": LEAK, "guardian.tool_name": "t"}))
    dumped = json.dumps(dict(span.attributes)) + json.dumps([dict(e.attributes) for e in span.events])
    assert "epro_api_5f4e3d2c1b0a9z8y7x" not in dumped and "eyJhbGciOiJIUzI1NiIs" not in dumped
    assert "abcd1234efgh5678" not in dumped
    assert span.attributes["guardian.tool_name"] == "t"               # ordinary values are untouched


def test_adk_spans_get_agent_names_types_model_and_free_cost():
    gen = prepare_span(_finished("generate_content openrouter/dots-studio/dots-3-note-preview:free", {
        "gen_ai.operation.name": "generate_content", "gen_ai.agent.name": "behavioral_anomaly_judge",
        "gen_ai.request.model": "openrouter/dots-studio/dots-3-note-preview:free",
        "gen_ai.usage.input_tokens": 345, "gen_ai.usage.output_tokens": 400}))
    a = gen.attributes
    assert gen.name == "behaviour_judge.llm"
    assert a["langfuse.observation.type"] == "generation"
    assert a["langfuse.observation.model.name"] == "dots-studio/dots-3-note-preview:free"
    assert a["gen_ai.request.model"] == "dots-studio/dots-3-note-preview:free"
    assert json.loads(a["langfuse.observation.cost_details"]) == {"total": 0.0}
    assert float(a["langfuse.observation.metadata.reference_cost_usd"]) > 0

    wrapper = prepare_span(_finished("call_llm", {"gen_ai.request.model": "x"}))
    assert wrapper.name == "adk.call_llm" and wrapper.attributes["langfuse.observation.type"] == "span"

    agent = prepare_span(_finished("invoke_agent pipeline_manager", {
        "gen_ai.operation.name": "invoke_agent", "gen_ai.agent.name": "pipeline_manager"}))
    assert agent.name == "case_manager (ADK)" and agent.attributes["langfuse.observation.type"] == "agent"

    plain = prepare_span(_finished("guardian.run", {"guardian.run_id": "r"}))
    assert plain.name == "guardian.run"


def test_the_trace_file_rotates_instead_of_growing_forever(tmp_path):
    path = tmp_path / "t.jsonl"
    exporter = obs.JsonlSpanExporter(path, max_bytes=2000, backups=2)
    span = _finished("s", {"x": "y" * 300})
    for _ in range(40):
        assert exporter.export([span]) == SpanExportResult.SUCCESS
    names = sorted(p.name for p in tmp_path.iterdir())
    assert "t.jsonl.1" in names and "t.jsonl.2" in names and "t.jsonl.3" not in names
    assert path.stat().st_size < 2600


def test_export_failures_are_counted_and_never_raise():
    class Broken:
        def export(self, spans):
            raise ConnectionError("langfuse unreachable")

        def shutdown(self):
            pass

    ex = obs.SanitizingExporter(Broken(), "unit_broken")
    assert ex.export([_finished("s")]) == SpanExportResult.FAILURE
    st = obs.STATS["unit_broken"]
    assert st.failed == 1 and "unreachable" in st.last_error

    class Fine(Broken):
        def export(self, spans):
            return SpanExportResult.SUCCESS

    ok = obs.SanitizingExporter(Fine(), "unit_fine")
    assert ok.export([_finished("s"), _finished("t")]) == SpanExportResult.SUCCESS
    assert obs.STATS["unit_fine"].exported == 2 and obs.STATS["unit_fine"].last_error is None


def test_sampling_ratio_zero_traces_nothing_and_file_can_be_switched_off(monkeypatch, tmp_path):
    monkeypatch.setenv("GUARDIAN_TRACE_SAMPLE_RATIO", "0")
    p = init_tracing(path=tmp_path / "t.jsonl", force=True)
    assert not p.get_tracer("x").start_span("dropped").is_recording()
    monkeypatch.setenv("GUARDIAN_TRACE_SAMPLE_RATIO", "1")
    p.shutdown()
    monkeypatch.setenv("GUARDIAN_TRACE_FILE", "off")
    p2 = init_tracing(force=True)
    assert not p2._active_span_processor._span_processors          # no file, no exporter: nothing to write to
    p2.shutdown()
    obs._PROVIDER = None
    assert obs.status()["file"] is False


def test_the_test_suite_never_counts_as_a_langfuse_environment(monkeypatch):
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-x")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-x")
    assert obs.langfuse_configured() is False


def test_model_calls_are_traced_under_their_agent_and_summed_per_run(provider):
    from src.llm_chain import ChainLLM, Slot

    p, path = provider
    n = {"calls": 0}

    def transport(slot, payload, timeout):
        n["calls"] += 1
        text = json.dumps({"verdict": "clean", "confidence": 0.9, "reasoning": "ok", "flagged_phrases": []})
        return 200, {}, {"choices": [{"message": {"content": text}}],
                         "usage": {"prompt_tokens": 100, "completion_tokens": 50, "cost": 0.002}}

    chain = ChainLLM(slots=[Slot("openrouter", "vendor/m", "response_format")], transport=transport, rpm=6000,
                     use_cache=True, cache_path=path.parent / "c.jsonl")
    usage = RunUsage()
    RUN_USAGE.set(usage)
    token = CURRENT_AGENT.set("static_analysis")
    try:
        chain.complete("s", "u")
        chain.complete("s", "u")                    # served from the cache
    finally:
        CURRENT_AGENT.reset(token)
    p.force_flush()
    fresh, cached = [s for s in _spans(path) if s["name"] == "static_inspector.llm"]
    assert fresh["attributes"]["langfuse.observation.type"] == "generation"
    assert cached["attributes"]["langfuse.observation.type"] == "span"           # not counted as a model call
    u = usage.agents["static_inspector"]
    assert (u.calls, u.cached, u.tokens_in, u.tokens_out) == (1, 1, 100, 50)
    assert abs(u.cost_usd - 0.002) < 1e-9 and n["calls"] == 1


def test_scores_include_model_usage_cost_and_reference_cost():
    from src.observability import security_scores

    usage = RunUsage()
    usage.add("static_inspector", {"tokens": {"prompt": 1000, "completion": 500}, "cost_usd": 0.0})
    usage.add("runtime_inspector", {"tokens": {"prompt": 2000, "completion": 1000}, "cost_usd": 0.0})
    usage.add("runtime_inspector", {"cached": True})
    got = {s["name"]: s for s in security_scores({}, {"status": "passed", "decision": "allow"}, usage)}
    assert got["guardian.model_calls"]["value"] == 2 and "1 more answers came from the local cache" in got["guardian.model_calls"]["comment"]
    assert got["guardian.tokens_total"]["value"] == 4500
    assert got["guardian.cost_usd"]["value"] == 0.0                       # what the provider reported
    assert got["guardian.reference_cost_usd"]["value"] == pytest.approx(3000 / 1e6 * 0.30 + 1500 / 1e6 * 1.20, abs=1e-6)
    assert got["guardian.tokens.static_inspector"]["value"] == 1500 and got["guardian.tokens.runtime_inspector"]["value"] == 3000
    local = RunUsage()
    local.add("static_inspector", {"tokens": {"prompt": 10, "completion": 5}})        # a local model reports no cost
    names = {s["name"] for s in security_scores({}, {"status": "passed", "decision": "allow"}, local)}
    assert "guardian.cost_usd" not in names and "guardian.reference_cost_usd" in names


def test_trace_context_crosses_the_a2a_hop(provider):
    """The case manager's spans must join the run's trace: caller injects, the ASGI middleware adopts."""
    from opentelemetry.propagate import inject

    from src.a2a_bridge.a2a_server import TraceContextMiddleware

    seen = {}

    async def app(scope, receive, send):
        seen["trace_id"] = trace.get_current_span().get_span_context().trace_id

    with tracer().start_as_current_span("guardian.a2a_hop") as hop:
        headers = {}
        inject(headers)
        want = hop.get_span_context().trace_id
    scope = {"type": "http", "headers": [(k.encode(), v.encode()) for k, v in headers.items()]}
    asyncio.run(TraceContextMiddleware(app)(scope, None, None))
    assert seen["trace_id"] == want
    asyncio.run(TraceContextMiddleware(app)({"type": "http", "headers": []}, None, None))      # no header: still fine


def test_a_pipeline_run_traces_the_mcp_call_the_visitor_and_the_run_usage(tmp_path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from src.api.main import app

    path = tmp_path / "t.jsonl"
    init_tracing(path=path, force=True)
    with TestClient(app) as client:
        with client.websocket_connect("/ws/run") as ws:
            ws.send_json({"server_id": "demo-clean", "tool_name": "calculator",
                          "arguments": {"expression": "2+2"}, "use_llm": False})
            try:
                while True:
                    ws.receive_json()
            except Exception:
                pass
    obs._PROVIDER = None
    spans = _spans(path)
    by = {s["name"]: s for s in spans}
    call = by["mcp.call_tool"]["attributes"]
    assert call["langfuse.observation.type"] == "tool" and "2+2" in call["input.value"] and call["output.value"]
    assert by["mcp.tools_list"]["attributes"]["guardian.tool_count"] >= 1
    root = by["guardian.run"]["attributes"]
    assert root["langfuse.observation.type"] == "chain"
    assert "calculator" in root["langfuse.trace.input"] and "decision" in root["langfuse.trace.output"]
    assert root["langfuse.user.id"] and "testclient" not in root["langfuse.user.id"]      # hashed, never the address
    assert json.loads(root["langfuse.trace.metadata.usage"]) == {}                         # no model calls in this run
    assert by["guardian.tool_call"]["attributes"]["langfuse.observation.type"] == "tool"
    assert by["guardian.static_check"]["attributes"]["langfuse.observation.type"] == "guardrail"
    assert len({s["trace_id"] for s in spans}) == 1                                        # the whole run is one trace


def test_the_langfuse_dashboard_link_is_for_the_owner(monkeypatch):
    monkeypatch.delenv("GUARDIAN_SHOW_LANGFUSE_LINK", raising=False)
    monkeypatch.delenv("GUARDIAN_PUBLIC", raising=False)
    assert obs.dashboard_link_visible() is True                      # local: shown
    monkeypatch.setenv("GUARDIAN_PUBLIC", "1")
    assert obs.dashboard_link_visible() is False                     # a public deployment: hidden by default
    monkeypatch.setenv("GUARDIAN_SHOW_LANGFUSE_LINK", "on")
    assert obs.dashboard_link_visible() is True                      # unless the owner opts in
    monkeypatch.setenv("GUARDIAN_SHOW_LANGFUSE_LINK", "off")
    monkeypatch.delenv("GUARDIAN_PUBLIC")
    assert obs.dashboard_link_visible() is False


def test_the_project_link_prefers_the_configured_address_and_needs_langfuse(monkeypatch):
    assert obs.langfuse_project_url() is None                        # not configured under the test suite
    monkeypatch.setenv("GUARDIAN_TEST_LANGFUSE", "1")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-x")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-x")
    monkeypatch.setenv("LANGFUSE_PROJECT_URL", "https://example.test/project/abc/")
    assert obs.langfuse_project_url() == "https://example.test/project/abc"
    monkeypatch.delenv("LANGFUSE_PROJECT_URL")
    obs._PROJECT["url"] = None
    assert obs.langfuse_project_url() == obs.langfuse_host()          # nothing looked up yet: Langfuse's home
    assert obs.status()["dashboard_url"] is not None
