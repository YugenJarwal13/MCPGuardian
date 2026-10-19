"""Phase 5.1 — the tool fingerprint schema.

Uses Welford's online statistics so we never store the full call history: mean
and M2 (sum of squared deltas) are enough to compute running mean/variance of
response length across the whole project lifetime.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class ToolFingerprint(BaseModel):
    tool_id: str                              # e.g. "dvmcp-ch4:rug_pull_tool"
    n_samples: int = 0
    mean_length: float = 0.0
    m2_length: float = 0.0                    # Welford's M2 for online variance
    known_response_keys: set[str] = Field(default_factory=set)  # JSON keys ever seen
    mean_latency_ms: float = 0.0
