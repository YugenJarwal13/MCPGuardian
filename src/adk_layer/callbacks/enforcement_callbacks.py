"""Phase 6 — guardrail enforcement.

Pure, independently-testable policy: combine the (up to three) signals into one
decision, then enforce it for real (raise, don't just log). The sensitive-scope
check runs BEFORE and INDEPENDENTLY of the AI verdicts — defense in depth: even
if every inspection agent is fooled, a tool requesting a sensitive scope still
cannot auto-execute.

``combine_verdicts`` / ``enforce`` stay pure functions. ``make_guardian_before_tool_callback``
wraps them in Google ADK's ``before_tool_callback`` hook so any ADK ``LlmAgent``
holding MCP tools gets the same hard block from ADK's own tool-dispatch
machinery: the callback raises ``GuardianBlockedError`` before ADK invokes the
tool, so the underlying MCP ``session.call_tool()`` never fires.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Awaitable, Callable, Optional

from src.crewai_layer.schemas import InspectionVerdict

try:  # ADK is a hard requirement, but keep the pure policy importable without it.
    from google.adk.tools.base_tool import BaseTool
    from google.adk.tools.tool_context import ToolContext
except ImportError:  # pragma: no cover
    BaseTool = ToolContext = Any  # type: ignore[misc,assignment]


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


# --- Google ADK integration -------------------------------------------------
# verdict_source(tool_name) -> kwargs for combine_verdicts minus the allowlist:
#   {"static_verdict", "runtime_verdict", "is_behaviorally_anomalous", "requested_scope"}
VerdictSource = Callable[[str], dict]


def make_guardian_before_tool_callback(
    verdict_source: VerdictSource,
    allowlist: dict,
    human_approval_callback: Optional[Callable[[str], Awaitable[bool]]] = None,
):
    """Build an ADK ``before_tool_callback`` enforcing the Guardian policy.

    ADK calls it with ``(tool, args, tool_context)`` right before dispatching a
    tool. We record the decision in the ADK session state (so it is part of the
    session's durable history) and then ``enforce`` it — a BLOCK or a denied
    ESCALATE raises ``GuardianBlockedError`` and the tool body never runs.
    Returning ``None`` lets ADK proceed with the real call.
    """

    async def guardian_before_tool_callback(
        tool: BaseTool, args: dict[str, Any], tool_context: ToolContext
    ) -> Optional[dict]:
        decision = combine_verdicts(allowlist=allowlist, **verdict_source(tool.name))
        tool_context.state[f"guardian:decision:{tool.name}"] = decision.value
        await enforce(decision, tool.name, human_approval_callback=human_approval_callback)
        return None

    return guardian_before_tool_callback
