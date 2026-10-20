"""Builds ``docs/evaluation_report.md`` (and ``reports/summary.json``) from the
per-case files written by ``run_eval.py``. Nothing here calls a model.

Conventions
  * detection = a case predicted ``suspicious`` or ``malicious`` (both leave the
    ALLOW path); positives are ``ground_truth_label == malicious``.
  * ``detectors`` view: only the static/runtime verdicts decide.
    ``policy`` view: also applies the sensitive-scope escalation rule (schema-based);
    ``policy_keyword`` is the OLD keyword rule, shown only for the before/after.
  * An LLM case counts only if EVERY LLM call for it was answered by the model
    (engine ``llm``). Anything else is ``unanswered`` and excluded from LLM numbers
    (never relabelled), and the same cases are used for the heuristic comparison.
"""
from __future__ import annotations

import json
import math
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Optional

from src.adk_layer.callbacks.enforcement_callbacks import GuardianDecision, combine_verdicts
from src.config import BACKEND_ROOT, REPO_ROOT, allowlist
from src.crewai_layer.schemas import InspectionVerdict

REPORTS_DIR = BACKEND_ROOT / "src" / "evaluation" / "reports"
CONFIGS = {"static_only": (True, False), "runtime_only": (False, True), "combined": (True, True)}
GROUPS = [
    ("mcptox", "MCPTox attacks (metadata)"), ("dvmcp", "DVMCP live tools"),
    ("custom_atk", "Response attacks (custom)"), ("custom_hn", "Hard negatives (custom, clean)"),
    ("custom_ben", "Plain benign responses (custom)"), ("benign_real", "Benign real tools (MCPTox clean)"),
    ("benign_hand", "Benign hand-written tools"),
]
_ALLOW = allowlist()


# --------------------------------------------------------------------------- io
def load_run(name: str) -> Optional[tuple[dict, list[dict]]]:
    path = REPORTS_DIR / f"cases_{name}.jsonl"
    if not path.exists():
        return None
    header, recs = {}, []
    for line in path.read_text(encoding="utf-8").splitlines():
        obj = json.loads(line)
        if "_header" in obj:
            header = obj["_header"]
        else:
            recs.append(obj)
    return header, recs


def answered(rec: dict) -> bool:
    return rec["static"]["engine"] == "llm" and (rec["runtime"] is None or rec["runtime"]["engine"] == "llm")


# --------------------------------------------------------------------------- stats
def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, centre - half), min(1.0, centre + half))


def _pct(x: Optional[float], digits: int = 1) -> str:
    return "—" if x is None else f"{x * 100:.{digits}f}%"


def _rate_cell(k: int, n: int) -> str:
    if n == 0:
        return "—"
    lo, hi = wilson(k, n)
    return f"{k / n * 100:.1f}% ({k}/{n}; CI {lo * 100:.0f}–{hi * 100:.0f})"


# --------------------------------------------------------------------------- decisions
def _iv(label: str) -> InspectionVerdict:
    return InspectionVerdict(verdict=label, confidence=0.5, reasoning="-")


def decide(rec: dict, source: str, cfg: str, scope_mode: Optional[str]) -> str:
    """Predicted label (clean/suspicious/malicious) for one case.

    source: "primary" (the run's own engine) or "heuristic"."""
    use_static, use_runtime = CONFIGS[cfg]
    if source == "heuristic":
        sv = rec["heuristic"]["static"] if use_static else None
        rv = rec["heuristic"].get("runtime") if use_runtime else None
    else:
        sv = rec["static"]["verdict"] if use_static else None
        rv = rec["runtime"]["verdict"] if (use_runtime and rec["runtime"]) else None
    scope = None
    if scope_mode == "schema":
        scope = rec.get("scope")
    elif scope_mode == "keyword":
        scope = rec.get("scope_keyword")
    decision = combine_verdicts(_iv(sv) if sv else None, _iv(rv) if rv else None, False, scope, _ALLOW)
    return {GuardianDecision.BLOCK: "malicious", GuardianDecision.ESCALATE: "suspicious",
            GuardianDecision.ALLOW: "clean"}[decision]


def metrics(records: list[dict], source: str, cfg: str, scope_mode: Optional[str]) -> dict:
    preds = [decide(r, source, cfg, scope_mode) for r in records]
    tp = sum(1 for r, p in zip(records, preds) if r["label"] == "malicious" and p != "clean")
    fp = sum(1 for r, p in zip(records, preds) if r["label"] == "clean" and p != "clean")
    fn = sum(1 for r, p in zip(records, preds) if r["label"] == "malicious" and p == "clean")
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    f1 = (2 * precision * recall / (precision + recall)) if precision and recall else (0.0 if precision is not None and recall is not None else None)
    groups: dict[str, dict] = {}
    for g, _ in GROUPS:
        idx = [i for i, r in enumerate(records) if r["group"] == g]
        if idx:
            flagged = sum(1 for i in idx if preds[i] != "clean")
            groups[g] = {"n": len(idx), "flagged": flagged,
                         "kind": "recall" if records[idx[0]]["label"] == "malicious" else "fpr"}
    return {"n": len(records), "tp": tp, "fp": fp, "fn": fn, "precision": precision, "recall": recall,
            "f1": f1, "groups": groups, "preds": preds}


def _latency(records: list[dict], stage: str) -> Optional[dict]:
    vals = [r[stage]["latency_ms"] for r in records
            if r.get(stage) and r[stage].get("engine") == "llm" and r[stage].get("latency_ms")]
    if not vals:
        return None
    vals.sort()
    return {"n": len(vals), "mean": statistics.mean(vals), "median": statistics.median(vals),
            "p95": vals[min(len(vals) - 1, int(0.95 * len(vals)))]}


# --------------------------------------------------------------------------- tables
def _prf_table(rows: list[tuple[str, list[dict], str]], scope_mode: Optional[str]) -> list[str]:
    out = ["| Run | Config | n | Precision | Recall | F1 |", "|---|---|---|---|---|---|"]
    for label, recs, source in rows:
        for cfg in CONFIGS:
            m = metrics(recs, source, cfg, scope_mode)
            out.append(f"| {label} | {cfg} | {m['n']} | {_pct(m['precision'])} | {_pct(m['recall'])} | "
                       f"{'—' if m['f1'] is None else f'{m['f1']:.3f}'} |")
    return out


def _group_table(rows: list[tuple[str, list[dict], str]], cfg: str, scope_mode: Optional[str]) -> list[str]:
    heads = [lbl for g, lbl in GROUPS]
    out = ["| Run | " + " | ".join(heads) + " |", "|---|" + "---|" * len(heads)]
    for label, recs, source in rows:
        m = metrics(recs, source, cfg, scope_mode)
        cells = []
        for g, _ in GROUPS:
            gm = m["groups"].get(g)
            cells.append(_rate_cell(gm["flagged"], gm["n"]) if gm else "—")
        out.append(f"| {label} | " + " | ".join(cells) + " |")
    return out


def _runs() -> dict:
    names = ["deterministic", "llm", "ollama", "ollama_v1", "ollama_v2_sub", "ollama_mcptox",
             "prompt_v1", "prompt_v2"]
    # any full-set local run, e.g. cases_ollama_full.jsonl (qwen3:4b), cases_ollama_full_14b.jsonl
    names += sorted(p.stem[len("cases_"):] for p in REPORTS_DIR.glob("cases_ollama_full*.jsonl"))
    return {n: load_run(n) for n in names}


def _answering_model(records: list[dict]) -> tuple[str, str]:
    """(provider, model) that produced most of a run's LLM verdicts."""
    c = Counter()
    for r in records:
        for st in ("static", "runtime"):
            if r.get(st) and r[st].get("engine") == "llm":
                c[(r[st].get("provider") or "?", r[st].get("model") or "?")] += 1
    return c.most_common(1)[0][0] if c else ("?", "?")


def _label_for(records: list[dict]) -> str:
    provider, model = _answering_model(records)
    pretty = {"openrouter": "OpenRouter", "ollama": "Ollama"}.get(provider, provider)
    return f"LLM · {pretty} {model.split('/')[-1].replace(':free', '')}"


def _llm_runs(runs: dict) -> list[tuple[str, dict, list[dict], list[dict]]]:
    """[(label, header, all_records, answered_records)] for every LLM run that has answers."""
    out = []
    full_runs = sorted(n for n in runs if n.startswith("ollama_full"))
    for name in ("llm", "ollama", *full_runs):
        run = runs.get(name)
        if not run:
            continue
        hdr, recs = run
        ans = [r for r in recs if answered(r)]
        if ans:
            out.append((_label_for(ans), hdr, recs, ans))
    return out


def _agree_table(label: str, answered_recs: list[dict]) -> list[str]:
    """Where the LLM and the regex disagree, per group (combined config, detectors only)."""
    right_llm, right_regex = defaultdict(list), defaultdict(list)
    for r in answered_recs:
        pos = r["label"] == "malicious"
        lp = decide(r, "primary", "combined", None) != "clean"
        hp = decide(r, "heuristic", "combined", None) != "clean"
        if lp == pos and hp != pos:
            right_llm[r["group"]].append(r)
        if hp == pos and lp != pos:
            right_regex[r["group"]].append(r)
    lines = [f"**{label}**", "", "| Group | LLM right, regex wrong | Regex right, LLM wrong |", "|---|---|---|"]
    for g, lbl in GROUPS:
        if any(r["group"] == g for r in answered_recs):
            lines.append(f"| {lbl} | {len(right_llm[g])} | {len(right_regex[g])} |")
    worse = [r for lst in right_regex.values() for r in lst]
    if worse:
        lines += ["", "Cases where the regex was right and the LLM wrong:", ""]
        for r in worse[:8]:
            st = r["runtime"] if (r["runtime"] and r["group"].startswith("custom")) else r["static"]
            lines.append(f"- `{r['case_id']}` ({r['label']}): LLM said **{st['verdict']}** — “{st['reasoning'][:150].strip()}…”")
    lines.append("")
    return lines


# --------------------------------------------------------------------------- report
def write_report() -> Path:
    runs = _runs()
    det = runs["deterministic"]
    llm_runs = _llm_runs(runs)
    lines: list[str] = ["# MCP Guardian — Evaluation Report", ""]

    if det:
        det_recs = det[1]
        counts = Counter(r["group"] for r in det_recs)
        lines += [
            f"**Data.** {len(det_recs)} cases: " + ", ".join(f"{counts[g]} {lbl}" for g, lbl in GROUPS if counts[g])
            + ". DVMCP tools were read live from the running lab; MCPTox is the real benchmark "
            "(1,312 valid cases) plus its own 362 clean tools; the 50 response cases are hand-written "
            "(`backend/src/data/custom_fixtures/response_cases.py`).", ""]

    # ---- which LLM runs exist
    if not llm_runs:
        lines += ["> **No LLM run has produced answers yet** — run `python -m src.evaluation.run_eval --llm`.", ""]
    else:
        lines += ["## The LLM runs in this report", "",
                  "| Run | Model | Prompt | Selected | Scored | Fully answered by the LLM | Unanswered |",
                  "|---|---|---|---|---|---|---|"]
        for label, hdr, recs, ans in llm_runs:
            lines.append(f"| {hdr['name']} | {label[6:]} | {hdr.get('prompt_version')} | {hdr['n_selected']} | "
                         f"{len(recs)} | **{len(ans)}** | {len(recs) - len(ans)} |")
        lines += ["",
                  "Every verdict names the provider and model that produced it. Runs are **strict**: no silent fallback "
                  "to another model or to the heuristic. A case whose LLM call failed (or whose run stopped when a "
                  "quota ran out) is *unanswered*, is excluded from the LLM numbers, and is never relabelled. The "
                  "heuristic is always compared on exactly the cases the LLM answered.", ""]

    if llm_runs:
        lines += ["## Read this first: what is and is not held out", "",
                  "The **v2 prompt contains few-shot examples** (`backend/src/crewai_layer/tasks/`). Their sources: the literal text of "
                  "two DVMCP tool descriptions (Challenge 2 `get_company_data`, Challenge 10 `malicious_check_system_status`), "
                  "and hand-written response examples whose ideas overlap several of the 50 response fixtures (the same "
                  "author wrote both; e.g. a README \"ignore the compiler warnings\" negative and a customer-quote "
                  "negative). So under v2:", "",
                  "| Benchmark | Clean test of the LLM? |", "|---|---|",
                  "| MCPTox attacks (metadata) | **Yes** — never used in any prompt |",
                  "| Benign real tools (MCPTox clean) | **Yes** — never used in any prompt |",
                  "| DVMCP Challenge 2 / 10 | **No under v2** — their text is in the prompt; use the **v1 (zero-shot)** run below |",
                  "| Custom response fixtures | **Partly** — similar ideas appear in the examples; v1 is the cleaner estimate |", "",
                  "v1 contains only the two original positive and two negative examples from the project brief (one is a "
                  "changelog line similar to fixture `custom-resp-hn-01`). Prefer the MCPTox and v1 numbers when asking "
                  "\"does the LLM generalise?\".", ""]

    # ---- headline per LLM run
    for label, hdr, recs, ans in llm_runs:
        rows = [(label, ans, "primary"), ("Heuristic — same cases", ans, "heuristic")]
        lines += [f"## Headline — {label} vs the deterministic baseline (detectors only)", "",
                  "Only the static/runtime verdicts decide. Group cells show recall (attack groups) or false-positive "
                  "rate (clean groups) with Wilson 95% intervals.", ""]
        lines += _prf_table(rows + ([("Heuristic — full set", det[1], "primary")] if det else []), None)
        lines += ["", "Per group, combined config:", ""]
        lines += _group_table(rows, "combined", None)
        lines += ["", "Runtime inspection on tool responses (`runtime_only`):", ""]
        lines += _group_table(rows, "runtime_only", None)
        lines.append("")

    # ---- head-to-head on common cases
    if len(llm_runs) >= 2:
        ids = set.intersection(*[{r["case_id"] for r in ans} for _, _, _, ans in llm_runs])
        common = {label: [r for r in ans if r["case_id"] in ids] for label, _, _, ans in llm_runs}
        first = next(iter(common.values()))
        lines += [f"## Head-to-head on the {len(first)} cases every LLM answered", "",
                  "Identical cases for every row, so the rows are directly comparable.", ""]
        rows = [(lbl, recs, "primary") for lbl, recs in common.items()] + [("Heuristic", first, "heuristic")]
        lines += _prf_table(rows, None)
        lines += ["", "Per group, combined config:", ""]
        lines += _group_table(rows, "combined", None)
        lines.append("")

    # ---- widened MCPTox sample (local model)
    wide = runs.get("ollama_mcptox")
    if wide:
        wans = [r for r in wide[1] if answered(r)]
        if wans:
            lines += ["## MCPTox recall at a larger sample (local model, prompt v2)", "",
                      "MCPTox is the cleanest generalisation test (never used in any prompt). This run widens it to "
                      f"{len(wans)} attack cases answered by the model.", "",
                      "| Detector | Recall on MCPTox attacks (static) |", "|---|---|"]
            for lbl, src in ((_label_for(wans), "primary"), ("Heuristic — same cases", "heuristic")):
                m = metrics(wans, src, "static_only", None)["groups"].get("mcptox", {"flagged": 0, "n": 0})
                lines.append(f"| {lbl} | {_rate_cell(m['flagged'], m['n'])} |")
            full = next((r for r in [det] if r), None)
            if full:
                m = metrics(full[1], "primary", "static_only", None)["groups"]["mcptox"]
                lines.append(f"| Heuristic — all {m['n']} MCPTox cases | {_rate_cell(m['flagged'], m['n'])} |")
            lines.append("")

    # ---- policy view and the scope before/after
    if det:
        recs = det[1]
        lines += ["## Deployed policy and the scope rule", "",
                  "The policy additionally escalates any tool whose *parameter schema* grants a sensitive scope "
                  "(credential, code execution, network egress, file write). Before Phase 12 this was a keyword match "
                  "over the whole description. Same data, both rules (deterministic verdicts, combined config):", "",
                  "| Rule | Benign real tools escalated | Benign hand-written escalated | MCPTox tools with a scope | MCPTox policy recall |",
                  "|---|---|---|---|---|"]
        for mode, nm in (("keyword", "keyword (old)"), ("schema", "schema-based (new)"), (None, "none (detectors only)")):
            m = metrics(recs, "primary", "combined", mode)
            g = m["groups"]
            scope_key = "scope_keyword" if mode == "keyword" else "scope"
            mt = [r for r in recs if r["group"] == "mcptox"]
            scoped = sum(1 for r in mt if r.get(scope_key)) if mode else 0
            lines.append(f"| {nm} | {_rate_cell(g['benign_real']['flagged'], g['benign_real']['n'])} | "
                         f"{_rate_cell(g['benign_hand']['flagged'], g['benign_hand']['n'])} | "
                         f"{scoped}/{len(mt)} | {_rate_cell(g['mcptox']['flagged'], g['mcptox']['n'])} |")
        lines += ["", "Benign tools escalated by the schema rule genuinely take a path+content, URL, command or secret "
                  "parameter (e.g. `write_file`), so the policy is *designed* to ask a human about them; that is a cost, "
                  "not a detector error. The old rule's extra \"recall\" on MCPTox came from keywords in the poisoned "
                  "descriptions, not from detection.", ""]
        for label, hdr, recs2, ans in llm_runs:
            lines += [f"Policy view on the answered cases — {label}:", ""]
            lines += _prf_table([(label, ans, "primary"), ("Heuristic — same cases", ans, "heuristic")], "schema")
            lines.append("")

    # ---- latency
    lines += ["## Latency and engines", "",
              "| Run | Stage | Engine | n | Mean | Median | p95 |", "|---|---|---|---|---|---|---|"]
    if det:
        ws = sorted(r["static"]["wall_ms"] for r in det[1])
        wr = sorted(r["runtime"]["wall_ms"] for r in det[1] if r["runtime"])
        lines.append(f"| Deterministic | static | heuristic | {len(ws)} | {statistics.mean(ws):.2f} ms | "
                     f"{statistics.median(ws):.2f} ms | {ws[int(.95 * len(ws)) - 1]:.2f} ms |")
        if wr:
            lines.append(f"| Deterministic | runtime | heuristic | {len(wr)} | {statistics.mean(wr):.2f} ms | "
                         f"{statistics.median(wr):.2f} ms | {wr[max(0, int(.95 * len(wr)) - 1)]:.2f} ms |")
    for label, hdr, recs, ans in llm_runs:
        for stage in ("static", "runtime"):
            lat = _latency(recs, stage)
            if lat:
                lines.append(f"| {label[6:]} | {stage} | llm (model call) | {lat['n']} | {lat['mean'] / 1000:.1f} s | "
                             f"{lat['median'] / 1000:.1f} s | {lat['p95'] / 1000:.1f} s |")
    lines += ["", "LLM latency is the model call as measured when it was made (cached answers keep their original "
              "timing) and excludes CrewAI's own overhead. Free OpenRouter models share capacity, so latency varies "
              "call to call; the local model runs on a CPU-only laptop. The heuristic costs microseconds — "
              "that gap is the real price of LLM inspection on every tool call.", ""]
    for label, hdr, recs, ans in llm_runs:
        prov = Counter()
        for r in recs:
            for st in ("static", "runtime"):
                if r.get(st) and r[st].get("engine") == "llm":
                    prov[(r[st].get("provider"), r[st].get("model"), r[st].get("method"))] += 1
        lines += [f"Model verdicts in run `{hdr['name']}`:", "", "| Provider | Model | Structured method | LLM verdicts |", "|---|---|---|---|"]
        lines += [f"| {p} | {m} | {meth} | {n} |" for (p, m, meth), n in prov.most_common()]
        lines.append("")

    # ---- disagreements + challenge 2
    for label, hdr, recs, ans in llm_runs:
        lines += [f"## {label} vs the regex: where they disagree", ""]
        lines += _agree_table(label, ans)
        ch2 = [r for r in recs if r["case_id"].startswith("dvmcp-ch2-")]
        if ch2:
            lines += ["DVMCP Challenge 2 — the heuristic's known miss:", "",
                      "| Case | Tool | LLM verdict | Confidence | Engine / model | Heuristic |", "|---|---|---|---|---|---|"]
            for r in ch2:
                s = r["static"]
                lines.append(f"| {r['case_id']} | {r['tool']} | **{s['verdict']}** | {s['confidence']:.2f} | "
                             f"{s['engine']} / {(s.get('model') or '-').split('/')[-1]} | {r['heuristic']['static']} |")
            lines.append("")

    # ---- prompt v1 vs v2
    for n1, n2, who in (("ollama_v1", "ollama_v2_sub", "Ollama"), ("prompt_v1", "prompt_v2", "OpenRouter")):
        p1, p2 = runs[n1], runs[n2]
        if not (p1 and p2):
            continue
        a1 = [r for r in p1[1] if answered(r)]
        a2 = {r["case_id"]: r for r in p2[1] if answered(r)}
        a1 = [r for r in a1 if r["case_id"] in a2]
        a2 = [a2[r["case_id"]] for r in a1]
        if not a1:
            continue
        lines += [f"## Prompt v1 vs v2 — measured with {who}", "",
                  f"The same {len(a1)} cases answered under both prompts (a nested balanced prefix of the ordering).", ""]
        lines += _prf_table([("v1 (zero-shot)", a1, "primary"), ("v2 (few-shot)", a2, "primary"),
                             ("Heuristic — same cases", a1, "heuristic")], None)
        lines += ["", "Per group, combined config:", ""]
        lines += _group_table([("v1", a1, "primary"), ("v2", a2, "primary"), ("Heuristic", a1, "heuristic")],
                               "combined", None)
        lines.append("")

    # ---- limitations
    lines += ["## Honest limitations", "",
              "- **The LLM was evaluated on small samples, not all 1,762 cases.** The OpenRouter account is on the "
              "free tier, which allows **50 requests per day** for `:free` models (HTTP 429 `free-models-per-day`, "
              "resetting 00:00 UTC; $10 of credits raises it to 1,000/day). The run therefore stopped after a few dozen "
              "cases; every answer is cached, so re-running the same command resumes it. The local model "
              "(CPU-only laptop, 60–100 s per call) was run on a balanced prefix for the same reason.",
              "- **Samples are small, so intervals are wide.** A group of 5–10 cases cannot support a precise rate; read "
              "the Wilson intervals, and treat differences smaller than them as unproven.",
              "- **Models are free-tier or small and non-deterministic.** Latency, availability and even verdicts can "
              "differ between runs. A slot that returns a permanent error (Inkling Small: HTTP 403 \"only available on "
              "agentic harnesses\") is skipped automatically.",
              "- **The v2 few-shot prompt is not independent of DVMCP and the response fixtures.** It quotes two DVMCP "
              "descriptions and uses examples that resemble some fixtures (see \"what is and is not held out\"). MCPTox "
              "and the real benign tools were never used as prompt material, so those numbers are held out.",
              "- **DVMCP labels are per challenge.** Every tool on a challenge server is labelled malicious although several "
              "(e.g. `ping_host`) have benign metadata and are exploitable only through their implementation; static "
              "analysis should not flag those, which caps DVMCP recall for any detector.",
              "- **The response benchmark was written by the same project** (independently of the heuristics, not tuned "
              "against either detector). It is small (50 cases); treat it as a measurement of the data-vs-directive "
              "distinction, not as a field-wide benchmark.",
              "- **The behavioural layer needs a call history**, so it does not contribute to these single-shot metrics; "
              "its rug-pull time-to-detection (1 call) comes from a synthetic scenario. DVMCP challenge 4's live rug "
              "pull rewrites a tool description that current MCP servers cache, so it is not observable end to end.",
              "- MCPTox is attack-only; its 36 author-flagged `wrong_data` rows are excluded (1,348 → 1,312).",
              "- The regex heuristic was **not** tuned after seeing any of these numbers.",
              ""]

    out = REPO_ROOT / "docs" / "evaluation_report.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out
