"""Phase 7 — the A2A bridge.

The one genuine cross-framework hop in the system: CrewAI's reasoning output
becomes ADK's stateful input. The point of A2A here is the TRANSPORT between two
frameworks, not a bespoke protocol — so the payload is a plain, serializable
Pydantic model and delivery goes through a transport client rather than a direct
Python function call.

Two transports share one ``send(destination, payload)`` contract:

  * ``RemoteA2AClient`` — the LIVE path. Speaks the A2A protocol (JSON-RPC
    ``message/send`` over HTTP, via the ``a2a-sdk`` client) to the ADK case
    manager served by ``src/a2a_bridge/a2a_server.py``. The verdict crosses a
    real socket and is handled by ADK's ``A2aAgentExecutor`` on the far side.
  * ``LocalA2AClient`` — in-process routing to registered handlers, kept as the
    offline/test transport.

Both record ``a2a_message_sent`` in the audit trail; the receiver records
``a2a_message_received``.
"""
from __future__ import annotations

import json
import time
import uuid
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


class RemoteA2AClient:
    """A real A2A transport client. ``destinations`` maps a logical destination
    (e.g. ``"pipeline_manager"``) to the base URL of an A2A server."""

    def __init__(self, destinations: dict[str, str], timeout_s: float = 30.0) -> None:
        self._destinations = dict(destinations)
        self._timeout_s = timeout_s
        self._clients: dict[str, Any] = {}

    async def _client(self, url: str):
        if url not in self._clients:
            import httpx
            from a2a.client import ClientConfig, ClientFactory

            config = ClientConfig(streaming=False,
                                  httpx_client=httpx.AsyncClient(timeout=self._timeout_s))
            self._clients[url] = await ClientFactory.connect(url, client_config=config)
        return self._clients[url]

    async def send(self, destination: str, payload: dict) -> Any:
        from a2a.types import Message, Part, Role, TextPart

        url = self._destinations.get(destination)
        if url is None:
            raise KeyError(f"No A2A route registered for destination '{destination}'")
        log_decision({
            "layer": "a2a", "event": "a2a_message_sent", "destination": destination,
            "transport": "a2a-jsonrpc-http", "url": url,
            "case_id": payload.get("case_id"), "tool_name": payload.get("tool_name"),
        })
        start = time.monotonic()
        client = await self._client(url)
        message = Message(role=Role.user, message_id=uuid.uuid4().hex,
                          parts=[Part(root=TextPart(text=json.dumps(payload)))])
        result: dict | None = None
        async for event in client.send_message(message):
            result = _extract_json(event) or result
        if result is None:
            raise RuntimeError(f"A2A destination '{destination}' returned no result")
        result["_a2a_round_trip_ms"] = round((time.monotonic() - start) * 1000, 2)
        return result

    async def aclose(self) -> None:
        for c in self._clients.values():
            await c.close()
        self._clients.clear()


def _extract_json(event: Any) -> dict | None:
    """Pull the case-manager's JSON reply out of an A2A Task or Message."""
    from a2a.types import Message

    texts: list[str] = []
    if isinstance(event, Message):
        texts += [getattr(p.root, "text", "") for p in event.parts]
    else:
        task = event[0] if isinstance(event, tuple) else event
        for art in getattr(task, "artifacts", None) or []:
            texts += [getattr(p.root, "text", "") for p in art.parts]
        status_msg = getattr(getattr(task, "status", None), "message", None)
        if status_msg is not None:
            texts += [getattr(p.root, "text", "") for p in status_msg.parts]
        for msg in reversed(getattr(task, "history", None) or []):
            if msg.role.value == "agent":
                texts += [getattr(p.root, "text", "") for p in msg.parts]
    for t in texts:
        try:
            data = json.loads(t)
        except (TypeError, json.JSONDecodeError):
            continue
        if isinstance(data, dict) and "case_id" in data:
            return data
    return None


async def send_verdict_to_case_manager(message: GuardianVerdictMessage, a2a_client) -> Any:
    """Package the CrewAI crew's combined output as an A2A message and hand it to
    the ADK pipeline_manager's case-lifecycle endpoint."""
    return await a2a_client.send(destination="pipeline_manager", payload=message.model_dump())
