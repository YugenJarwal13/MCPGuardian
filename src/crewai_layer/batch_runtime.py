"""Phase 4.4 — batch runtime inspection over response-bearing cases.

Runs the runtime auditor over every case that has a ``sample_response`` (DVMCP
challenges 4/5/6/10 poison the response path; benign cases carry clean responses
including the tricky instruction-adjacent ones), logging each verdict AND its
per-call latency to ``logs/audit_trail.jsonl``.
"""
from __future__ import annotations

import asyncio

from src.audit import log_decision
from src.crewai_layer.crew import analyze_runtime_timed
from src.data.datasets import load_all_cases
from src.evaluation.metrics import false_positive_rate, precision_recall_f1


async def run_batch(use_llm: bool | None = None) -> dict:
    cases = [c for c in await load_all_cases() if c.sample_response]
    y_true, y_pred, benign_pred, latencies = [], [], [], []

    for case in cases:
        verdict, engine, elapsed_ms = analyze_runtime_timed(
            case.tool_name, case.sample_response, use_llm=use_llm
        )
        latencies.append(elapsed_ms)
        log_decision(
            {
                "case_id": case.case_id,
                "source": case.source,
                "layer": "runtime",
                "tool_name": case.tool_name,
                "verdict": verdict.verdict,
                "confidence": verdict.confidence,
                "reasoning": verdict.reasoning,
                "flagged_phrases": verdict.flagged_phrases,
                "latency_ms": round(elapsed_ms, 3),
                "engine": engine,
                "ground_truth": case.ground_truth_label,
                "attack_category": case.attack_category,
            }
        )
        y_true.append(case.ground_truth_label)
        y_pred.append(verdict.verdict)
        if case.source == "benign":
            benign_pred.append(verdict.verdict)

    metrics = precision_recall_f1(y_true, y_pred)
    metrics["false_positive_rate"] = false_positive_rate(benign_pred)
    metrics["n_cases"] = len(cases)
    metrics["mean_latency_ms"] = round(sum(latencies) / len(latencies), 3) if latencies else 0.0
    return metrics


if __name__ == "__main__":
    import json

    print(json.dumps(asyncio.run(run_batch()), indent=2))
