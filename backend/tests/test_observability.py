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
