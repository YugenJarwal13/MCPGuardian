"""Phase 7 — the A2A bridge.

The one genuine cross-framework hop in the system: CrewAI's reasoning output
becomes ADK's stateful input. The point of A2A here is the TRANSPORT between two
frameworks, not a bespoke protocol — so the payload is a plain, serializable
Pydantic model and delivery goes through a transport client rather than a direct
Python function call.

``LocalA2AClient`` is an in-process transport that routes to registered
destination handlers and records the hop in the audit trail. When
``google-adk[a2a]`` services are running, a real A2A client can be substituted
wherever a ``LocalA2AClient`` is used — the ``send`` contract is the same.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from pydantic import BaseModel, Field

from src.audit import log_decision


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class GuardianVerdictMessage(BaseModel):
    case_id: str
    tool_name: str
    static_verdict: str | None = None
    runtime_verdict: str | None = None
    behavioral_anomaly: bool = False
    combined_confidence: float = 0.0
    evidence: list[str] = []               # flagged_phrases + z-score/new-keys merged
    timestamp: str = Field(default_factory=_now_iso)


Handler = Callable[[dict], Awaitable[Any]]


class LocalA2AClient:
    """In-process stand-in for an A2A transport client."""

    def __init__(self) -> None:
        self._routes: dict[str, Handler] = {}

    def register(self, destination: str, handler: Handler) -> None:
        self._routes[destination] = handler

    async def send(self, destination: str, payload: dict) -> Any:
        # The hop is explicitly recorded so it is visible in the Phase 9 dashboard.
        log_decision({
            "layer": "a2a", "event": "a2a_message_sent", "destination": destination,
            "case_id": payload.get("case_id"), "tool_name": payload.get("tool_name"),
        })
        handler = self._routes.get(destination)
        if handler is None:
            raise KeyError(f"No A2A route registered for destination '{destination}'")
        return await handler(payload)


async def send_verdict_to_case_manager(message: GuardianVerdictMessage, a2a_client) -> Any:
    """Package the CrewAI crew's combined output as an A2A message and hand it to
    the ADK pipeline_manager's case-lifecycle endpoint."""
    return await a2a_client.send(destination="pipeline_manager", payload=message.model_dump())
