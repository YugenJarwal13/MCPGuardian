"""Phase 3.5 — batch static analysis over the full Phase 1 dataset.

Runs every case through ``run_static_analysis``, logs each verdict to
``logs/audit_trail.jsonl`` in the shared schema the Phase 8 evaluator and Phase 9
dashboard both read, and prints a first-pass precision/recall/F1 plus the benign
false-positive rate. Uses the deterministic heuristic offline; the LLM agent when
credentials are set.
"""
from __future__ import annotations

import asyncio

from src.audit import log_decision
from src.crewai_layer.crew import analyze_static
from src.data.datasets import load_all_cases
from src.evaluation.metrics import false_positive_rate, precision_recall_f1


async def run_batch(use_llm: bool | None = None) -> dict:
    cases = await load_all_cases()
    y_true, y_pred, benign_pred = [], [], []

    for case in cases:
        verdict, engine = analyze_static(
            case.tool_name, case.tool_description, case.tool_schema, use_llm=use_llm
        )
        log_decision(
            {
                "case_id": case.case_id,
                "source": case.source,
                "layer": "static",
                "tool_name": case.tool_name,
                "verdict": verdict.verdict,
                "confidence": verdict.confidence,
                "reasoning": verdict.reasoning,
                "flagged_phrases": verdict.flagged_phrases,
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
    return metrics


if __name__ == "__main__":
    import json

    print(json.dumps(asyncio.run(run_batch()), indent=2))
