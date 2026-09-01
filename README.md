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

Bring up the DVMCP challenge lab (Docker required) and the benchmark:

```bash
bash scripts/setup_dvmcp.sh
bash scripts/setup_mcptox.sh
```

Launch the dashboard:

```bash
streamlit run src/dashboard/app.py
```

## Test data & ground truth

| Source | Cases | Label | Notes |
|---|---|---|---|
| DVMCP | 10 challenges → 10+ tools | `malicious` | 1:1 port→challenge→attack-category mapping (see `dvmcp_loader.py`) |
| MCPTox | ~1,312 | `malicious` | attack-only dataset; 10 risk categories |
| Benign control | 5–10 | `clean` | hand-assembled; the only way to measure false positives |
| Custom | backup only | either | added only if evaluation reveals a gap |

## Status

Implemented phase by phase per [`implementation_plan.md`](implementation_plan.md).
Deterministic layers (anomaly scoring, enforcement policy, metrics, interceptor
plumbing, loaders, dashboard) are fully unit-tested; LLM-backed agents (CrewAI /
ADK) require provider credentials in `.env` to execute live.
