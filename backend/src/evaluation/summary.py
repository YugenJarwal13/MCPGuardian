"""Writes ``frontend/src/data/results.json`` - the numbers the landing page shows.

Everything is derived from the per-case file of the full local-LLM run
(``reports/cases_ollama_full.jsonl``) with the same ``metrics`` / ``wilson`` helpers the
Markdown report uses, so the web page and ``docs/evaluation_report.md`` cannot disagree.
Nothing here calls a model. Hardware facts are supplied by the person who ran the job.
"""
from __future__ import annotations

import json
import statistics
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from src.config import REPO_ROOT
from src.evaluation.report import GROUPS, answered, load_run, metrics, wilson

OUT = REPO_ROOT / "frontend" / "src" / "data" / "results.json"
RUN = "ollama_full"

# Supplied by the operator of the run (not recorded in the case file).
HARDWARE = {"gpu": "NVIDIA H200 (MIG slice)", "cluster": "BMU Kubernetes cluster", "runtime": "Ollama"}


def _view(recs: list[dict], source: str) -> dict:
    out = {}
    for cfg in ("static_only", "runtime_only", "combined"):
        m = metrics(recs, source, cfg, None)
        out[cfg] = {k: m[k] for k in ("n", "tp", "fp", "fn", "precision", "recall", "f1")}
    return out


def _groups(recs: list[dict]) -> dict:
    llm, rx = metrics(recs, "primary", "combined", None), metrics(recs, "heuristic", "combined", None)
    out = {}
    for gid, label in GROUPS:
        a, b = llm["groups"].get(gid), rx["groups"].get(gid)
        if not a:
            continue
        lo, hi = wilson(a["flagged"], a["n"])
        out[gid] = {"label": label, "n": a["n"], "kind": a["kind"],
                    "llm": {"flagged": a["flagged"], "rate": a["flagged"] / a["n"], "lo": lo, "hi": hi},
                    "regex": {"flagged": b["flagged"], "rate": b["flagged"] / b["n"]}}
    return out


def _categories(recs: list[dict], top: int = 8) -> list[dict]:
    """MCPTox attack categories (largest first): share caught by the model vs the regex."""
    per = defaultdict(lambda: [0, 0, 0])
    llm = metrics(recs, "primary", "combined", None)["preds"]
    rx = metrics(recs, "heuristic", "combined", None)["preds"]
    for r, a, b in zip(recs, llm, rx):
        if r["group"] != "mcptox":
            continue
        row = per[r["category"]]
        row[0] += 1
        row[1] += a != "clean"
        row[2] += b != "clean"
    rows = [{"category": c, "n": n, "llm": l / n, "regex": x / n} for c, (n, l, x) in per.items()]
    return sorted(rows, key=lambda r: -r["n"])[:top]


def build() -> dict | None:
    run = load_run(RUN)
    if not run:
        return None
    hdr, recs = run
    ans = [r for r in recs if answered(r)]
    if not ans:
        return None
    det = load_run("deterministic")
    started, finished = hdr.get("started"), hdr.get("finished")
    minutes = None
    if started and finished:
        fmt = "%Y-%m-%dT%H:%M:%S%z"
        minutes = (datetime.strptime(finished, fmt) - datetime.strptime(started, fmt)).total_seconds() / 60
    model = Counter(r["static"].get("model") for r in ans).most_common(1)[0][0]
    lat = [r["static"]["latency_ms"] for r in ans if r["static"].get("latency_ms") and not r["static"].get("cached")]
    llm_right_regex_wrong = sum(1 for r, a, b in zip(ans, metrics(ans, "primary", "combined", None)["preds"],
                                                     metrics(ans, "heuristic", "combined", None)["preds"])
                                if r["label"] == "malicious" and a != "clean" and b == "clean")
    regex_right_llm_wrong = sum(1 for r, a, b in zip(ans, metrics(ans, "primary", "combined", None)["preds"],
                                                     metrics(ans, "heuristic", "combined", None)["preds"])
                                if r["label"] == "malicious" and b != "clean" and a == "clean")
    return {
        "run": {"name": RUN, "model": model, "prompt_version": hdr.get("prompt_version"),
                "cases": len(recs), "answered": len(ans), "unanswered": len(recs) - len(ans),
                "workers": hdr.get("args", {}).get("workers"), "duration_minutes": minutes,
                "started": started, "finished": finished, **HARDWARE,
                "median_call_seconds": statistics.median(lat) / 1000 if lat else None},
        "dataset": {"total": len(recs), "groups": {g: {"label": l, "n": n} for g, l in GROUPS
                                                     if (n := sum(1 for r in recs if r["group"] == g))}},
        "llm": _view(ans, "primary"),
        "regex": _view(ans, "heuristic"),
        "groups": _groups(ans),
        "categories": _categories(ans),
        "agreement": {"llm_caught_regex_missed": llm_right_regex_wrong,
                      "regex_caught_llm_missed": regex_right_llm_wrong},
        "regex_rules": len(__import__("src.crewai_layer.heuristics", fromlist=["x"])._DIRECTIVE_PATTERNS),
        "has_deterministic": bool(det),
    }


def write_summary() -> Path | None:
    data = build()
    if data is None:
        return None
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return OUT
