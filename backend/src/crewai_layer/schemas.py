"""Phase 3.1 — the shared verdict schema.

Every inspection agent (static, runtime) outputs this exact shape so the Phase 6
enforcement layer has one uniform contract to reason over.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Verdict = Literal["clean", "suspicious", "malicious"]


class InspectionVerdict(BaseModel):
    verdict: Verdict
    confidence: float = Field(ge=0.0, le=1.0)   # 0.0-1.0
    reasoning: str                              # short human-readable justification (audit log)
    flagged_phrases: list[str] = []             # exact substrings that triggered suspicion
