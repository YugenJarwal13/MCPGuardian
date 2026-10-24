# MCP Guardian — cost and running-time estimates

Everything here is measured from the project's own records unless it is marked **estimate**. Regenerate the
numbers with `cd backend && python -m src.evaluation.cost`. No provider price list was consulted: dollar figures
are shown for three **illustrative** price points, not quotes.

## 1. What one inspection costs

The pipeline makes one model call per tool description (static check) and one per tool response (runtime check).
The behaviour layer is statistics only; its judge agent is called only when a tool drifts.

| Model (how it was served) | Calls measured | Prompt tokens / call | Completion tokens / call | Median latency / call |
|---|---|---|---|---|
| `dots-3-note-preview` (OpenRouter, free tier) | 117 | 1,020 | 780 (it reasons before answering) | **10.2 s** |
| `nemotron-3.5-lightning` (OpenRouter, free tier) | 5 (too few to rely on) | 1,710 | 633 | 7.5 s |
| `qwen3:4b` (Ollama, laptop CPU, no GPU) | 171 | 1,087 | 184 | **67.6 s** |
| `qwen3:4b` (Ollama, NVIDIA H200 MIG slice, 1 worker) | 1,748 fresh calls | n/a (not recorded in case files) | n/a | **19.2 s** (p95 27.7 s) |

Tokens come from the provider-reported usage stored in the local answer cache. The H200 run's case file records
latency but not tokens, so token totals for it are estimated with the laptop's per-call means.

## 2. The full 1,762-case evaluation

| Quantity | Value |
|---|---|
| Cases | 1,762 |
| Model calls | 1,819 (1,762 static + 57 runtime); 71 served from the cache because descriptions repeat, so **1,748 fresh calls** |
| Wall-clock on an H200 MIG slice, 1 worker | **568.9 min = 9 h 29 min** (mean 19.5 s per fresh call) |
| API spend (local model) | **$0**: GPU time only, about 9.5 hours of one MIG slice |
| Estimated tokens, `qwen3:4b` | about 1.9 M prompt + 0.3 M completion |
| Same run on a laptop CPU | about 1,748 x 67.6 s = **about 33 hours** (measured per-call latency; not run in full) |
| Same run on the hosted free tier | 1,819 calls at 50 free requests/day = **about 36 days**; with $10 of credit (1,000 requests/day) about 2 days |

**Estimated dollar cost if the same run were paid per token** (illustrative prices, USD per million tokens in/out):

| Model token profile | $0.10 / $0.40 | $0.30 / $1.20 | $1.00 / $4.00 |
|---|---|---|---|
| dots-3 (1.78 M in + 1.36 M out) | $0.72 | $2.17 | $7.23 |
| qwen3:4b profile (1.90 M in + 0.32 M out) | $0.32 | $0.96 | $3.18 |

Formula: `cost = tokens_in/1e6 x price_in + tokens_out/1e6 x price_out`. Even at the highest illustrative price the
whole benchmark costs single-digit dollars; time, not money, is the constraint.

## 3. One live run (what a visitor experiences)

For a server with *n* tools and a call that executes, the pipeline makes *n* static calls and 1 runtime call.

| Mode | Model requests | Typical end-to-end time |
|---|---|---|
| Regex rules only | 0 | **under 1 s** (A2A hop to the case manager measured at about 47 ms) |
| Hosted model (dots-3) | n + 1 | about (n + 1) x 10 s, e.g. **about 30 s** for a 2-tool server; repeats are cached and take about 1 s |
| Local model, laptop CPU | n + 1 | about (n + 1) x 68 s |
| Local model, H200 slice | n + 1 | about (n + 1) x 19 s |

Tokens per live run are about (n + 1) x 1,800 (dots-3). "Check a server" (inspection only) makes *n* calls.

## 4. Running the public site on free tiers

| Resource | Limit | How the app copes |
|---|---|---|
| OpenRouter free models | about 50 requests/day, resets 00:00 UTC | `GUARDIAN_LLM_RUNS_PER_DAY` (default 10) caps AI-inspector runs per day; after that runs continue on regex rules and say so |
| Hugging Face Space (free CPU) | 2 vCPU, 16 GB RAM, sleeps when idle | the model is not hosted there, only called over the API; first request after sleep takes a minute |
| Abuse | anyone can open the page | per-visitor rate limit (12 runs/hour) and 2 concurrent runs; internal addresses refused |

Total running cost of the deployed demo: **$0**.

## 5. What these numbers do not cover

One model per row, one run each; latencies vary with provider load. The H200 figures are for a MIG slice shared on a
cluster, not a whole GPU. Prices are illustrative.
