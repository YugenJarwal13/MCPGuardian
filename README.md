# MCP Guardian

A security gateway for the **Model Context Protocol (MCP)**. It sits between an AI agent and the MCP servers the
agent uses, and inspects every tool description and every tool response before the agent can act on it. It detects
**tool poisoning**, **indirect prompt injection**, **tool shadowing** and **rug-pull** attacks, then enforces an
`allow`, `block` or `escalate to a human` decision.

- **CrewAI** runs the two LLM inspectors (tool metadata and tool responses).
- **Google ADK** keeps per-tool behavioural state, judges drift, and runs the case manager.
- **A2A** carries each verdict from the CrewAI side to the ADK case manager over HTTP.

Test data comes from published poisoned-MCP resources:
[MCPTox](https://github.com/zhiqiangwang4/MCPTox-Benchmark) and
[DVMCP](https://github.com/harishsg993010/damn-vulnerable-MCP-server), plus a small set of hand-written response cases.

## Results

Full run of **1,762 cases** with the local `qwen3:4b` model (every case answered by the model), compared with a
regex baseline on the same cases:

| | Precision | Recall |
|---|---|---|
| Guardian (CrewAI + qwen3:4b) | 98.6% | 74.4% |
| Regex baseline | 96.9% | 39.1% |

On the 1,312 real MCPTox attacks the pipeline flags 75.8% (95% CI 73-78%) against 39.7% for the baseline, with 3.9% false
alarms on 362 real clean tools. Details, per-dataset tables and limitations (notably DVMCP, 16%) are in
[`docs/evaluation_report.md`](docs/evaluation_report.md); token, time and cost figures are in
[`docs/cost_and_runtime.md`](docs/cost_and_runtime.md).

## Quick start

Requirements: Python 3.12, Node.js 20, an OpenRouter API key.

```bash
python -m venv .venv
.venv\Scripts\activate                 # macOS/Linux: source .venv/bin/activate
pip install -r backend/requirements.txt
cd frontend && npm install && cd ..
cp .env.example .env                   # then put your OpenRouter key in .env
bash backend/scripts/setup_dvmcp.sh    # clones the DVMCP lab into backend/external/ (Windows: use Git Bash)
```

Start the three parts (Windows; each in its own terminal, from the repository root):

```bat
start-backend.cmd
start-lab.cmd
start-frontend.cmd
```

Then open **http://localhost:5173**. `start-backend.cmd` uses the OpenRouter models from `.env` and never falls back to
the slow local model; run `start-backend.cmd local` to allow Ollama as a last resort.

On macOS/Linux run the same commands by hand: `cd backend && python -m uvicorn src.api.main:app --port 8000`,
`cd backend && python scripts/run_dvmcp_native.py`, and `cd frontend && npm run dev`.

## The web app

| Page | What it does |
|---|---|
| **Overview** | The problem, how Guardian works, the evaluation results, the datasets and the limitations. |
| **Live demo** | Pick a DVMCP or fixture server and run one tool call. An animated diagram follows the call through every check, with a plain-English narration, the backend event log and the without/with-Guardian comparison. Approvals appear inline. |
| **Check a server** | Paste the URL of any public MCP server (SSE or streamable HTTP). Guardian reads every tool it offers with its LLM inspectors and reports which ones carry hidden instructions. You can then run one tool through the full pipeline. |

Both live pages use the LLM pipeline only. Not supported yet: stdio servers, servers that need authentication, and
multi-call sessions.

Public servers that work without a login: DeepWiki `https://mcp.deepwiki.com/mcp`, Microsoft Learn
`https://learn.microsoft.com/api/mcp`, Cloudflare Docs `https://docs.mcp.cloudflare.com/mcp`, Context7
`https://mcp.context7.com/mcp`, CoinGecko `https://mcp.api.coingecko.com/mcp`, Hugging Face Hub
`https://huggingface.co/mcp`, GitMCP `https://gitmcp.io/<owner>/<repo>`.

## Configuration

`.env` (git-ignored; template in `.env.example`) selects the models behind the CrewAI agents and the ADK judge:

```dotenv
LLM_PROVIDER=openrouter
OPENROUTER_API_KEY=
LLM_MODEL=dots-studio/dots-3-note-preview:free
OPENROUTER_FALLBACK_MODELS=nvidia/nemotron-3.5-lightning:free
LLM_STRUCTURED_METHODS=response_format,tool_call
```

The model chain (`backend/src/llm_chain.py`) tries the primary model, then the fallbacks, then optionally a local
Ollama model. Every verdict records the provider, model and structured-output method that produced it. A model that
fails permanently (HTTP 400/401/403/404) is disabled for the process, a temporary upstream error rests it for five
minutes, and a daily-quota error pauses the free tier until it resets. Answers are cached in
`backend/logs/llm_cache.jsonl`, so repeating a run costs no requests.

OpenRouter's free tier allows about 50 requests a day (resets 00:00 UTC). A run costs one request per tool description
plus one for the response.

## Evaluation

```bash
cd backend
python -m src.evaluation.run_eval                    # regex baseline on all cases (the DVMCP lab must be running)
python -m src.evaluation.run_eval --llm --limit 30   # LLM pipeline on a balanced sample
python -m src.evaluation.run_eval --report-only      # rebuild docs/evaluation_report.md and the web app's results
bash scripts/run_full_local_eval.sh                  # all cases with a local Ollama model (needs a GPU)
```

| Source | Cases | Notes |
|---|---|---|
| MCPTox | 1,312 attacks, 362 clean tools | 36 rows the authors flagged as bad data are excluded |
| DVMCP | 31 live tools | read from the running lab |
| Hand-written | 50 responses, 7 clean tools | 29 attacks, 9 plain, 12 hard negatives |

## Tracing, callbacks and security

- **Tracing:** every run is one OpenTelemetry trace (a span per stage and per model call), written to
  `backend/logs/traces.jsonl`. Set `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY` and optionally `LANGFUSE_HOST` to send
  traces to [Langfuse](https://langfuse.com). The trace id appears in the live console.
- **Callbacks:** CrewAI step/task callbacks and ADK agent, model and tool callbacks write intermediate outputs and
  errors to `backend/logs/audit_trail.jsonl` (`backend/src/monitoring.py`). `streamlit run backend/src/dashboard/app.py`
  browses the audit trail.
- **Input guard:** tool arguments and server URLs are validated before any work starts.
- **Public mode** (`GUARDIAN_PUBLIC=1`): internal addresses are refused, runs are rate-limited, the daily number of
  LLM runs is capped, and the DVMCP challenges that execute commands or read files are inspect-only.

## Docker

```bash
docker build -t mcp-guardian .
docker run -p 7860:7860 -e OPENROUTER_API_KEY=... mcp-guardian
```

The image serves the web app, the API and the DVMCP lab on one port.

## Repository layout

```
backend/
  src/mcp_gateway/    the interception layer (GuardedMCPClient, GuardianInterceptor)
  src/crewai_layer/   inspection agents, tasks and the verdict schema
  src/adk_layer/      behavioural analysis, state stores, enforcement callbacks, case manager
  src/a2a_bridge/     A2A server and client
  src/api/            FastAPI + WebSocket API used by the web app
  src/security/       input guard and public-mode protections
  src/evaluation/     metrics, evaluation runner, report generation
  src/data/           loaders for MCPTox, DVMCP and the hand-written cases
  tests/              pytest suite
frontend/             React + Vite web app
docs/                 architecture, evaluation report, cost and runtime, prompt log, requirements map
```

Run the tests with `cd backend && python -m pytest -q`. They use fakes, need no API key, and skip the tests that
need the DVMCP lab when it is not running.

More: [`docs/architecture.md`](docs/architecture.md), [`docs/prompt_iterations.md`](docs/prompt_iterations.md),
[`docs/REQUIREMENTS.md`](docs/REQUIREMENTS.md).
