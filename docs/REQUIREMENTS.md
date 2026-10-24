# Project requirements: where each one is met

An honest map from the course's minimum requirements to the code and the evidence. "Partial" means partly
met, with the gap stated.

| # | Requirement | Status | Evidence |
|---|---|---|---|
| 1 | Context sharing and state updates between agents | Met | The CrewAI static verdict is held by the interceptor and feeds the policy and the runtime stage; the combined verdict goes over A2A and is stored in ADK session state (`app:case:<id>`, SQLite) by the case manager. Tool fingerprints persist per tool. See `docs/architecture.md` §3.4. The CrewAI inspectors exchange data through the gateway, not through CrewAI's own memory. |
| 2 | At least two external tools via MCP | Met | Real MCP servers over SSE and streamable HTTP: the ten DVMCP lab servers, calculator / weather / notes / fetch fixtures, and public servers (DeepWiki, Microsoft Learn, GitMCP) through the "Check a server" page. |
| 3 | Structured output with Pydantic | Met | `InspectionVerdict` (CrewAI `output_pydantic`), `RugPullJudgement` (ADK `output_schema`), `GuardianVerdictMessage` (A2A), typed `PipelineEvent`; Markdown report and JSON results. |
| 4 | Suitable agentic design patterns | Met | `docs/architecture.md` §3.3 lists each pattern and where it lives. |
| 5 | Monitoring with callbacks | Met | `backend/src/monitoring.py`: CrewAI step/task callbacks; ADK agent, model, tool and error callbacks; ADK `before_tool_callback` enforcement. Output goes to `logs/audit_trail.jsonl` and the active trace. Test: `tests/test_observability.py`. |
| 6 | Agent-to-agent communication with A2A, interoperating frameworks | Met | The ADK case manager is served with `to_a2a` and called over HTTP with `a2a-sdk` from the CrewAI-based pipeline (`backend/src/a2a_bridge/`). The A2A client is gateway code, not a CrewAI agent itself. |
| 7 | CrewAI and ADK only | Met | No other agent framework is used. LiteLLM (an ADK dependency), `a2a-sdk` and the MCP SDK are libraries. |
| 8 | Guardrails and data-validation callbacks | Met, with a stated limit | Content guardrails on tool descriptions and responses (the product itself); Pydantic validation of every verdict; ADK enforcement callback; **input guard** on user-supplied tool arguments and URLs (`backend/src/security/input_guard.py`); SSRF block, rate limits and a daily AI budget on the public site (`public_mode.py`); inspect-only mode for dangerous lab servers. There is no chat input in this app, so "user prompt screening" applies to tool arguments and URLs. The input guard is rule-based and unevaluated. Tests: `test_input_guard.py`, `test_api_guards.py`. |
| 9 | Observability (tracing, auditability, provenance) | Met | `backend/src/observability.py`: OpenTelemetry trace per run, a span per stage and per model call, written to `logs/traces.jsonl`; exported to **Langfuse** when `LANGFUSE_*` keys are set (tested locally against the file exporter; a live Langfuse project has not been connected from this repository). Trace id is on every event and audit record and shown in the live console. |
| 10 | End-to-end performance evaluation, cost and running-time estimates | Met | `docs/evaluation_report.md` (1,762 cases, confidence intervals, baseline comparison, latency); `docs/cost_and_runtime.md` (tokens, time, illustrative dollars; regenerate with `python -m src.evaluation.cost`). Token totals for the H200 run are estimates (the case files do not store tokens). |
| 11 | Deploy on a cloud platform | Ready, deploy step is yours | `Dockerfile`, `deploy/start.sh`, `deploy/hf/README.md`, `deploy/push_to_hf.sh` and `.github/workflows/ci.yml` are in the repo for a free Hugging Face Space. The image has not been built in this repository's environment (Docker is not installed there); the same server configuration was run locally and exercised end to end. Requirement 11 is satisfied once the Space is pushed. |

## Known limits worth stating

* Static analysis cannot see flaws that live in a server's code (DVMCP recall is 16%).
* One model, one full run; the hosted-model run and the prompt v1-vs-v2 comparison are samples.
* Rate limits and budgets are per process and in memory.
