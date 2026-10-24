"""Cost and running-time figures, measured from what the project actually recorded.

    python -m src.evaluation.cost

* call counts and per-call latency come from the per-case file of the full run (``cases_ollama_full.jsonl``);
* tokens per call come from the local LLM answer cache (``logs/llm_cache.jsonl``), which stores the
  provider-reported usage for every real call made on this machine. The case files do not store tokens,
  so total tokens for the full run are an ESTIMATE (calls x mean tokens per call).
Prices are not looked up anywhere: dollar figures are shown for illustrative price points only.
"""
from __future__ import annotations

import json
import statistics
from collections import defaultdict

from src.config import BACKEND_ROOT
from src.evaluation.report import REPORTS_DIR, load_run

PRICE_POINTS = [(0.10, 0.40), (0.30, 1.20), (1.00, 4.00)]       # USD per million tokens (in, out): illustrative


def token_stats() -> dict:
    by = defaultdict(list)
    path = BACKEND_ROOT / "logs" / "llm_cache.jsonl"
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                meta = json.loads(line).get("meta", {})
            except ValueError:
                continue
            t = meta.get("tokens") or {}
            if t.get("prompt") is not None and t.get("completion") is not None and meta.get("latency_ms"):
                by[(meta.get("provider"), meta.get("model"))].append((t["prompt"], t["completion"], meta["latency_ms"]))
    return {k: {"n": len(v), "prompt": statistics.mean(x[0] for x in v), "completion": statistics.mean(x[1] for x in v),
                "median_s": statistics.median(x[2] for x in v) / 1000} for k, v in by.items()}


def full_run_stats() -> dict | None:
    run = load_run("ollama_full")
    if not run:
        return None
    hdr, recs = run
    calls = [(st, r[st]) for r in recs for st in ("static", "runtime") if r.get(st)]
    fresh = [c for _, c in calls if not c.get("cached") and c.get("latency_ms")]
    lat = sorted(c["latency_ms"] for c in fresh)
    return {"cases": len(recs), "calls": len(calls), "cached": sum(1 for _, c in calls if c.get("cached")),
            "fresh": len(fresh), "median_s": statistics.median(lat) / 1000,
            "p95_s": lat[int(0.95 * (len(lat) - 1))] / 1000, "mean_s": statistics.mean(lat) / 1000}


def main() -> None:
    fr, ts = full_run_stats(), token_stats()
    print("full run:", fr)
    for k, v in ts.items():
        print(k, {a: round(b, 1) for a, b in v.items()})
    if fr:
        for (prov, model), v in ts.items():
            n_in, n_out = fr["fresh"] * v["prompt"] / 1e6, fr["fresh"] * v["completion"] / 1e6
            print(f"estimate for {model}: {n_in:.2f} M in + {n_out:.2f} M out over {fr['fresh']} fresh calls")
            for p_in, p_out in PRICE_POINTS:
                print(f"   at ${p_in}/${p_out} per M: ${n_in * p_in + n_out * p_out:.2f}")


if __name__ == "__main__":
    main()
