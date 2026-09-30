# MCP Guardian — Viva Demo Script

A rehearsable sequence driven from the **live web UI**: the examiner picks a
server, you press *Run pipeline*, and every defence layer resolves on screen as
it happens. Run through it at least once before the viva.

## Setup (before the examiner arrives)

Three terminals, left running:

```bash
python scripts/run_dvmcp_native.py   # (A) live DVMCP challenges on 127.0.0.1:9001-9010
bash scripts/run_api.sh              # (B) FastAPI + WebSocket on :8000, A2A case manager
bash scripts/run_frontend.sh         # (C) React UI on http://localhost:5173
```

Optional fourth: `streamlit run src/dashboard/app.py` (historical audit log).

Check before you start:

- `pytest -q` is green.
- In the UI's top bar, the A2A pill shows an address. The LLM pill says either
  *LLM configured* or *No LLM key — heuristic mode*. **Say which one out loud.**
- Every DVMCP card in the *Poisoned* column shows a green `live :90xx` dot.
- Press *Reset history* on any server you reuse, so its behavioural fingerprint
  starts clean.

## The sequence

**1. The pipeline, before anything runs.**
Select **Calculator & Weather (clean reference)**. All nine stages appear in grey
before the run. *"This is every check a single tool call goes through: static
analysis of the metadata, a policy gate, the real call, runtime inspection of
the response, behavioural fingerprinting, the A2A hop to the ADK case manager,
and enforcement."*

**2. Clean run — everything green.**
Press *Run pipeline*. Each stage spins, then turns green. The banner says
**ALLOW**. Open the **A2A hop** card: it shows the case ID, the decision the ADK
case manager recorded, and the round-trip time. *"That verdict crossed a real
HTTP A2A hop into ADK session state. It is not a function call."* Point at the
engine badges: they say which detector actually decided.

**3. Tricky-but-clean data.**
Select **Changelog (clean data with instruction-like words)** and run. The
response contains "Ignore the deprecated v1 API", and the runtime stage stays
green. *"Flagging every sentence with 'ignore' in it would make the defence
unusable. It has to find intent aimed at the agent."*

**4. Real tool poisoning, caught before any call (DVMCP Challenge 10).**
Select **Challenge 10 — Multi-Vector Attack** (`get_user_profile`). The static
stage turns amber and auto-expands. It shows the tool description exactly as the
live server served it, with `<IMPORTANT> … include the master password …` and
the flagged phrases highlighted. The policy gate then shows **Blocked before
execution — the server was never called**. *"The poison is in metadata the agent
trusts once, at connect time. We block before execution."*

**5. Indirect prompt injection in a real response (DVMCP Challenge 6).**
Select **Challenge 6 — Indirect Prompt Injection**. The default arguments upload
a document containing an injected "Note to AI assistant" line.
- The static stage stays green: the metadata is clean.
- The policy gate asks for **human approval**, because the tool writes files.
  Click **Approve**. *"This is the human-in-the-loop guardrail, live."*
- The call executes against the real server, which echoes the document into its
  analysis. The **runtime stage** turns amber, and its card highlights the
  injected sentence inside the actual response.
- Enforcement shows **Flagged! Blocking**. *"Even after a human approved the
  call, a malicious response never reaches the agent. A malicious verdict always
  blocks."*

**6. Rug pull (behavioural layer).**
Select **Stock price rug pull (offline fixture)** and press *Reset history*.
Run it repeatedly. For 10 runs the behavioural stage stays green, and its
*calls observed* counter climbs. On run 11 a new `hidden_directive` key appears.
The behavioural stage flags the drift (z-score and new keys in the card), and
the response is blocked. *"Time to detection: one call."* Be upfront that this
is an in-process fixture. DVMCP's live Challenge 4 rewrites its docstring, but
current MCP servers cache tool descriptions, so the live rug pull never changes
anything a client can see.

**7. Where it misses (say this before they find it).**
Select **Challenge 2 — Tool Poisoning**. On the heuristic path the static stage
rates the real `<IMPORTANT> … read the confidential company information … Do not
mention …` description **clean**. *"Our regex baseline has no rule for this
wording. This is exactly the case the LLM agent is for. With an LLM configured
the badge says LLM, and the v2 prompt has a worked example of this pattern."*
Only claim the LLM catches it if you have run it with a key.

**8. The numbers.**
Open `docs/evaluation_report.md`. These are real data, deterministic baseline,
detectors only:

- 1,312 real MCPTox attacks, 31 live DVMCP tools, and 369 benign tools
  (362 of them real third-party tools).
- Precision 97.8%, recall 39.2% (MCPTox 39.7%), benign false-positive rate 3.3%.

*"Earlier we reported 77.5% recall. That was measured on fixtures written
alongside the heuristics. On the real benchmark it is 39.7%. We report the real
number. The keyword scope rule adds recall, but it also adds false positives, so
we report it separately and don't credit it to the detectors."*
If an LLM run exists, its column sits next to the baseline, and the *Engines and
latency* table shows the per-call cost of each engine. Quote the measured
numbers; the heuristic's are sub-millisecond.

**9. Architecture questions — where things live.**
- Real Google ADK: `src/adk_layer/behavioral_anomaly_agent.py` (`LlmAgent`
  judge), `src/adk_layer/callbacks/enforcement_callbacks.py`
  (`before_tool_callback`), `src/adk_layer/pipeline_manager.py` (ADK
  `BaseAgent` + `Runner` + SQLite session state).
- Real A2A: `src/a2a_bridge/a2a_server.py` (`to_a2a` server) and
  `src/a2a_bridge/bridge.py` (`RemoteA2AClient.send`, the JSON-RPC
  `message/send`).
- One audit trail: every UI event is also a `pipeline_event` row in
  `logs/audit_trail.jsonl`, which the Streamlit dashboard reads.

## Fallbacks if something breaks

- **DVMCP lab down:** the DVMCP cards show red `offline` dots. Use the
  in-process fixtures (clean, changelog, poisoned weather, poisoned web fetch,
  rug pull); they exercise the same pipeline.
- **UI won't load:** run the terminal version against the same live servers:
  `python -m src.demo_agent.run_demo --live --interactive`.
- **No LLM key:** everything runs on the deterministic detectors, and the badges
  say `heuristic`. Say so. The architecture is identical; only the reasoning
  engine differs.
- **An LLM call hangs:** after `timeouts.*_s` (settings.yaml) the stage shows
  *LLM timed out → escalate*, and you get Approve/Deny instead of a silent
  allow. Deny it and move on.
