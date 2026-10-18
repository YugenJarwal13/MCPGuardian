# MCP Guardian — Phase 12 Report

Everything done since the Phase 11 report ([`PHASE11_WORKLOG.md`](../PHASE11_WORKLOG.md)): what was built and how,
the commands used, what the **real LLM pipeline** measured, the problems found, what could not be done, and what is
still pending. Written 2026-10-18.

- **Repository:** `https://github.com/YugenJarwal13/MCPGuardian.git`, branch `master`. Everything below is
  committed and pushed (commit list in §9).
- **Start:** commit `9c262aa` (end of Phase 11). **Tests now:** 95 pass, 0 skipped (with the DVMCP lab running).
- **Measured results** are in [`evaluation_report.md`](evaluation_report.md), generated from the per-case files in
  `src/evaluation/reports/` (one file per run). This report quotes them and never invents a number.

---

## 1. Summary

| Item | Status |
|---|---|
| LLM provider wiring (OpenRouter chain → local Ollama) behind the CrewAI agents | ✅ Done and verified live |
| Task 5 — evaluation of the **LLM pipeline** | ⚠️ **Done on samples, not the full 1,762 cases** (free-tier quota; CPU-only local model) |
| Task 6 — 50 hand-written tool-response cases | ✅ Done |
| Task 7 — schema-based scope rule; Challenge 2 left unpatched | ✅ Done; Challenge 2 result measured |
| Task 8 — UI redesign + "Test a MCP server LIVE" page | ✅ Done, verified in the browser (light + dark) |
| Task 9 — viva script, LLM-chain docs, push | ✅ Done |

**Headline results** (real data, real models, strict runs; details and intervals in `evaluation_report.md`):

| Detector (combined static+runtime, detectors only) | n answered | Precision | Recall | Hard-negative false positives |
|---|---|---|---|---|
| Heuristic (regex/statistics), full set | 1,762 | 96.9% | 39.1% | 5/12 |
| Heuristic, on the **same 70 cases** as the local LLM | 70 | 76.5% | 39.4% | 4/11 |
| **LLM · Ollama `qwen3:4b`** (CrewAI agents, prompt v2) | 70 | **100%** | **63.6%** | **0/11** |
| Heuristic, on the same 32 cases as the hosted LLM | 32 | 77.8% | 46.7% | 2/5 |
| **LLM · OpenRouter `dots-3-note-preview`** (prompt v2) | 32 | **92.3%** | **80.0%** | **0/5** |

- **Did the LLM beat the regex's 39.7% MCPTox recall?** On the held-out MCPTox sample the local 4B model flagged
  8 of 11 (72.7%) vs 6 of 11 for the regex on the same cases; the hosted model flagged 5 of 5 vs 3 of 5. Widened to **50 held-out MCPTox cases**, the local model's recall is **62.0% (31/50, 95% CI 48–74%)** vs 34.0% for the regex on the same cases and 39.7% across all 1,312 — the interval's lower bound (48%) clears the regex's full-set upper bound (42%), so on this benchmark **the LLM beat the regex**, by roughly 20–28 points.
  These samples are small — read the Wilson intervals in the report — but the direction is consistent across both models.
- **Runtime inspection (`runtime_only`, the project's novel layer)** was previously unmeasurable (0%, only 7 cases
  had a response). On the 50 hand-written response cases the local LLM caught **10 of 11** injected responses it was
  shown (regex 5/11) with **0 of 11 false positives** on instruction-like clean data (regex 4/11).
- **DVMCP Challenge 2** (the regex's known miss): the LLM flags both tools **malicious (1.0)** — including under the
  zero-shot prompt v1, which contains no DVMCP text, so it is not memorisation.
- **v2 prompt vs v1:** v2 did **not** measurably beat v1 (28 identical cases: one case each way).
- **Cost:** model calls take seconds (hosted: median ~11 s) to minutes (CPU-only local: median ~67 s, p95 ~162 s) vs
  well under a millisecond for the regex.
- **Scope rule:** benign real tools escalated by policy fell from 17.7% (keyword rule) to 11.9% (schema rule).

---

## 2. What was found at the start

| Item | Found |
|---|---|
| `.env` | OpenRouter primary + two fallback models with a per-model structured-output method, Ollama `qwen3:4b` as the final fallback, Gemini commented out. **The model IDs were unfilled placeholders** (`<dots3-note-preview-free-id>` …) and the file said they were unverified. |
| OpenRouter account | **Free tier**: `GET /api/v1/key` → `is_free_tier: true`, $0 credit. Free models are capped at **50 requests/day** (`X-RateLimit-Limit: 50`, HTTP 429 `free-models-per-day`, resets 00:00 UTC; "Add 10 credits to unlock 1000 free model requests per day"). |
| Ollama | Not running; the executable and models were gone from the machine. |
| Hardware | i5-11300H, **7.9 GB RAM, no GPU**. |
| Working tree | Your uncommitted `static_analysis_agent.py` edit, `done.md`, `PHASE11_WORKLOG.md`, and a deleted `.env.example` — **left untouched**. |

Verified slugs (public `GET /api/v1/models`, no key needed):

| `.env` placeholder | Real slug | Structured method | Works over the API? |
|---|---|---|---|
| Dots3-Note Preview | `dots-studio/dots-3-note-preview:free` | `response_format` | ✅ (~5–26 s per call) |
| Nemotron 3.5 Lightning | `nvidia/nemotron-3.5-lightning:free` | `tool_call` | ✅ (one call took 128 s) |
| Inkling Small | `thinkingmachines/inkling-small:free` | `json_parse` | ❌ HTTP 403 "only available on agentic harnesses" — skipped automatically |
| local fallback | Ollama `qwen3:4b` | `ollama_format` | ✅ (needs re-install + re-pull, see §4) |

I did **not** edit `.env`; the code resolves the placeholders (`src/llm_chain.py`). A shell variable always wins
(`LLM_PROVIDER=ollama …` forces the local model for one run without touching any file).

---

## 3. What was built, and how

### 3.1 The LLM chain behind the CrewAI agents (commit `2314524`)

- **`src/llm_chain.py`** — `ChainLLM` walks the configured chain. A slot with a permanent error (HTTP
  400/401/403/404) is disabled for the process; a daily-quota 429 disables the free tier until its reset; transient
  errors and unparseable output retry once, then fall through. An account-wide token bucket (`OPENROUTER_RPM`, default
  16/min) respects the 20/min limit. Every answer is cached on disk (`logs/llm_cache.jsonl`) so a long evaluation
  **resumes** after an interruption or a quota stop. Per-call metadata (provider, model, method, latency, tokens,
  models tried) travels with the verdict.
- **`src/crewai_layer/chain_llm.py`** — a CrewAI `BaseLLM` over the chain. *Why this exists:* CrewAI's agent loop
  only accepts text containing `Final Answer:`; a bare JSON reply makes it re-prompt up to `max_iter`, multiplying
  latency and (on a quota-limited key) requests. The LLM therefore answers `Thought: … Final Answer: {json}` so one
  call completes the agent; `output_pydantic` then parses the JSON. This also explains why the earlier Ollama
  probe never finished.
- **`src/crewai_layer/crew.py`** — `analyze_static_meta` / `analyze_runtime_meta` return `(verdict, engine, meta)`;
  engine is `llm`, `heuristic`, `heuristic_fallback` (the LLM was tried and failed) or `timeout`. Provider and model
  go into every audit record. CrewAI telemetry is disabled. `Agent.max_retry_limit=0` (CrewAI had re-invoked failing
  calls 3×). `GUARDIAN_AGENT_TIMEOUT_S` overrides the timeouts per run.
- **Quota protection:** `tests/conftest.py` forces LLM auto-detection off in the test suite so tests can never spend
  quota. 12 offline tests (`tests/test_llm_chain.py`, fake transport) cover each payload method, the 403 disable, the
  daily-quota path, retry/fall-through, the cache, placeholder resolution and a full CrewAI agent finishing in exactly
  one call.
- ADK judge: `src/adk_layer/adk_runtime.py` routes the ADK anomaly judge through LiteLLM (`openrouter/<slug>` or
  `ollama_chat/<model>`).

### 3.2 Tasks 6 and 7 (commits `26b8c30`, `e0baa97`)

- **Task 6 — response benchmark.** `src/data/custom_fixtures/response_cases.py` generates `fixtures.json`: **50 cases
  written for this project in its own words** — 29 injected responses (indirect injection in search/page/doc/ticket/
  email content, fake system/assistant turns, exfiltration directives, tool redirection, hidden JSON fields,
  zero-width/base64 obfuscation, persistence, social engineering), 9 plain benign, and **12 hard negatives** (a
  changelog "ignore the deprecated v1 API", an article quoting "ignore previous instructions", a customer quote, an
  email addressed to a human, an "Assistant: Priya N." ticket field, …). All tool descriptions are plain so only the
  response carries the attack. Tests keep the JSON in sync and check no upstream exploit phrasing appears.
  Written independently of the heuristics (untuned): the regex catches 10/29 and falsely flags 5/12.
- **Task 7.1 — schema-based scope.** `ToolTestCase.requested_scope()` now reads the tool's **parameter schema**
  (secret-taking parameter → credential; `code`/`command` → execution; `url`/`host`/`recipient` → network; a path-like
  parameter plus write intent → file write) and never the description prose. The old rule is kept as
  `requested_scope_keyword()` solely for before/after. Same data: benign real tools escalated **17.7% → 11.9%**;
  MCPTox tools with a scope 570 → 3 (the old rule's extra "recall" came from keywords in the poisoned descriptions,
  not from detection). Consequences handled: the notes-writer fixture got a real path/content schema; the
  poisoned-fetch fixture now escalates pre-call because its `url` parameter is genuine network access.
- **Task 7.2 — Challenge 2 left unpatched,** as instructed; the LLM result is recorded in the report and viva script.

### 3.3 Task 5 — the evaluation harness and results (commit `8182317` and the final commit)

- **Design.** One file per run, `src/evaluation/reports/cases_<name>.jsonl` (verdicts, engine, provider, model,
  method, latency, plus the heuristic's verdicts for the same case). `src/evaluation/report.py` derives every
  table, interval and slice from those files. Detectors-only and policy views; Wilson 95% intervals; per-group recall
  or false-positive rate; head-to-head on common cases; latency; LLM-vs-regex disagreement; Challenge 2 table;
  scope before/after; prompt v1 vs v2.
- **Strict runs.** `LLM_LOCAL_FALLBACK=off`: a failed or quota-stopped case is *unanswered*, excluded from the LLM
  numbers and counted — never relabelled as an LLM verdict. The heuristic is compared on exactly the answered cases.
- **Nested balanced ordering.** `--limit N` takes the first N of a round-robin over the seven groups, so any prefix
  is balanced and smaller runs are subsets of larger ones.
- **Task 5.0 sanity batch** (OpenRouter, 30 cases): **30/30 answered, 0 parse failures, 0 timeouts, 0 fallbacks**
  (47 calls, ~11 s each) — far under the 15% threshold, so no schema workaround was needed.
- **The runs** (all verdicts name provider and model):

| Run | Model | Cases scored / answered | Notes |
|---|---|---|---|
| `deterministic` | regex + statistics | 1,762 / 1,762 | full set; ~0.8 ms per case |
| `llm` | OpenRouter dots-3-note-preview | 35 / **32** | stopped by the 50/day cap; 3 unanswered |
| `ollama` | Ollama qwen3:4b | 70 / **70** | one request at a time |
| `ollama_v1`, `ollama_v2_sub` | qwen3:4b, prompt v1 / v2 | 28 / 28 each | Task 5.5 |
| `ollama_mcptox` | qwen3:4b | 50 / **50** | MCPTox only, larger sample |

### 3.4 Task 8 — the UI (commit `326a50e`)

Builds on the Phase 11 React/Vite app and its WebSocket events.

- **Design:** light by default, a fully separate dark palette, toggle in the nav, persisted in `localStorage` and
  applied before first paint (no flash). Inter + JetBrains Mono bundled via `@fontsource` (no third-party requests), a
  real type scale, tabular numerals. Two-pane layout; hash routes `#/` and `#/test-live`.
- **Motion that carries meaning:** the active stage's status is typed out with pulsing dots, a live timer ticks, the
  node spins then draws its check / alert / cross, cards recolour smoothly, detail panels animate their real height,
  stages stagger in; `prefers-reduced-motion` is honoured.
- **Everything the backend does is surfaced:** per-stage engine badge naming the model (`LLM · dots-3-note-preview`,
  `heuristic`, `LLM failed → heuristic`, `LLM timed out → escalate`), latency, "answered by" + models tried, the real
  description/response with flagged phrases highlighted, confidence bar, fingerprint evidence, A2A transport and round
  trip. Escalation is an inline **Your decision** panel, not a modal. Static analysis streams per-tool progress.
- **"Test a MCP server live" (basic):** paste an http(s) MCP endpoint (SSE or streamable HTTP); the Guardian connects
  and statically inspects **every** tool (no call), shows a verdict table, then runs the full pipeline on one tool you
  pick. Lists what is not supported yet (stdio, auth headers/OAuth, multi-call sessions). Refuses non-http(s) URLs,
  credentials in the URL and link-local/metadata addresses.
- **Verification:** driven in the in-app browser — Challenge 6 (real injected response highlighted), Challenge 10
  (flagged/blocked in dark mode), theme persistence across a reload, and the live page against Challenge 2. This found
  and fixed a real crash (inspect-mode `tools` arrived as objects; the renderer assumed strings) and added an
  `ErrorBoundary`. `tests/test_api_custom_server.py` runs a real in-process FastMCP SSE server.

### 3.5 Task 9

`docs/viva_demo_script.md` rewritten for the new UI (incl. the quota budget, Challenge 2 with LLM off/on, the live
page); `README.md` has an "LLM configuration" section (the chain, forcing a provider, quotas, resuming) — this is the
documentation of the fallback chain; `config/settings.yaml` timeouts raised 30 s → 60 s from the measured latency.

---

## 4. Commands used (reproducible)

```bash
# --- environment / model discovery (no key needed for the model list)
curl -s https://openrouter.ai/api/v1/models                      # verify the slugs
# (GET /api/v1/key with the Authorization header showed is_free_tier=true)

# --- Ollama had to be reinstalled (approved by you) and the model re-pulled
winget install --id Ollama.Ollama -e --silent                    # v0.40.5, ~1 GB, per-user
ollama pull qwen3:4b                                             # ~2.5 GB

# --- tests, fixtures, manifest
.venv/Scripts/python -m pytest -q                                # 95 passed
python -m src.data.custom_fixtures.response_cases                # regenerate fixtures.json
python -m src.data.build_manifest                                # 1,762 cases (DVMCP lab must be up)

# --- evaluation (lab must be running: python scripts/run_dvmcp_native.py)
python -m src.evaluation.run_eval                                # deterministic, full set
python -m src.evaluation.run_eval --llm --limit 30 --name llm_sanity          # 5.0 sanity (OpenRouter)
python -m src.evaluation.run_eval --llm --mcptox-n 200 --benign-n 100 --name llm   # resumes after a quota stop
python -m src.evaluation.run_eval --llm --provider ollama --mcptox-n 200 --benign-n 100 --limit 70 --name ollama
python -m src.evaluation.run_eval --llm --provider ollama --prompt-version v1 --limit 28 --name ollama_v1
python -m src.evaluation.run_eval --llm --provider ollama --only-groups mcptox --limit 50 --name ollama_mcptox
python -m src.evaluation.run_eval --report-only                  # rebuild docs/evaluation_report.md

# --- UI
bash scripts/run_api.sh ; bash scripts/run_frontend.sh           # http://localhost:5173
```

---

## 5. Issues found, and how each was handled

| # | Issue | Handling |
|---|---|---|
| 1 | `.env` model IDs were placeholders. | Resolved to verified slugs in code; `.env` not edited. |
| 2 | **OpenRouter free tier = 50 requests/day**, which ended the main run after 35 cases. | Strict mode + resumable cache; run stopped cleanly; documented; local model used for the larger sample. |
| 3 | Inkling Small returns HTTP 403 over the API. | Permanent-error slot disabling; skipped automatically. |
| 4 | CrewAI re-prompted/retried (ReAct format; `max_retry_limit=2`), multiplying calls. | `Final Answer:` wrapper; `max_retry_limit=0`. |
| 5 | CrewAI runs `call()` on another thread, losing thread-local metadata. | Per-call token-keyed metadata table. |
| 6 | Ollama was gone from the machine. | Reinstalled and re-pulled (approved). |
| 7 | **Local model thrashed**: llama.cpp's in-RAM prompt cache grew to ~7 GB on a 7.9 GB machine (0.3 tokens/s). | `keep_alive: 0` for evaluation runs (model unloaded per call); lab/preview servers stopped during the run. |
| 8 | Stricter scope rule changed two fixtures/tests. | Notes-writer fixture got a real write schema; fetch test approves the escalation. |
| 9 | UI render crash in inspect mode (found by driving the page). | Fixed, plus an `ErrorBoundary`. |
| 10 | Link-local URL guard swallowed its own error (`CustomServerError` is a `ValueError`). | Fixed; test added. |
| 11 | A `git rm` on never-tracked (git-ignored) CSVs aborted a commit chain. | Retried correctly; no data lost. |
| 12 | Several patch scripts broke on shell-heredoc escaping and a transient file lock. | Re-done via files/edit tool; every change re-tested before commit. |
| 13 | **Few-shot overlap (found while analysing results):** the v2 prompt quotes two DVMCP descriptions and overlaps some fixtures. The UI run later showed the model's reasoning literally saying "this matches the MALICIOUS examples provided (live DVMCP challenge 2)". | Disclosed prominently in the report; the v1 (zero-shot) run is used for the clean Challenge 2 answer; MCPTox and the real benign tools are the held-out benchmarks. |

---

## 6. Surprises

- **The small local model did well**, better than expected: precision 100%, recall 63.6% on 70 cases, and **0 false
  positives on the hard negatives** where the regex had 4/11. It also flagged both Challenge 2 tools under the
  zero-shot prompt. (An earlier ad-hoc test of the raw model rated Challenge 10's poisoned description `clean`;
  through the real CrewAI prompt it did not. The prompt, not just the model, matters.)
- **But it is not strictly better than the regex:** on `custom-resp-atk-03` it *quoted* the injected "Instruction for
  the summarizer" in its own reasoning and still answered `clean` — a self-contradiction the regex did not make.
- **v2 (few-shot) did not beat v1** on the same 28 cases; its precision gain and recall loss are each one case.
- **The old keyword scope rule was doing most of the "detection"** on MCPTox (570 tools "caught" by keywords in the
  poisoned text, 0.2% under the schema rule).
- **Free-tier arithmetic:** a useful hosted evaluation needs ~400 requests; the account allows 50/day.

---

## 7. What could not be done

1. **The full 1,762-case LLM evaluation.** Hosted: capped at 50 requests/day. Local: ~70 s per call on this CPU-only
   laptop, so a full run would take ≈ 2 days. The LLM numbers are therefore from balanced samples with wide intervals.
2. **v1 vs v2 on a hosted model**, and at more than 28 cases.
3. **Hosted-model Challenge 2 under v1** (the local model covers it).
4. **A live pass through the new UI with the *hosted* model** (quota). A live pass with the **local** model *was*
   verified: on the "Test a server live" page, Challenge 2 ran with *Use LLM agents* on; OpenRouter's daily quota was
   hit, the chain **fell back to local Ollama automatically**, and the Static check cards showed the badge
   **LLM · qwen3:4b** with both tools **MALICIOUS 100%** after ~2 minutes per tool (typed live status and ticking timer
   visible throughout).
5. **Gemini** was not used (commented out in `.env`).

---

## 8. Pending

**Needs OpenRouter capacity** (add $10 of credits → 1,000 free requests/day, or wait for the 00:00 UTC resets):
1. `python -m src.evaluation.run_eval --llm --mcptox-n 200 --benign-n 100 --name llm` — resumes from the cache and
   continues the hosted run; repeat daily, or once with credits.
2. `GUARDIAN_PROMPT_VERSION=v1 … --name prompt_v1` and the matching v2 subset to measure v1 vs v2 on a hosted model.
3. Optionally `--full` for all 1,762 cases.

**Doesn't need a key:**
4. A v3 prompt from the models' own errors (DVMCP / benign / fixtures only — never MCPTox).
5. Make the "Test a server live" page handle auth headers and stdio servers; keep sessions open for several calls.
6. A live-response benchmark built from real DVMCP calls with hand-written payloads.
7. `PHASE11_WORKLOG.md`, `done.md`, your `static_analysis_agent.py` edit and the deleted `.env.example` are still
   uncommitted/untouched, as you asked.

---

## 9. Commits (all pushed)

| Commit | What |
|---|---|
| `2314524` | Phase 12.0 — OpenRouter chain behind the CrewAI agents |
| `26b8c30` | Phase 12.6 — 50 hand-written response cases |
| `e0baa97` | Phase 12.7 — schema-based `requested_scope()` |
| `326a50e` | Phase 12.8 — redesigned UI + "Test a MCP server LIVE" |
| `8182317` | Phase 12.5 (part 1) — evaluation harness + first real LLM results |
| *(final)* | Phase 12.5 (part 2) — local-model runs, prompt comparison, docs, this report |

Files of note: `src/llm_chain.py`, `src/crewai_layer/chain_llm.py`, `src/crewai_layer/crew.py`,
`src/evaluation/{run_eval,report}.py`, `src/data/custom_fixtures/response_cases.py`, `src/data/schemas.py`,
`src/api/{runner,servers,events,main}.py`, `frontend/src/**`, `docs/{evaluation_report,prompt_iterations,viva_demo_script,PHASE12_REPORT}.md`.
