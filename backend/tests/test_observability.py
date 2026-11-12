"""Tracing + callback monitoring: one trace per run, a span per stage, model calls nested under stages."""
import asyncio
import json

from src.api.events import EventEmitter
from src.observability import init_tracing, tracer
from src.monitoring import crew_task_callback, record_error


def _spans(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_run_is_one_trace_with_a_span_per_stage(tmp_path):
    path = tmp_path / "traces.jsonl"
    provider = init_tracing(path=path, force=True)
    import src.observability as obs
    sent = []

    async def send(payload):
        sent.append(payload)

    async def go():
        em = EventEmitter("run1", send, "srv", "tool")
        await em.emit("static_check", "started", "reading…")
        with tracer().start_as_current_span("llm.complete"):      # as the chain does mid-stage
            pass
        await em.emit("static_check", "flagged", "bad", {"verdict": "malicious", "confidence": 0.9,
                      "reasoning": "hidden order", "flagged_phrases": ["x"]}, "llm", {"model": "m", "provider": "p"})
        await em.emit("done", "blocked", "BLOCK", {"final_decision": "block"})
        em.finish()
        return em

    em = asyncio.run(go())
    provider.force_flush()
    spans = _spans(path)
    by_name = {s["name"]: s for s in spans}
    assert {"guardian.run", "guardian.static_check", "llm.complete"} <= set(by_name)
    assert len({s["trace_id"] for s in spans}) == 1                      # one trace
    assert by_name["guardian.static_check"]["parent_id"] == by_name["guardian.run"]["span_id"]
    assert by_name["llm.complete"]["parent_id"] == by_name["guardian.static_check"]["span_id"]
    assert by_name["guardian.static_check"]["attributes"]["guardian.verdict"] == "malicious"
    assert all(e["trace_id"] == em.trace_id for e in sent)               # events carry the trace id
    obs._PROVIDER = None


def test_unfinished_run_is_closed_by_finish(tmp_path):
    path = tmp_path / "t.jsonl"
    provider = init_tracing(path=path, force=True)

    async def go():
        em = EventEmitter("r2", lambda p: asyncio.sleep(0), "srv")
        await em.emit("connect", "started", "connecting")
        em.finish()
        em.finish()          # idempotent

    asyncio.run(go())
    provider.force_flush()
    names = [s["name"] for s in _spans(path)]
    assert names.count("guardian.connect") == 1 and names.count("guardian.run") == 1
    import src.observability as obs
    obs._PROVIDER = None


def test_callbacks_write_to_audit_trail_and_never_raise(tmp_path, monkeypatch):
    from src import audit, monitoring
    logged = []
    monkeypatch.setattr(monitoring, "log_decision", lambda rec, path=None: logged.append(rec))

    class Out:
        pydantic = type("P", (), {"verdict": "clean", "confidence": 0.8})()
        raw = "{}"
    crew_task_callback("Auditor")(Out())
    record_error("crewai", "static", RuntimeError("boom"))
    monitoring.adk_after_model(None, llm_response=None)       # odd inputs must not raise
    monitoring.adk_on_model_error(callback_context=None, llm_request=None, error=ValueError("x"))
    events = {(r["layer"], r["event"]) for r in logged}
    assert ("crewai_callback", "task_finished") in events
    assert ("error", "crewai_error") in events
    assert ("adk_callback", "after_model") in events and ("error", "adk_model_error") in events


def _fake_chain(tmp_path, cost):
    from src.llm_chain import ChainLLM, Slot

    def transport(slot, payload, timeout):
        text = json.dumps({"verdict": "clean", "confidence": 0.9, "reasoning": "ok", "flagged_phrases": []})
        usage = {"prompt_tokens": 11, "completion_tokens": 5, **({"cost": cost} if cost is not None else {})}
        return 200, {}, {"choices": [{"message": {"content": text}}], "usage": usage}

    return ChainLLM(slots=[Slot("openrouter", "vendor/model-x", "response_format")], transport=transport,
                    rpm=6000, use_cache=True, cache_path=tmp_path / "cache.jsonl")


def test_model_call_is_a_langfuse_generation_with_model_usage_and_cost(tmp_path):
    path = tmp_path / "t.jsonl"
    provider = init_tracing(path=path, force=True)
    chain = _fake_chain(tmp_path, cost=0.00042)
    chain.complete("system prompt", "user prompt")
    chain.complete("system prompt", "user prompt")          # second call is served from the cache
    provider.force_flush()
    first, second = [s for s in _spans(path) if s["name"] == "llm.complete"]
    a = first["attributes"]
    assert a["langfuse.observation.type"] == "generation"
    assert a["langfuse.observation.model.name"] == "vendor/model-x"
    assert json.loads(a["langfuse.observation.usage_details"]) == {"input": 11, "output": 5, "total": 16}
    assert json.loads(a["langfuse.observation.cost_details"]) == {"total": 0.00042}
    assert "system prompt" in a["input.value"] and "user prompt" in a["input.value"]
    b = second["attributes"]                                 # a cache hit books no model usage and no cost
    assert b["guardian.cached"] is True and b["langfuse.observation.type"] == "span"      # not a model call
    assert "langfuse.observation.usage_details" not in b and "langfuse.observation.cost_details" not in b
    import src.observability as obs
    obs._PROVIDER = None


def test_security_scores_describe_the_run():
    from src.observability import security_scores

    stages = {"static_check": {"status": "flagged", "engine": "llm", "reasoning": "hidden order"},
              "runtime_check": {"status": "flagged", "engine": "heuristic_fallback",
                                "reasoning": "Credential scan: the response contains JSON web token"},
              "behavioral_check": {"status": "passed", "engine": "none"}}
    got = {s["name"]: s for s in security_scores(stages, {"status": "blocked", "decision": "block"})}
    assert got["guardian.decision"]["value"] == "block" and got["guardian.risk"]["value"] == 1.0
    assert got["guardian.static_flagged"]["value"] == 1 and got["guardian.behavioral_flagged"]["value"] == 0
    assert got["guardian.credential_leak"]["value"] == 1
    assert got["guardian.llm_coverage"]["value"] == 0.5          # one of two inspection stages used the model
    insp = {s["name"]: s["value"] for s in security_scores({}, {"status": "passed", "decision": None, "total": 3, "flagged": 0})}
    assert insp == {"guardian.decision": "inspection_clean", "guardian.risk": 0.0}
