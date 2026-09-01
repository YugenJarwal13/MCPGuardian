# MCP Guardian — Architecture

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
| **Static-Analysis Agent** | CrewAI | Tool name, description, parameter schema at connect-time | `InspectionVerdict` — catches *tool poisoning* (instructions hidden in metadata), encoding anomalies, purpose/scope mismatch |
| **Runtime-Inspection Agent** | CrewAI | The *response* body returned by a live `call_tool` | `InspectionVerdict` — catches *indirect prompt injection* and *tool shadowing* delivered through response data |
| **Behavioral-Anomaly Agent** | Google ADK (stateful) | The statistical fingerprint of a tool across many calls | `is_anomalous` flag — catches *rug pulls*: a tool that behaved normally for N calls then suddenly changes shape/length/structure |
| **Guardrail-Enforcement Agent** | Google ADK | The combined verdicts + the requested scope | `GuardianDecision` (allow / block / escalate) — turns advisory verdicts into a hard stop, with sensitive scopes always requiring a human |
| **pipeline_manager** | Google ADK | Case lifecycle keyed by `case_id` | Persists verdicts arriving over A2A and drives enforcement |

## Design principles

- **Interception, not cooperation.** The agent under protection does not have to
  opt in — it simply talks to a `GuardedMCPClient` instead of a raw
  `ClientSession`, and everything is screened transparently.
- **Data is not a command.** The runtime auditor treats every response as
  untrusted input; instruction-adjacent words are not enough — it must find
  actual directive intent aimed at the agent.
- **Defense in depth.** The sensitive-scope check (`filesystem_write`,
  `network_egress`, `credential_access`, `code_execution`) fires *before and
  independently of* any AI verdict. Even a fully-fooled inspection stack cannot
  let one of those auto-execute.
- **Everything is auditable.** Every verdict and decision is appended to
  `logs/audit_trail.jsonl`, giving the Monitoring/Observability story a concrete,
  clickable form in the Phase 9 dashboard.
