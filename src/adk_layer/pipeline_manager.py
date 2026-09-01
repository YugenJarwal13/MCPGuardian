"""Phase 7.3 — ADK case-lifecycle manager (the A2A receiver).

Accepts a ``GuardianVerdictMessage`` over A2A, persists it as part of that case's
lifecycle state (same pattern as the Phase 5 fingerprint store — a store keyed by
``case_id``), and triggers the Phase 6 enforcement logic. This is the ADK
stateful half: verdicts produced anywhere in the CrewAI layer arrive here and
become durable, enforceable case state.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel

from src.a2a_bridge.bridge import GuardianVerdictMessage
from src.adk_layer.callbacks.enforcement_callbacks import GuardianDecision, combine_verdicts
from src.audit import log_decision
from src.config import allowlist as load_allowlist
from src.crewai_layer.schemas import InspectionVerdict


class Case(BaseModel):
    case_id: str
    tool_name: str
    static_verdict: str | None = None
    runtime_verdict: str | None = None
    behavioral_anomaly: bool = False
    combined_confidence: float = 0.0
    evidence: list[str] = []
    decision: str = GuardianDecision.ALLOW.value
    timestamp: str = ""


def _verdict(label: str | None, confidence: float) -> Optional[InspectionVerdict]:
    if label is None:
        return None
    return InspectionVerdict(verdict=label, confidence=confidence, reasoning="via A2A")


class PipelineManager:
    def __init__(self, allowlist: Optional[dict] = None):
        self._allowlist = allowlist if allowlist is not None else load_allowlist()
        self._cases: dict[str, Case] = {}

    def register_with(self, a2a_client) -> None:
        a2a_client.register("pipeline_manager", self.handle_message)

    async def handle_message(self, payload: dict) -> Case:
        msg = GuardianVerdictMessage(**payload)
        log_decision({"layer": "a2a", "event": "a2a_message_received",
                      "case_id": msg.case_id, "tool_name": msg.tool_name})

        decision = combine_verdicts(
            static_verdict=_verdict(msg.static_verdict, msg.combined_confidence),
            runtime_verdict=_verdict(msg.runtime_verdict, msg.combined_confidence),
            is_behaviorally_anomalous=msg.behavioral_anomaly,
            requested_scope=None,
            allowlist=self._allowlist,
        )
        case = Case(
            case_id=msg.case_id, tool_name=msg.tool_name,
            static_verdict=msg.static_verdict, runtime_verdict=msg.runtime_verdict,
            behavioral_anomaly=msg.behavioral_anomaly, combined_confidence=msg.combined_confidence,
            evidence=msg.evidence, decision=decision.value, timestamp=msg.timestamp,
        )
        self._cases[msg.case_id] = case
        log_decision({"layer": "enforcement", "case_id": msg.case_id,
                      "tool_name": msg.tool_name, "decision": decision.value, "via": "a2a"})
        return case

    def get_case(self, case_id: str) -> Case:
        return self._cases[case_id]

    def all_cases(self) -> list[Case]:
        return list(self._cases.values())
