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

| Path | What lives here |
|---|---|
| `src/mcp_gateway/` | The interception layer (`GuardedMCPClient`, `GuardianInterceptor`) |
| `src/crewai_layer/` | Static-analysis + runtime-inspection agents, tasks, verdict schema |
| `src/adk_layer/` | Behavioral-anomaly agent, ADK state stores, enforcement callbacks |
| `src/a2a_bridge/` | CrewAI verdict → A2A message → ADK pipeline |
| `src/data/` | Loaders for DVMCP / MCPTox / benign / custom test cases |
| `src/evaluation/` | Metrics, ablation harness, report generation |
| `src/dashboard/` | Streamlit audit-trail viewer |
| `src/demo_agent/` | End-to-end demo agent using Guardian-wrapped tools |
| `external/` | Third-party clones (git-ignored, not authored here) |
| `docs/` | Architecture, evaluation report, viva demo script |

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                 # then fill in your LLM key(s)
```

Sanity-check the three frameworks (Phase 0):

```bash
python scratch/toy_crewai.py         # prints something containing "ready"
python scratch/toy_adk.py
python scratch/toy_mcp_client.py     # lists tools from a reference MCP server
```

Run the deterministic test suite (no LLM keys required):

```bash
pytest tests -q
```

Bring up the DVMCP challenge lab and the benchmark:

```bash
bash scripts/setup_mcptox.sh
bash scripts/setup_dvmcp.sh                 # clones DVMCP; builds/runs Docker if present
python scripts/run_dvmcp_native.py          # no Docker: same ports 9001-9010, 127.0.0.1 only
```

The native launcher serves upstream's poisoned `server.py` challenge modules by
default (`--variant sse` reproduces the Docker image, whose tool descriptions are
simplified and carry no poison).

Launch the historical audit-log dashboard:

```bash
streamlit run src/dashboard/app.py
```

## Running the live UI

Pick a clean or poisoned MCP server, run one tool call, and watch every stage
stream in live: static check → policy gate / tool call → runtime check →
behavioural check → A2A hop → enforcement. Escalations render Approve/Deny
buttons (human in the loop over the WebSocket).

```bash
python scripts/run_dvmcp_native.py   # terminal 1 — live DVMCP challenges (optional)
bash scripts/run_api.sh              # terminal 2 — FastAPI + WS on :8000 (+ A2A case manager)
bash scripts/run_frontend.sh         # terminal 3 — React/Vite on http://localhost:5173
```

In-process fixture servers (clean reference, tricky-but-clean data, offline
attack stand-ins) work without the lab. Each stage shows an engine badge —
`LLM`, `heuristic`, or `LLM failed → heuristic` — so it is always visible which
detector actually decided. Every streamed event is also written to
`logs/audit_trail.jsonl` (layer `pipeline_event`), so the Streamlit dashboard
shows the same runs. `npm --prefix frontend run build` lets the API serve the UI
itself at http://127.0.0.1:8000.

## Test data & ground truth

| Source | Cases | Label | Notes |
|---|---|---|---|
| DVMCP | 10 challenges → 31 live tools | `malicious` | 1:1 port→challenge→attack-category mapping (see `dvmcp_loader.py`) |
| MCPTox | 1,312 | `malicious` | attack-only; 11 risk scopes; 36 author-flagged rows excluded |
| Benign control | 369 | `clean` | 362 real unpoisoned tools from MCPTox's 45 servers + 7 hand-written |
| Custom | backup only | either | added only if evaluation reveals a gap |

## Status

Implemented phase by phase per [`implementation_plan.md`](implementation_plan.md).
Deterministic layers (anomaly scoring, enforcement policy, metrics, interceptor
plumbing, loaders, dashboard) are fully unit-tested; LLM-backed agents (CrewAI /
ADK) require provider credentials in `.env` to execute live.
