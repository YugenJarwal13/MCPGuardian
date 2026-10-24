# MCP Guardian - Architecture

MCP Guardian is a transparent interception layer that sits between an LLM agent
and the MCP servers it uses. Every `list_tools` and `call_tool` is screened by a
pipeline of inspection agents before the caller ever sees the result.

## 3.1 Pipeline

```
                          ┌─────────────────────────────────────────────┐
   Agent (CrewAI/ADK/…)   │                MCP GUARDIAN                  │
        │                 │                                             │
        │ list_tools /    │   ┌───────────────┐                         │
        │ call_tool       │   │  MCP GATEWAY  │  GuardedMCPClient       │
        ▼                 │   │ (interceptor) │  wraps ClientSession    │
  ┌───────────┐  request  │   └──────┬────────┘                         │
  │ Guarded   │──────────▶│          │                                  │
  │ MCPClient │           │          ▼                                  │
  └───────────┘           │   ┌──────────────────────── CrewAI layer ─┐ │
        ▲                 │   │  Static-Analysis Agent  (metadata)    │ │
        │  screened       │   │  Runtime-Inspection Agent (responses) │ │
        │  result /       │   └───────────────┬───────────────────────┘ │
        │  refusal        │                   │ InspectionVerdict        │
        │                 │            A2A message (cross-framework hop) │
        │                 │                   ▼                          │
        │                 │   ┌──────────────────────── ADK layer ────┐ │
        │                 │   │  Behavioral-Anomaly Agent (fingerprint)│ │
        │                 │   │  Guardrail-Enforcement Agent           │ │
        │                 │   │  pipeline_manager (case lifecycle)     │ │
        │                 │   └───────────────┬───────────────────────┘ │
        │                 │                   │ GuardianDecision         │
        │                 │       allow / block / escalate-to-human     │
        └─────────────────┼───────────────────┘                          │
                          │        every decision -> audit_trail.jsonl   │
                          └─────────────────────────────────────────────┘
                                            │
                                            ▼
                               Streamlit audit dashboard
```

## 3.2 Agent roles

| Agent | Framework | Inspects | Signal it produces |
|---|---|---|---|
| **Static-Analysis Agent** | CrewAI | Tool name, description, parameter schema at connect-time | `InspectionVerdict` - catches *tool poisoning* (instructions hidden in metadata), encoding anomalies, purpose/scope mismatch |
| **Runtime-Inspection Agent** | CrewAI | The *response* body returned by a live `call_tool` | `InspectionVerdict` - catches *indirect prompt injection* and *tool shadowing* delivered through response data |
| **Behavioral-Anomaly Agent** | Google ADK (stateful) | The statistical fingerprint of a tool across many calls | `is_anomalous` flag - catches *rug pulls*: a tool that behaved normally for N calls then suddenly changes shape/length/structure |
| **Guardrail-Enforcement Agent** | Google ADK | The combined verdicts + the requested scope | `GuardianDecision` (allow / block / escalate) - turns advisory verdicts into a hard stop, with sensitive scopes always requiring a human |
| **pipeline_manager** | Google ADK | Case lifecycle keyed by `case_id` | Persists verdicts arriving over A2A and drives enforcement |

## Design principles

- **Interception, not cooperation.** The agent under protection does not have to
  opt in - it simply talks to a `GuardedMCPClient` instead of a raw
  `ClientSession`, and everything is screened transparently.
- **Data is not a command.** The runtime auditor treats every response as
  untrusted input; instruction-adjacent words are not enough - it must find
  actual directive intent aimed at the agent.
- **Defense in depth.** The sensitive-scope check (`filesystem_write`,
  `network_egress`, `credential_access`, `code_execution`) fires *before and
  independently of* any AI verdict. Even a fully-fooled inspection stack cannot
  let one of those auto-execute.
- **Everything is auditable.** Every verdict and decision is appended to
  `backend/logs/audit_trail.jsonl`, giving the Monitoring/Observability story a concrete,
  clickable form in the Phase 9 dashboard.

## 3.3 Agentic design patterns used

| Pattern | Where it is in the code | Why this pattern |
|---|---|---|
| **Gateway / guardrail (interceptor)** | `backend/src/mcp_gateway/interceptor.py` (`GuardianInterceptor`, `GuardedMCPClient`) | The agent never talks to a tool server directly; every `tools/list` and `tools/call` passes the checks first. |
| **Sequential pipeline** | `backend/src/api/runner.py` (stages in a fixed order) | Each stage consumes the previous stage's output: static verdict -> policy gate -> runtime verdict -> behaviour -> case. |
| **Specialised agents (role-based)** | `backend/src/crewai_layer/agents/` (Metadata Auditor, Response Auditor) | Two narrow roles with strict, typed outputs are more reliable than one generalist. |
| **LLM-as-judge on top of statistics** | `backend/src/adk_layer/behavioral_anomaly_agent.py` | Cheap Welford statistics run on every call; the ADK judge agent is only invoked when they flag drift. |
| **Agent-to-agent hand-off (A2A)** | `backend/src/a2a_bridge/` | The inspector verdict is sent as an A2A message to a separate ADK case-manager agent, so the two frameworks interoperate over a real protocol. |
| **Human-in-the-loop** | `escalate` decisions in `backend/src/adk_layer/callbacks/enforcement_callbacks.py`, approval panel in the UI | Ambiguous or sensitive calls pause until a person approves or denies. |
| **Graceful degradation** | `backend/src/llm_chain.py`, `backend/src/crewai_layer/crew.py` | Model chain with fallbacks; a failed or slow model is labelled (`heuristic_fallback`, `timeout`) and never silently replaced. |
| **Shared state** | ADK `SqliteSessionService`, state keys `app:case:<id>` | The case manager keeps durable per-case state that later calls read. |

## 3.4 State, structured output, callbacks and observability

* **Context sharing and state.** The CrewAI static verdict is kept by the interceptor and feeds the runtime stage
  and the policy; the combined verdict is serialised as a `GuardianVerdictMessage`, sent over A2A, and stored by
  the ADK case manager in session state (`app:case:<id>`). Tool fingerprints persist per tool for rug-pull detection.
* **Structured output (Pydantic).** `InspectionVerdict` (CrewAI `output_pydantic`), `RugPullJudgement` (ADK
  `output_schema`), `GuardianVerdictMessage` (A2A) and the typed `PipelineEvent` stream. The evaluation report and
  `frontend/src/data/results.json` are generated tables/JSON.
* **Callbacks for monitoring and validation.** `backend/src/monitoring.py`: CrewAI `step_callback` / `task_callback`
  and ADK `before/after_agent`, `before/after_model`, `on_model_error`, `after_tool`, `on_tool_error` callbacks write
  intermediate outputs and errors to `logs/audit_trail.jsonl` and to the active trace span. ADK's
  `before_tool_callback` enforces the policy (`enforcement_callbacks.py`). Pydantic validates every verdict.
* **Guardrails.** Content guardrails on tool metadata and responses are the core of the product. The input guard
  (`backend/src/security/input_guard.py`) validates user-supplied tool arguments and URLs (size, shape, control
  characters, instruction-injection phrasing, abusive language). In public deployments
  (`backend/src/security/public_mode.py`) internal addresses are refused (SSRF), visitors are rate-limited and the
  AI-inspector budget is capped.
* **Observability and provenance.** `backend/src/observability.py`: OpenTelemetry traces, one trace per run, a span
  per stage and per model call (model, tokens, latency, cache hit), written to `logs/traces.jsonl` and optionally
  exported to Langfuse (`LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST`) or any OTLP endpoint. Google
  ADK's own spans land in the same provider. The trace id is carried on every event, in the audit trail and in the
  live console.
* **Evaluation and cost.** `docs/evaluation_report.md` (accuracy) and `docs/cost_and_runtime.md` (tokens, time, money).
