# Observability: tracing, cost and scores

Every pipeline run is one OpenTelemetry trace. It is written to `backend/logs/traces.jsonl` and, when Langfuse keys
are set, exported to Langfuse. This page says what is recorded, how cost is counted, how to read it in Langfuse and
what to configure for production. All of it was checked against a real Langfuse project (see "Verification").

## What one run looks like

```
guardian.run                              chain     the whole run; input = server, tool, arguments; output = decision
  guardian.connect / guardian.list_tools  span
    mcp.tools_list                        tool      the tools/list call
  guardian.static_check                   guardrail inspection of the tool descriptions
    static_inspector (CrewAI)             agent     one agent run per tool
      static_inspector.llm                generation  model, prompt, reply, tokens, cost
  guardian.tool_call                      tool      the policy gate and the real call
    mcp.call_tool                         tool      arguments in, reply out (credentials masked)
  guardian.runtime_check                  guardrail inspection of the reply
    runtime_inspector (CrewAI) / runtime_inspector.llm
  guardian.behavioral_check               guardrail drift statistics
    invocation > behaviour_judge (ADK) > behaviour_judge.llm      only when drift is flagged
  guardian.a2a_hop                        span      the verdict sent to the ADK case manager over A2A
    invocation > case_manager (ADK)                 the case manager's spans, joined by trace-context propagation
  guardian.enforcement                    guardrail allow / block / escalate
```

* A model call that was answered from the local cache is a plain span ("served from cache"): it books no tokens and
  no cost, and is never counted as a model call.
* A failed or timed-out model call shows as a WARNING on its agent span, with the reason; the regex fallback's answer
  is labelled as such everywhere.
* The trace id is shown in the live console, so a run on the site can be found in Langfuse.

## Cost: what is counted, and what is not

| Figure | Where | Meaning |
|---|---|---|
| **Provider cost** | `cost_details` on every generation; score `guardian.cost_usd` | What the provider reported for the call. OpenRouter reports it; it is **0 for free-tier models**, so $0.00 is the true figure today. A local (Ollama) model reports none, so no cost is shown rather than a made-up one. |
| **Reference cost** | observation metadata `reference_cost_usd`; score `guardian.reference_cost_usd` | An **estimate**: the same tokens priced at `GUARDIAN_REF_PRICE_IN_PER_M` / `_OUT_PER_M` (default $0.30 / $1.20 per million). It shows what a run would cost on a paid model and is never mixed into the provider cost. |
| **Tokens** | usage on every generation; scores `guardian.tokens_total`, `guardian.tokens.<agent>` | Input and output tokens as the provider counted them. |

**Cost per agent:** group Langfuse's metrics by observation name. `static_inspector.llm`, `runtime_inspector.llm` and
`behaviour_judge.llm` are the three model-using agents; the case manager is deterministic and costs nothing. Each
run's trace metadata also holds a per-agent table (`usage`: calls, cached answers, tokens, cost, reference cost).

## Scores on every run

`guardian.decision`, `guardian.risk` (block 1, escalate 0.5, allow 0), `guardian.static_flagged`,
`guardian.runtime_flagged`, `guardian.behavioral_flagged`, `guardian.credential_leak`, `guardian.llm_coverage` (the
share of inspection answered by the model rather than the regex fallback), `guardian.model_calls`,
`guardian.tokens_total`, `guardian.cost_usd`, `guardian.reference_cost_usd` and one `guardian.tokens.<agent>` per agent.

## Production configuration

| Variable | Default | Purpose |
|---|---|---|
| `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY` | unset | enable the Langfuse export |
| `LANGFUSE_HOST` or `LANGFUSE_BASE_URL` | `https://cloud.langfuse.com` | EU cloud; US is `https://us.cloud.langfuse.com`; or your own server |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | unset | any other OTLP backend instead |
| `GUARDIAN_ENVIRONMENT` | `production` in public mode, else `local` | Langfuse environment, so test and real traffic never mix |
| `GUARDIAN_VERSION` | `dev` | release label shown in Langfuse (set it to the git SHA in your deploy) |
| `GUARDIAN_TRACE_SAMPLE_RATIO` | `1` | share of runs traced (0 to 1); a run that is not sampled is not in Langfuse |
| `GUARDIAN_TRACE_FILE` | `on` | `off` for containers with no persistent disk |
| `GUARDIAN_TRACE_FILE_MAX_MB` | `25` | the file rotates at this size and keeps 3 backups |
| `GUARDIAN_TRACE_QUEUE`, `GUARDIAN_TRACE_DELAY_MS` | `4096`, `2000` | export batching |
| `GUARDIAN_TRACE_SALT` | built in | salt for the hashed visitor id (`langfuse.user.id`); set your own in production |

What the code guarantees:

* **Nothing sensitive leaves the process.** One sanitising step sits in front of both the file and Langfuse: every
  string attribute and span event is scanned and credential-like values (API keys, tokens, JWTs, private keys, URLs
  with `apikey=`) are masked. Sign-in credentials never reach spans in the first place.
* **Export problems are visible.** `GET /health` returns `tracing` with the number of spans exported and failed per
  destination and the last error; failures are also logged (at most once a minute).
* **Graceful stop.** Queued spans and scores are flushed when the API stops and at interpreter exit.
* **Bounded.** Attributes are capped, the export queue is bounded, the trace file rotates, and the score sender retries
  three times and never raises into a run.
* **No library noise.** The A2A library's internal spans (about a dozen per message) are switched off, which also keeps
  the Langfuse observation count down (Langfuse bills by observation). The A2A hop itself is still traced.
* **Visitors are pseudonymous.** The per-user id is a salted hash; the address is not stored.
* **The test suite never writes to a real project** (it is excluded from Langfuse whatever keys are in the environment).

## Verification

Run against a real Langfuse project, with the model, and read back through Langfuse's API:

* a clean run, a poisoned run and an 11-call rug-pull sequence (which triggers the ADK judge);
* every run is a single trace with one root (no orphans); the case manager's spans sit under `a2a_hop`;
* every model call has model name, tokens, cost, input and output; each agent is named; the scores are all present;
* export counters showed 0 failed spans and 0 failed scores.

## Known limits

* Provider cost is **$0 because the models are free-tier**. The cost path for a paid model (a non-zero
  `usage.cost` from OpenRouter) is implemented and unit-tested but has not been exercised with a paid model.
* Local-model (Ollama) calls have tokens but no provider cost; only the reference cost applies.
* ADK's message capture uses the OpenTelemetry GenAI convention marked *experimental*; a future ADK release may rename
  those attributes, which would remove the judge's prompt and reply from Langfuse (the model, tokens and cost remain).
* Traces and scores only: there are no OpenTelemetry metrics or logs exporters.
* A run that is sampled out (`GUARDIAN_TRACE_SAMPLE_RATIO` below 1) has a trace id in the console but no trace in
  Langfuse.
* The benchmark evaluation runs call the inspectors directly and are not traced.
