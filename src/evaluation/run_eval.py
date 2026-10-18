"""Phase 8 / 11.5 / 12.5 — evaluation runner.

Scores every selected ``ToolTestCase`` once and writes ONE record per case to
``src/evaluation/reports/cases_<name>.jsonl`` — verdicts, engine, and (for LLM
verdicts) the provider/model/latency that produced them, plus the deterministic
heuristic's verdicts for the same case. ``report.py`` derives every number from
those files, so metrics can be recomputed (and sliced) without re-running a model.

    python -m src.evaluation.run_eval                    # deterministic, full set
    python -m src.evaluation.run_eval --llm              # LLM pipeline, stratified sample
    python -m src.evaluation.run_eval --llm --limit 30   # sanity batch (prefix of the sample)
    python -m src.evaluation.run_eval --llm --name prompt_v1 --prompt-version v1 --limit 100
    python -m src.evaluation.run_eval --report-only      # regenerate docs/evaluation_report.md
    LLM_PROVIDER=ollama python -m src.evaluation.run_eval --llm --provider ollama   # force local

LLM runs are RESUMABLE: every successful model answer is cached
(``logs/llm_cache.jsonl``), so re-running continues where a quota stopped it.
By default an LLM run is STRICT — it never silently falls back to the local model
or to the heuristic; a case whose LLM call failed is recorded as ``unanswered`` and
excluded from the LLM numbers (and counted), never passed off as an LLM verdict.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from src.config import REPO_ROOT
from src.crewai_layer.heuristics import runtime_heuristic, static_heuristic
from src.data.datasets import load_all_cases
from src.data.schemas import ToolTestCase

REPORTS_DIR = REPO_ROOT / "src" / "evaluation" / "reports"
SEED = 7


def case_group(c: ToolTestCase) -> str:
    """Slice key: dvmcp | mcptox | benign_real | benign_hand | custom_atk | custom_ben | custom_hn."""
    if c.source == "custom":
        return "custom_" + c.case_id.split("-")[2]
    if c.source == "benign":
        return "benign_real" if c.case_id.startswith("mcptox-clean-") else "benign_hand"
    return c.source


# --------------------------------------------------------------------------- selection
def _interleave(groups: dict[str, list[ToolTestCase]]) -> list[ToolTestCase]:
    """Round-robin across groups so ANY prefix is a balanced, nested subset."""
    order = ["dvmcp", "custom_atk", "custom_hn", "custom_ben", "mcptox", "benign_real", "benign_hand"]
    lists = [list(groups[g]) for g in order if g in groups]
    out, i = [], 0
    while any(lists):
        for lst in lists:
            if lst:
                out.append(lst.pop(0))
        i += 1
    return out


def select_cases(cases: list[ToolTestCase], sample: bool, mcptox_n: int, benign_n: int,
                 limit: int | None) -> list[ToolTestCase]:
    rng = random.Random(SEED)
    by_group: dict[str, list[ToolTestCase]] = defaultdict(list)
    for c in cases:
        by_group[case_group(c)].append(c)
    if sample:
        # MCPTox: proportional to each risk category (>= 3 per category), seeded.
        cats: dict[str, list[ToolTestCase]] = defaultdict(list)
        for c in by_group["mcptox"]:
            cats[c.attack_category or "other"].append(c)
        total = len(by_group["mcptox"])
        picked: list[ToolTestCase] = []
        for cat, lst in sorted(cats.items()):
            k = min(len(lst), max(3, round(mcptox_n * len(lst) / total)))
            picked += rng.sample(lst, k)
        rng.shuffle(picked)
        by_group["mcptox"] = picked[:mcptox_n] if len(picked) > mcptox_n else picked
        by_group["benign_real"] = rng.sample(by_group["benign_real"], min(benign_n, len(by_group["benign_real"])))
    else:
        for g in by_group:
            rng.shuffle(by_group[g])
    ordered = _interleave(by_group)
    return ordered[:limit] if limit else ordered


# --------------------------------------------------------------------------- scoring
def _verdict_dict(v) -> dict:
    return {"verdict": v.verdict, "confidence": v.confidence,
            "reasoning": v.reasoning[:400], "flagged_phrases": v.flagged_phrases[:8]}


def _score_one(case: ToolTestCase, use_llm: bool, strict: bool, chain_ref) -> dict:
    from src.crewai_layer.crew import analyze_runtime_meta, analyze_static_meta

    rec: dict = {"case_id": case.case_id, "source": case.source, "label": case.ground_truth_label,
                 "group": case_group(case), "category": case.attack_category, "tool": case.tool_name,
                 "scope": case.requested_scope(), "scope_keyword": case.requested_scope_keyword(),
                 "heuristic": {"static": static_heuristic(case.tool_name, case.tool_description, case.tool_schema).verdict}}
    if case.sample_response:
        rec["heuristic"]["runtime"] = runtime_heuristic(case.tool_name, case.sample_response).verdict

    def run(kind: str) -> dict:
        t0 = time.monotonic()
        if kind == "static":
            v, engine, meta = analyze_static_meta(case.tool_name, case.tool_description, case.tool_schema, use_llm)
        else:
            v, engine, meta = analyze_runtime_meta(case.tool_name, case.sample_response, use_llm)
        out = {**_verdict_dict(v), "engine": engine, "wall_ms": round((time.monotonic() - t0) * 1000, 1)}
        out.update({k: meta[k] for k in ("provider", "model", "method", "latency_ms", "cached", "error",
                                         "slots_tried") if k in meta})
        return out

    rec["static"] = run("static")
    rec["runtime"] = run("runtime") if case.sample_response else None
    return rec


def run_cases(cases: list[ToolTestCase], use_llm: bool, workers: int, strict: bool) -> list[dict]:
    from src.llm_chain import get_chain

    chain = get_chain() if use_llm else None
    results: dict[str, dict] = {}
    skipped_quota = 0
    lock = threading.Lock()
    done = 0
    t_start = time.monotonic()

    def work(c: ToolTestCase):
        nonlocal skipped_quota
        if chain is not None and strict and time.monotonic() < chain.free_tier_exhausted_until \
                and not any(s.provider == "ollama" for s in chain.slots):
            with lock:
                skipped_quota += 1
            return c.case_id, None
        return c.case_id, _score_one(c, use_llm, strict, chain)

    with ThreadPoolExecutor(max_workers=workers if use_llm else 1) as pool:
        futures = [pool.submit(work, c) for c in cases]
        for fut in as_completed(futures):
            cid, rec = fut.result()
            with lock:
                done += 1
                if rec is not None:
                    results[cid] = rec
            if use_llm and (done % 5 == 0 or done == len(cases)):
                el = time.monotonic() - t_start
                eta = el / done * (len(cases) - done)
                print(f"  [{done}/{len(cases)}] {el/60:.1f} min elapsed, ~{eta/60:.1f} min left"
                      f"{'  (quota stop: ' + str(skipped_quota) + ' skipped)' if skipped_quota else ''}", flush=True)
    if chain is not None:
        for ev in chain.events:
            print("  chain event:", ev)
    ordered = [results[c.case_id] for c in cases if c.case_id in results]
    print(f"scored {len(ordered)}/{len(cases)} cases" + (f"; {skipped_quota} skipped (free-tier quota exhausted)" if skipped_quota else ""))
    return ordered


# --------------------------------------------------------------------------- run metadata
def run_header(name: str, use_llm: bool, cases: list[ToolTestCase], args) -> dict:
    from src.llm_chain import get_chain

    head = {"name": name, "llm": use_llm, "n_selected": len(cases),
            "prompt_version": os.environ.get("GUARDIAN_PROMPT_VERSION", "v2"),
            "started": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "args": {k: v for k, v in vars(args).items() if v is not None}}
    if use_llm:
        chain = get_chain()
        head["chain"] = chain.describe()
        head["provider_override"] = os.environ.get("LLM_PROVIDER")
    return head


def write_cases(name: str, header: dict, records: list[dict]) -> Path:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORTS_DIR / f"cases_{name}.jsonl"
    with path.open("w", encoding="utf-8") as fh:
        fh.write(json.dumps({"_header": header}) + "\n")
        for r in records:
            fh.write(json.dumps(r) + "\n")
    return path


# --------------------------------------------------------------------------- CLI
async def _main(args) -> None:
    if args.provider:
        os.environ["LLM_PROVIDER"] = args.provider
    if args.prompt_version:
        os.environ["GUARDIAN_PROMPT_VERSION"] = args.prompt_version
    local = (os.environ.get("LLM_PROVIDER") or "").lower() == "ollama"
    if args.llm:
        # Hosted free models answer in ~10 s; a CPU-only local model can need minutes.
        os.environ.setdefault("GUARDIAN_AGENT_TIMEOUT_S", "1500" if local else "420")
        if not args.allow_local_fallback:
            os.environ["LLM_LOCAL_FALLBACK"] = "off"
        if args.workers is None:
            args.workers = 1 if local else 6          # one CPU-bound request at a time

    name = args.name or ("llm" if args.llm else "deterministic")
    all_cases = await load_all_cases()
    sample = args.llm and not args.full
    cases = select_cases(all_cases, sample=sample, mcptox_n=args.mcptox_n, benign_n=args.benign_n,
                         limit=args.limit)
    print(f"run '{name}': {'LLM' if args.llm else 'deterministic'}, {len(cases)} cases "
          f"({'stratified sample' if sample else 'full set'}), prompt {os.environ.get('GUARDIAN_PROMPT_VERSION', 'v2')}")
    if args.llm:
        from src.crewai_layer.crew import llm_available

        if not llm_available():
            raise SystemExit("LLM requested but no provider can answer (check .env / OPENROUTER_API_KEY / Ollama).")
    header = run_header(name, args.llm, cases, args)
    records = run_cases(cases, args.llm, args.workers or 1, strict=not args.allow_local_fallback)
    header["finished"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    path = write_cases(name, header, records)
    print(f"wrote {path}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--llm", action="store_true", help="use the LLM-backed CrewAI agents")
    ap.add_argument("--name", help="output name (cases_<name>.jsonl); default llm / deterministic")
    ap.add_argument("--full", action="store_true", help="with --llm: all cases instead of the sample")
    ap.add_argument("--limit", type=int, help="first N of the (nested) balanced ordering")
    ap.add_argument("--mcptox-n", type=int, default=120)
    ap.add_argument("--benign-n", type=int, default=60)
    ap.add_argument("--workers", type=int, default=None, help="parallel cases (default 6 hosted, 1 local)")
    ap.add_argument("--prompt-version", choices=("v1", "v2"))
    ap.add_argument("--provider", help="force LLM_PROVIDER for this run (e.g. ollama)")
    ap.add_argument("--allow-local-fallback", action="store_true",
                    help="let a failed/exhausted primary fall through to the local model")
    ap.add_argument("--report-only", action="store_true", help="only regenerate docs/evaluation_report.md")
    args = ap.parse_args()
    if not args.report_only:
        asyncio.run(_main(args))
    from src.evaluation.report import write_report

    print("report:", write_report())


if __name__ == "__main__":
    main()
