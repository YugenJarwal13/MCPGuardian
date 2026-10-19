# MCP Guardian — Viva Demo Script

A rehearsable sequence driven from the **live web UI**. The examiner picks a server, you press
*Run pipeline*, and every defence layer resolves on screen as it happens. Run through it once
before the viva. Light theme is the default; the moon/sun button in the nav switches themes and
remembers your choice (use dark if the room is dim).

## Setup (before the examiner arrives)

Three terminals, left running:

```bash
python backend/scripts/run_dvmcp_native.py   # (A) live DVMCP challenges on 127.0.0.1:9001-9010
bash backend/scripts/run_api.sh              # (B) FastAPI + WebSocket on :8000, A2A case manager
bash backend/scripts/run_frontend.sh         # (C) React UI on http://localhost:5173
```

Optional fourth: `streamlit run backend/src/dashboard/app.py` (historical audit log).

Check before you start:

- `pytest -q` is green.
- In the top bar, the model pill names the configured LLM (for example *openrouter · dots-3-note-preview*)
  and the A2A pill shows the case-manager address. **Say out loud which engine you are demoing.**
- **Mind the quota.** The OpenRouter key is on the free tier: **50 requests a day**. A full pipeline run
  with LLM agents costs one request per tool inspected plus one for the response, so budget roughly
  **8–10 live LLM runs per day**. When the quota is gone the badge reads *LLM failed → heuristic* (or the chain
  falls through to the local model, which takes about a minute per call) — switch *Use LLM agents* off and
  say so, or add credits.
- Every DVMCP card shows a green `live · :90xx` dot.
- Press *Reset history* on any server you reuse so its behavioural fingerprint starts clean.

## The sequence

**1. The pipeline, before anything runs.** Select **Calculator & Weather (clean reference)**. All nine
stages sit in grey. *"Every check a single tool call goes through: static analysis of the metadata, a
policy gate, the real call, runtime inspection of the response, behavioural fingerprinting, an A2A hop to
the ADK case manager, and enforcement."*

**2. Clean run, everything green.** Run it. Each stage types its status ("Static analysis (CrewAI) running…"),
a timer ticks, then the node draws a check. The banner says **ALLOW**. Open the **A2A hop** card: case ID,
the decision the ADK case manager recorded, the round-trip time. *"That verdict crossed a real HTTP A2A hop
into ADK session state."* Point at the engine badges: they name the model that decided.

**3. Tricky-but-clean data.** Select **Changelog (clean data with instruction-like words)** and run. The
response says "Ignore the deprecated v1 API"; the runtime stage stays green. *"Flagging every sentence with
'ignore' in it would make a defence unusable. It has to find intent aimed at the agent."*

**4. Real tool poisoning, caught before any call (DVMCP Challenge 10).** Select **Challenge 10** (the default
tool is `get_user_profile`). The static stage turns amber and opens by itself: the description exactly as the
live server served it, with the `<IMPORTANT> … include the master password … Do not mention …` block, the
flagged phrases highlighted, the model's reasoning and confidence. The gate then reports **Blocked before
execution — the server was never called**.

**5. Indirect prompt injection in a real response (DVMCP Challenge 6).** Select **Challenge 6**. The default
arguments upload a document containing an injected "Note to AI assistant" line.
- The static stage stays green: the metadata is clean.
- The tool has no path, URL, command or secret parameter, so the **schema-based policy lets it run** with no
  human approval (a keyword rule would have escalated it for the word "upload").
- The call executes on the real server, which echoes the document back. The **runtime stage** turns amber
  and highlights the injected sentence inside the actual response.
- Enforcement shows **Flagged! Blocking**. *"A malicious verdict always blocks."*

**6. The human in the loop.** Select **Poisoned web fetch (offline fixture)**. Its `url` parameter is
genuine network access, so the policy stops at an inline **Your decision** panel (not a popup): *Approve*,
and the response is still caught afterwards; run it again and press *Deny*, and the tool never executes.
Select **Notes writer** for the clean-but-sensitive case: a clean tool with `path` + `content` always needs a
human.

**7. Rug pull (behavioural layer).** Select **Stock price rug pull (offline fixture)** and press *Reset
history*. Run it repeatedly. For ten runs the behavioural stage stays green while *calls observed* climbs. On
run 11 a new `hidden_directive` key appears, the stage flags the drift (z-score and new keys in the card) and
the response is blocked: *"time to detection, one call."* Say it is an in-process fixture: DVMCP Challenge 4's
live rug pull rewrites a docstring that current MCP servers cache, so it never changes anything a client
can see.

**8. Test any server live (the second page).** Open **Test a server live**. Click the *DVMCP Challenge 2*
example and press *Run Guardian*. The Guardian connects, statically inspects **every** tool the server offers
(no tool is called), and shows a verdict table. Stages that were deliberately not run are shown as
*Not run in this mode*. Pick a tool and *Call through Guardian* to run the whole pipeline on it.
Be upfront that this is the basic version: no stdio servers, no authentication, no multi-call sessions.

**9. Challenge 2: why the LLM layer exists.** Still on the live page, run Challenge 2 twice: once with
*Use LLM agents* **off**, once **on**.
- Heuristic: `get_company_data` → **clean**. Its regexes have no rule for the `<IMPORTANT> … read the
  confidential company information … Do not mention …` wording.
- LLM (CrewAI → dots-3-note-preview): `get_company_data` → **malicious (confidence 1.0)**. This is a measured
  result from the real pipeline, recorded in `docs/evaluation_report.md` (DVMCP Challenge 2 table).
*"We left the heuristic unpatched on purpose. Adding a rule that makes it catch the demo would be tuning on
the test set."*

**10. The numbers.** Open `docs/evaluation_report.md`. State them with their sample sizes and intervals:

- **Regex baseline, full real data (1,762 cases):** precision 96.9%, recall 39.1%, MCPTox recall 39.7%; on the
  hand-written response cases it catches 10 of 29 injections and falsely flags 5 of 12 hard negatives.
- **Local LLM (CrewAI + Ollama qwen3:4b), 70 balanced cases:** precision **100%**, recall **63.6%** (regex on the same
  cases 76.5% / 39.4%); **0 of 11** hard negatives flagged (regex 4 of 11); **10 of 11** response injections caught
  (regex 5 of 11).
- **MCPTox, held out (never in any prompt), 50 cases:** LLM **62.0%** (95% CI 48–74%) vs regex **34.0%** on the same
  cases (39.7% over all 1,312).
- **Hosted LLM (OpenRouter dots-3-note-preview), 42 cases (stopped by the free-tier 50 requests/day cap):** recall
  73.7%, precision 87.5% (regex on the same cases 42.1% / 80.0%); 0 of 6 hard negatives flagged (regex 2 of 6).
- **Cost:** hosted median ~11 s per model call, local CPU median ~67 s (p95 ~162 s), regex under a millisecond.
- **Prompt v2 did not beat v1** on either model (28 identical cases each: local one case each way; hosted recall
  83.3% for both) — say so if asked.
- **Challenge 2** is flagged malicious (1.0) by the LLM, including under the zero-shot prompt v1.

*"On the real benchmark the regex catches 39.7% of MCPTox attack descriptions, not the 77.5% we first
reported on fixtures we wrote ourselves. The LLM numbers come from small, strict, labelled samples because the
free model API is capped at 50 requests a day; every verdict names the model that produced it, and
unanswered cases are excluded rather than relabelled."*

**11. Architecture questions: where things live.**
- Real Google ADK: `backend/src/adk_layer/behavioral_anomaly_agent.py` (`LlmAgent` judge),
  `backend/src/adk_layer/callbacks/enforcement_callbacks.py` (`before_tool_callback`),
  `backend/src/adk_layer/pipeline_manager.py` (ADK `BaseAgent` + `Runner` + SQLite session state).
- Real A2A: `backend/src/a2a_bridge/a2a_server.py` (`to_a2a` server) and `backend/src/a2a_bridge/bridge.py`
  (`RemoteA2AClient.send`, JSON-RPC `message/send`).
- The LLM chain behind the CrewAI agents: `backend/src/llm_chain.py` (OpenRouter models, each with its own structured
  output method, then local Ollama) and `backend/src/crewai_layer/chain_llm.py`.
- One audit trail: every UI event is also a `pipeline_event` row in `backend/logs/audit_trail.jsonl`, with the
  provider and model that answered.

## Fallbacks if something breaks

- **DVMCP lab down:** the DVMCP cards show red `offline` dots. Use the in-process fixtures; they exercise the
  same pipeline.
- **UI won't load:** run the terminal version against the same live servers:
  `python -m src.demo_agent.run_demo --live --interactive`.
- **LLM quota exhausted or no key:** switch *Use LLM agents* off; the badges say `heuristic`. Say so. The
  architecture is identical; only the reasoning engine differs. The local model works too
  (`LLM_PROVIDER=ollama`) but needs about a minute per call.
- **An LLM call hangs:** after `timeouts.*_s` (60 s, `backend/config/settings.yaml`) the stage shows *LLM timed out →
  escalate*, and you get *Approve / Deny* instead of a silent allow. Deny it and move on.
