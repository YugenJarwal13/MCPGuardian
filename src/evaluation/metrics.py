"""Phase 8.1 — evaluation metrics (introduced early for the Phase 3 first-pass).

A "detection" counts when a malicious case is flagged as either ``malicious`` or
``suspicious`` — both route to a non-ALLOW enforcement decision, so both are
successful catches from the system's point of view.
"""
from __future__ import annotations


def precision_recall_f1(
    y_true: list[str], y_pred: list[str], positive_label: str = "malicious"
) -> dict:
    tp = sum(1 for t, p in zip(y_true, y_pred) if t == positive_label and p in (positive_label, "suspicious"))
    fp = sum(1 for t, p in zip(y_true, y_pred) if t != positive_label and p in (positive_label, "suspicious"))
    fn = sum(1 for t, p in zip(y_true, y_pred) if t == positive_label and p == "clean")
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return {"precision": precision, "recall": recall, "f1": f1, "tp": tp, "fp": fp, "fn": fn}


def false_positive_rate(benign_cases_results: list[str]) -> float:
    """Fraction of genuinely clean tools incorrectly flagged. Run over benign only."""
    flagged = sum(1 for r in benign_cases_results if r != "clean")
    return flagged / len(benign_cases_results) if benign_cases_results else 0.0
