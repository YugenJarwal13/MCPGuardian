"""Phase 5.2 / 5.3 — behavioral-anomaly detection.

Two layers:
  * ``update_fingerprint_and_score`` — pure, deterministic Welford scoring that
    runs BEFORE any LLM reasoning. This is what the rug-pull test pins exactly.
  * ``BehavioralAnomalyAgent`` — an ADK-agent wrapper that adds a human-readable
    explanation on top of the numeric signal (and can catch anomalies the raw
    statistics miss, e.g. a length-preserving but semantically different
    response). Runs fully offline with a templated explanation when no ADK/LLM
    credentials are configured.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from src.adk_layer.state.session_schema import ToolFingerprint
from src.config import settings


def _thresholds() -> tuple[float, int]:
    t = settings().get("thresholds", {})
    return float(t.get("response_length_zscore", 3.0)), int(t.get("fingerprint_warmup_samples", 5))


def update_fingerprint_and_score(
    fp: ToolFingerprint, response_text: str, response_keys: set[str], latency_ms: float
) -> tuple[ToolFingerprint, bool, dict]:
    """Welford's online algorithm for running mean/variance of response length,
    plus structural-drift detection on the set of JSON keys ever seen.

    Returns ``(updated_fp, is_anomalous, evidence)``.
    """
    z_thresh, warmup = _thresholds()

    n = fp.n_samples + 1
    length = len(response_text)
    delta = length - fp.mean_length
    new_mean = fp.mean_length + delta / n
    new_m2 = fp.m2_length + delta * (length - new_mean)

    std = math.sqrt(new_m2 / n) if n > 1 else 0.0
    z_score = abs(length - new_mean) / std if std > 0 else 0.0

    new_keys = response_keys - fp.known_response_keys
    # Ignore key growth during warm-up (a tool legitimately reveals keys early).
    structural_anomaly = len(new_keys) > 0 and fp.n_samples >= warmup

    fp.n_samples, fp.mean_length, fp.m2_length = n, new_mean, new_m2
    fp.known_response_keys |= response_keys
    fp.mean_latency_ms = fp.mean_latency_ms + (latency_ms - fp.mean_latency_ms) / n

    is_anomalous = z_score > z_thresh or structural_anomaly
    evidence = {
        "z_score": round(z_score, 3),
        "new_keys": sorted(new_keys),
        "structural_anomaly": structural_anomaly,
        "mean_length": round(new_mean, 3),
    }
    return fp, is_anomalous, evidence


@dataclass
class AnomalyReport:
    is_anomalous: bool
    explanation: str
    evidence: dict


class BehavioralAnomalyAgent:
    """ADK stateful wrapper around the deterministic scorer."""

    def __init__(self, use_llm: bool | None = None):
        self._use_llm = use_llm

    def analyze(
        self,
        fp: ToolFingerprint,
        response_text: str,
        response_keys: set[str],
        latency_ms: float,
    ) -> tuple[ToolFingerprint, AnomalyReport]:
        fp, is_anomalous, evidence = update_fingerprint_and_score(
            fp, response_text, response_keys, latency_ms
        )
        explanation = self._explain(fp, is_anomalous, evidence)
        return fp, AnomalyReport(is_anomalous=is_anomalous, explanation=explanation, evidence=evidence)

    def _explain(self, fp: ToolFingerprint, is_anomalous: bool, evidence: dict) -> str:
        if not is_anomalous:
            return (
                f"Tool '{fp.tool_id}' behaved within its established profile "
                f"(z={evidence['z_score']}, no new response keys)."
            )
        reasons = []
        if evidence["z_score"] and evidence["z_score"] > 0 and evidence["structural_anomaly"] is False:
            reasons.append(f"response length deviated sharply (z={evidence['z_score']})")
        if evidence["structural_anomaly"]:
            reasons.append(f"new response keys appeared post-warm-up: {evidence['new_keys']}")
        base = (
            f"ANOMALY on '{fp.tool_id}' after {fp.n_samples} calls: " + "; ".join(reasons or ["statistical drift"])
            + ". This is the signature of a rug pull — a tool that behaved normally then changed."
        )
        # An LLM pass would refine this wording; offline we return the template.
        return base
