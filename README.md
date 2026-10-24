# MCP Guardian

A security interception layer for the **Model Context Protocol (MCP)**. It sits
transparently between an LLM agent and the MCP servers it uses, screening every
`list_tools` and `call_tool` through a pipeline of inspection agents that detect
**tool poisoning**, **indirect prompt injection**, **tool shadowing**, and
**rug-pull** attacks — then enforces hard `allow` / `block` / `escalate-to-human`
decisions.

Built on **CrewAI** (reasoning/inspection), **Google ADK** (stateful enforcement
+ case management), and **A2A** (the cross-framework hop between them).

> Course project. Test data comes from published poisoned-MCP resources —
> [DVMCP](https://github.com/harishsg993010/damn-vulnerable-MCP-server) and
> [MCPTox-Benchmark](https://github.com/zhiqiangwang4/MCPTox-Benchmark) — with a
> small hand-picked benign control set for measuring false positives.

## Architecture

See [`docs/architecture.md`](docs/architecture.md) for the full pipeline diagram
and per-agent role table. In one line:

```
agent → GuardedMCPClient → interceptor → [CrewAI: static + runtime] →A2A→ [ADK: anomaly + enforcement] → allow/block/escalate
                                                              └────────── audit_trail.jsonl ──────────┘
```

## Layout

```
MCPGuardian/
├── backend/            Python backend: gateway, CrewAI + ADK + A2A layers, API, evaluation, tests
│   ├── src/            application code (run Python commands from backend/ so `src.*` resolves)
│   ├── tests/          pytest suite
│   ├── config/         settings.yaml, allowlist.yaml
│   ├── scripts/        run_api.sh, run_dvmcp_native.py, run_full_eval.sh, setup_*.sh
│   ├── logs/           audit trail, LLM answer cache, ADK case store (git-ignored contents)
│   ├── external/       third-party clones: DVMCP, MCPTox (git-ignored)
│   ├── requirements.txt · pyproject.toml · docker-compose.yml · data_manifest.json
├── frontend/           React + Vite UI (separate app; talks to the backend over HTTP/WebSocket)
├── docs/               architecture, evaluation report, prompt log, viva script, phase reports
├── .env                your secrets (git-ignored; see "LLM configuration")
└── README.md
```

| Backend path | What lives here |
|---|---|
| `backend/src/mcp_gateway/` | The interception layer (`GuardedMCPClient`, `GuardianInterceptor`) |
| `backend/src/crewai_layer/` | Static-analysis + runtime-inspection agents, tasks, verdict schema |
| `backend/src/adk_layer/` | Behavioral-anomaly agent, ADK state stores, enforcement callbacks |
| `backend/src/a2a_bridge/` | CrewAI verdict → A2A message → ADK case manager |
| `backend/src/api/` | FastAPI + WebSocket live-pipeline API used by the frontend |
| `backend/src/llm_chain.py` | The OpenRouter → Ollama LLM fallback chain |
| `backend/src/data/` | Loaders for DVMCP / MCPTox / benign / custom test cases |
| `backend/src/evaluation/` | Metrics, evaluation runner, report generation |
| `backend/src/dashboard/` | Streamlit audit-trail viewer |
| `backend/src/demo_agent/` | End-to-end demo agent using Guardian-wrapped tools |

## Quick start

### 1. Backend setup (once)

```bash
cd backend
python -m venv .venv
source .venv/bin/activate            # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Create your `.env` (git-ignored) in the **repo root** (or in `backend/`; `backend/.env` wins if both
exist) and fill in your LLM key(s) — see [LLM configuration](#llm-configuration). Without any key
everything still runs on the deterministic detectors.

Run the test suite (no LLM keys or network needed):

```bash
cd backend
python -m pytest -q
```

Fetch the benchmark data and start the DVMCP challenge lab (only needed for the live demo and for
evaluation runs):

```bash
cd backend
bash scripts/setup_mcptox.sh                 # clones MCPTox into backend/external/
bash scripts/setup_dvmcp.sh                  # clones DVMCP; builds/runs Docker if present
python scripts/run_dvmcp_native.py           # no Docker: ports 9001-9010, 127.0.0.1 only
```

The native launcher serves upstream's poisoned `server.py` challenge modules by default
(`--variant sse` reproduces the Docker image, whose tool descriptions are simplified and carry no poison).

### 2. Frontend setup (once)

```bash
cd frontend
npm install
```

## Starting the application

Open **three terminals** from the repo root. Start them in this order.

| # | Terminal | Command | Serves |
|---|---|---|---|
| 1 | DVMCP lab *(optional — live poisoned MCP servers)* | `cd backend && python scripts/run_dvmcp_native.py` | `127.0.0.1:9001-9010` |
| 2 | **Backend API** | `cd backend && bash scripts/run_api.sh` | `http://127.0.0.1:8000` (REST + WebSocket, plus the A2A case manager on a free local port) |
| 3 | **Frontend** | `cd frontend && npm run dev` | `http://localhost:5173` |

Then open **http://localhost:5173**.

Notes:

* No bash (PowerShell)? Terminal 2 is just
  `cd backend; python -m uvicorn src.api.main:app --host 127.0.0.1 --port 8000`
  (from the repo root: `python -m uvicorn --app-dir backend src.api.main:app --port 8000`).
  Terminal 3 can also be `bash frontend/scripts/run_frontend.sh`.
* The frontend dev server proxies `/servers`, `/health` and `/ws` to `:8000`. Point it elsewhere with
  `GUARDIAN_API=http://host:port npm run dev`.
* One-process alternative: `cd frontend && npm run build`, then the backend also serves the built UI at
  `http://127.0.0.1:8000`.
* Stop everything with `Ctrl+C` in each terminal. The in-process fixture servers work without terminal 1.
* Historical audit-log dashboard (optional): `cd backend && streamlit run src/dashboard/app.py`.

Run evaluations and other Python tools from `backend/`, for example:

```bash
cd backend
python -m src.evaluation.run_eval                   # deterministic baseline (DVMCP lab must be running)
python -m src.evaluation.run_eval --llm --limit 30  # LLM pipeline on a balanced sample
python -m src.evaluation.run_eval --report-only     # rebuild docs/evaluation_report.md
python -m src.demo_agent.run_demo --live            # terminal demo against the live lab
```

## The web app

Four views in one light/dark-themed app (the theme toggle persists across refreshes). Every animation
is driven by the events the backend really emits; nothing is scripted.

* **Overview (`#/`)** — what MCP tool poisoning is, how Guardian stops it (CrewAI inspectors, Google
  ADK behaviour layer, A2A hand-off), a looping hand-drawn story (trusting agent → tricked → Guardian
  steps in → safe), and the **results of the full 1,762-case run** with qwen3:4b on an NVIDIA H200 (MIG
  slice): headline numbers, per-dataset bars with 95% intervals, the regex baseline vs the model, the
  datasets with credit (MCPTox, DVMCP) and the honest limitations. The numbers come from
  `frontend/src/data/results.json`, regenerated by `python -m src.evaluation.run_eval --report-only`.
* **Live demo (`#/demo`)** — pick a DVMCP (or clean/offline) server and run one tool call. An animated
  diagram shows the call travelling through the Guardian (read the labels → policy gate → real call →
  scan the answer → watch behaviour → A2A case manager → final decision), a plain-English narration
  explains each step with the real model's reasoning, a terminal panel prints every backend event, and
  a *without / with Guardian* comparison shows what the agent would have trusted. Escalations are an
  inline *Your decision* panel (Approve / Deny). Stage-by-stage technical cards are under *Under the hood*.
* **Check a server (`#/test-live`)** — paste an http(s) MCP endpoint (SSE `…/sse` or streamable HTTP).
  The Guardian connects and inspects every tool it offers (no call is made), gives a plain verdict
  ("2 of 6 tools carry hidden instructions"), and lets you run one tool through the full pipeline.
  *Not supported yet:* stdio servers, authenticated servers, multi-call sessions (the page says so).

In-process fixture servers (clean reference, tricky-but-clean data, offline attack stand-ins) work
without the lab. Every streamed event is also written to `backend/logs/audit_trail.jsonl` (layer
`pipeline_event`), so the Streamlit dashboard shows the same runs.

## LLM configuration

`.env` (git-ignored) selects the model behind the CrewAI agents (and the ADK anomaly judge):

```dotenv
LLM_PROVIDER=openrouter
OPENROUTER_API_KEY=...
LLM_MODEL=<primary model slug>
OPENROUTER_FALLBACK_MODELS=<slug>,<slug>
LLM_STRUCTURED_METHODS=response_format,tool_call,json_parse     # one per model, primary first
LLM_FALLBACK_PROVIDER=ollama
LLM_FALLBACK_MODEL=qwen3:4b
LOCAL_LLM_ENDPOINT=http://localhost:11434
```

**The fallback chain** (`backend/src/llm_chain.py`): primary model → fallback models → local Ollama. Each model has
its own structured-output method (`response_format` = JSON schema, `tool_call` = a forced function call,
`json_parse` = JSON in plain text, `ollama_format` = Ollama's schema constraint). A slot that fails
*permanently* (HTTP 400/401/403/404) is disabled for the process; a daily-quota 429 disables the free tier
until its reset; transient errors and unparseable output retry once and then fall through to the next slot.
`LLM_LOCAL_FALLBACK=off` keeps the chain from ever reaching the local model (evaluations use this). Verified
slugs for the placeholder names written in `.env` (`<dots3-note-preview-free-id>` etc.) are resolved
automatically: `dots-studio/dots-3-note-preview:free`, `nvidia/nemotron-3.5-lightning:free`,
`thinkingmachines/inkling-small:free` (the last returns HTTP 403 "only available on agentic harnesses", so it
is skipped at runtime).

**Forcing a provider for one run, without editing `.env`:**

```bash
cd backend && LLM_PROVIDER=ollama python -m src.evaluation.run_eval --llm --name ollama   # local qwen3:4b only
GUARDIAN_PROMPT_VERSION=v1 python -m src.evaluation.run_eval --llm --name llm_v1
```

A shell variable always wins over `.env`; `LLM_PROVIDER=ollama` never touches OpenRouter.

**Quotas.** A *free-tier* OpenRouter key allows 50 `:free` requests/day (HTTP 429 `free-models-per-day`,
resets 00:00 UTC; $10 of credits lifts it to 1,000/day). Evaluations are resumable — every model answer is
cached in `backend/logs/llm_cache.jsonl`, so re-running the same command continues where a quota stopped it.
Gemini is not used (its block in `.env` is commented out).

Every audit record of an LLM verdict carries `engine`, `provider`, `model` and `method`.

## Test data & ground truth

| Source | Cases | Label | Notes |
|---|---|---|---|
| DVMCP | 10 challenges → 31 live tools | `malicious` | 1:1 port→challenge→attack-category mapping (see `dvmcp_loader.py`) |
| MCPTox | 1,312 | `malicious` | attack-only; 11 risk scopes; 36 author-flagged rows excluded |
| Benign control | 369 | `clean` | 362 real unpoisoned tools from MCPTox's 45 servers + 7 hand-written |
| Custom (responses) | 50 | 29 `malicious`, 21 `clean` | hand-written tool *responses* (12 hard negatives with instruction-like words); the only runtime-inspection benchmark |

## Status

Implemented phase by phase per [`implementation_plan.md`](implementation_plan.md); see
[`docs/evaluation_report.md`](docs/evaluation_report.md) for measured results (LLM pipeline vs the deterministic
baseline) and [`PHASE11_WORKLOG.md`](PHASE11_WORKLOG.md) / [`docs/PHASE12_REPORT.md`](docs/PHASE12_REPORT.md) for
everything that was built, how, and what is still pending. Deterministic layers are fully unit-tested
(`pytest -q`); the LLM path is tested offline with a fake transport and exercised live against OpenRouter and
Ollama (see the report for sample sizes).
