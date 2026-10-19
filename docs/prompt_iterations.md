# Prompt iteration log (CrewAI inspection agents)

Status: **v1 and v2 are both measured on two models** (local `qwen3:4b` and hosted `dots-3-note-preview`, the same
28 cases). v2 did **not** measurably beat v1 on either. See the numbers below and the full tables in [`evaluation_report.md`](evaluation_report.md).

## How the comparison was run

```bash
# the first 28 cases of the nested, balanced ordering (4 per group), identical for both prompts
LLM_PROVIDER=ollama GUARDIAN_PROMPT_VERSION=v1 python -m src.evaluation.run_eval --llm --provider ollama --prompt-version v1 --limit 28 --name ollama_v1
LLM_PROVIDER=ollama                           python -m src.evaluation.run_eval --llm --provider ollama --limit 28 --name ollama_v2_sub
```

Every verdict names the model that produced it (`qwen3:4b`, provider `ollama`). Runs are strict: a case whose
model call failed would be excluded, not relabelled; here all 28 cases were answered under both prompts.
Hosted models could not be used for this comparison: the OpenRouter account is on the free tier (50 requests/day).

## Result (qwen3:4b, 28 identical cases, combined config, detectors only)

| Prompt | Precision | Recall | MCPTox | DVMCP | Response attacks | Hard negatives (FP) | Benign real tools (FP) |
|---|---|---|---|---|---|---|---|
| v1 (zero-shot-ish) | 90.0% | 75.0% | 4/4 | 2/4 | 3/4 | 0/4 | 1/4 |
| v2 (few-shot) | 100.0% | 66.7% | 3/4 | 2/4 | 3/4 | 0/4 | 0/4 |
| Heuristic (same cases) | 85.7% | 50.0% | 2/4 | 1/4 | 3/4 | 1/4 | 0/4 |

**Reading it honestly.** v1 and v2 differ by one case in each direction (v1 made one false positive on a real
benign tool; v2 missed one MCPTox attack). With 28 cases that is **indistinguishable from noise**, so the honest
conclusion is "v2 is not shown to be better than v1 on this model". Both beat the regex on the same cases.

**DVMCP Challenge 2 under the clean prompt.** v2 quotes the Challenge 2 and Challenge 10 descriptions as examples,
so a v2 result on those tools proves little. v1 contains no DVMCP text, and under v1 the model flags *both* Challenge
2 tools **malicious (confidence 1.0)** (`get_company_data`, `search_company_database`), which the regex rates clean
and suspicious. That is the uncontaminated answer to "does the LLM catch the heuristic's known miss": **yes**.

## Hosted model (OpenRouter dots-3-note-preview, same 28 cases, 2026-10-20)

```bash
python -m src.evaluation.run_eval --llm --mcptox-n 200 --benign-n 100 --limit 28 --name prompt_v2
python -m src.evaluation.run_eval --llm --mcptox-n 200 --benign-n 100 --limit 28 --prompt-version v1 --name prompt_v1
```

All 28 cases were answered under both prompts (0 failures).

| Prompt | Precision | Recall | MCPTox | DVMCP | Response attacks | Hard negatives (FP) | Benign real tools (FP) |
|---|---|---|---|---|---|---|---|
| v1 | 83.3% | 83.3% | 4/4 | 2/4 | 4/4 | 0/4 | 2/4 |
| v2 | 90.9% | 83.3% | 4/4 | 2/4 | 4/4 | 0/4 | 1/4 |
| Heuristic (same cases) | 85.7% | 50.0% | 2/4 | 1/4 | 3/4 | 1/4 | 0/4 |

Recall is identical; v2 made one fewer false positive on a real benign tool. One case is not evidence, so the
conclusion matches the local model's: **v2 is not shown to be better than v1.** Under zero-shot v1 the hosted model
also flags both Challenge 2 tools malicious (0.98 and 1.0), a second, independent confirmation that the LLM catches
the heuristic's known miss without having seen the text.

## What each version contains

- **v1** — the original zero-shot checklist (static) and the original two-positive / two-negative few-shot prompt
  (runtime, including a changelog "ignore the deprecated v1 API" negative).
- **v2** — adds few-shot pairs for the failure modes seen on real data: a hidden directive with a secrecy clause
  (DVMCP Challenge 2), a cross-tool instruction with no tags (Challenge 10), priority-override claims, scope
  mismatch, capability words that are not intent (real benign tool wording), an injection echoed inside a
  legitimate result, a coercive rug-pull response, and instruction-like words inside ordinary data.
  MCPTox text was never used.

## Held-out discipline, and where it leaks

MCPTox (1,312 attacks) and the 362 real clean tools were never used as prompt material, so those results are held
out. **DVMCP and the hand-written response fixtures are not independent of v2**: the prompt quotes two DVMCP
descriptions and contains examples whose ideas overlap some fixtures (same author). The report states this next to
the results ("what is and is not held out"). Prefer MCPTox and v1 when asking whether the model generalises.

## Not yet done

- v1 vs v2 on a larger sample than 28 cases (hosted needs more than 50 requests/day — add credits); at n=28 only
  large effects are visible.
- A v3 built from the models' own errors (add examples from DVMCP / benign / fixtures only — never MCPTox).
  One concrete failure to learn from: `custom-resp-atk-03`, where the 4B model *quoted* the injected
  "Instruction for the summarizer" in its reasoning but still answered `clean`.
