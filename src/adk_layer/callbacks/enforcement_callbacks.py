"""Phase 6 — guardrail enforcement.

Pure, independently-testable policy: combine the (up to three) signals into one
decision, then enforce it for real (raise, don't just log). The sensitive-scope
check runs BEFORE and INDEPENDENTLY of the AI verdicts — defense in depth: even
if every inspection agent is fooled, a tool requesting a sensitive scope still
cannot auto-execute.
"""
from __future__ import annotations

from enum import Enum
from typing import Awaitable, Callable, Optional

from src.crewai_layer.schemas import InspectionVerdict


class GuardianDecision(str, Enum):
    ALLOW = "allow"
    BLOCK = "block"
    ESCALATE = "escalate"   # requires human approval before proceeding


def _worst(*verdicts: Optional[InspectionVerdict]) -> str:
    worst = "clean"
    for v in verdicts:
        if v is None:
            continue
        if v.verdict == "malicious":
            return "malicious"
        if v.verdict == "suspicious" and worst != "malicious":
            worst = "suspicious"
    return worst


def combine_verdicts(
    static_verdict: Optional[InspectionVerdict],
    runtime_verdict: Optional[InspectionVerdict],
    is_behaviorally_anomalous: bool,
    requested_scope: Optional[str],
    allowlist: dict,
) -> GuardianDecision:
    worst = _worst(static_verdict, runtime_verdict)

    sensitive = [s["scope"] for s in allowlist.get("always_require_human_approval", [])]
    if requested_scope in sensitive:
        # Sensitive scopes ALWAYS require a human, regardless of AI verdict.
        return GuardianDecision.ESCALATE
    if worst in allowlist.get("auto_block_on_verdict", []):
        return GuardianDecision.BLOCK
    if worst in allowlist.get("escalate_on_verdict", []) or is_behaviorally_anomalous:
        return GuardianDecision.ESCALATE
    return GuardianDecision.ALLOW


class GuardianBlockedError(Exception):
    """Raised when a tool call is hard-blocked. Must propagate up to
    GuardedMCPClient.call_tool() and prevent session.call_tool() from ever
    being invoked."""


async def enforce(
    decision: GuardianDecision,
    tool_name: str,
    human_approval_callback: Optional[Callable[[str], Awaitable[bool]]] = None,
) -> None:
    if decision == GuardianDecision.BLOCK:
        raise GuardianBlockedError(f"Tool call to '{tool_name}' blocked: malicious verdict.")
    if decision == GuardianDecision.ESCALATE:
        approved = await human_approval_callback(tool_name) if human_approval_callback else False
        if not approved:
            raise GuardianBlockedError(
                f"Tool call to '{tool_name}' blocked: human approval denied or unavailable."
            )
    # ALLOW: fall through, execution proceeds normally.


async def cli_human_approval(tool_name: str) -> bool:
    """A blocking CLI prompt — a completely legitimate human-in-the-loop for a
    course demo."""
    response = input(f"[GUARDIAN] Tool '{tool_name}' flagged for review. Approve? (y/n): ")
    return response.strip().lower() == "y"
