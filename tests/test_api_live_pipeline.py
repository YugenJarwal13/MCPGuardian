"""Task 6 backend — the WebSocket streams real pipeline stages.

Uses the in-process fixture servers (no DVMCP lab, no LLM key needed); the app's
lifespan still starts the real A2A case-manager server, so the a2a_hop stage
is a genuine HTTP hop here too.
"""
from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from src.api.main import app  # noqa: E402


def _run(client, server_id, approvals=(), **req):
    events, approvals = [], list(approvals)
    with client.websocket_connect("/ws/run") as ws:
        ws.send_json({"server_id": server_id, "use_llm": False, **req})
        while True:
            ev = ws.receive_json()
            events.append(ev)
            if ev["status"] == "escalate":
                ws.send_json({"type": "approval", "approved": approvals.pop(0)})
            if ev["stage"] == "done":
                return events


def _final(events, stage):
    return [e for e in events if e["stage"] == stage and e["status"] != "started"][-1]


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_servers_lists_clean_and_poisoned(client):
    body = client.get("/servers").json()
    assert {s["id"] for s in body["clean"]} >= {"demo-clean"}
    ch2 = next(s for s in body["poisoned"] if s["id"] == "dvmcp-ch2")
    assert ch2["port"] == 9002 and isinstance(ch2["live"], bool)


def test_clean_server_all_green_and_started_before_result(client):
    events = _run(client, "demo-clean")
    stages = [e["stage"] for e in events]
    for s in ("static_check", "runtime_check", "a2a_hop"):
        assert stages.index(s) < len(stages)
        assert events[stages.index(s)]["status"] == "started"   # emitted before the result
    assert all(_final(events, s)["status"] == "passed" for s in
               ("connect", "list_tools", "static_check", "tool_call", "runtime_check",
                "behavioral_check", "a2a_hop", "enforcement", "done"))
    assert _final(events, "done")["message"] == "ALLOW"
    assert _final(events, "static_check")["engine"] == "heuristic"
    assert _final(events, "a2a_hop")["detail"]["case_decision"] == "allow"


def test_tricky_clean_data_stays_clean(client):
    events = _run(client, "demo-clean-changelog")
    assert _final(events, "runtime_check")["status"] == "passed"
    assert _final(events, "done")["message"] == "ALLOW"


def test_poisoned_response_flagged_after_the_call(client):
    events = _run(client, "demo-poisoned-response")
    assert _final(events, "static_check")["status"] == "passed"
    assert any(e["stage"] == "tool_call" and e["status"] == "passed" for e in events)
    rt = _final(events, "runtime_check")
    assert rt["status"] == "flagged" and rt["detail"]["flagged_phrases"]
    assert _final(events, "enforcement")["status"] == "blocked"


def test_poisoned_metadata_blocked_before_execution(client):
    events = _run(client, "demo-poisoned-metadata")
    assert _final(events, "static_check")["status"] == "flagged"
    assert not any(e["status"] == "escalate" for e in events)   # malicious never escalates
    assert _final(events, "tool_call")["status"] == "blocked"
    assert _final(events, "runtime_check")["detail"] == {"skipped": True}
    assert _final(events, "done")["message"] == "BLOCK"


@pytest.mark.parametrize("approved", [True, False])
def test_escalation_roundtrips_human_choice_over_websocket(client, approved):
    # A clean tool with a filesystem_write scope must be approved by a human.
    client.post("/servers/demo-notes-writer/reset")
    events = _run(client, "demo-notes-writer", approvals=[approved])
    assert any(e["stage"] == "tool_call" and e["status"] == "escalate" for e in events)
    executed = any(e["stage"] == "tool_call" and e["message"].startswith("Tool executed")
                   for e in events)
    assert executed is approved
    assert (_final(events, "done")["status"] == "passed") is approved
