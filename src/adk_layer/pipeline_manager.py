"""Phase 7.3 / 11.2 — ADK case-lifecycle manager (the A2A receiver).

The case manager is a real Google ADK agent (``CaseManagerAgent``, a
deterministic ``BaseAgent`` — no LLM needed to apply policy) run by an ADK
``Runner``. Every incoming ``GuardianVerdictMessage`` is one ADK invocation:

  1. the message arrives as the invocation's user content (over A2A — see
     ``src/a2a_bridge/a2a_server.py`` — or via ``LocalA2AClient`` offline);
  2. the agent applies ``combine_verdicts`` and yields an ``Event`` whose
     ``EventActions.state_delta`` writes the case under ``app:case:<case_id>``;
  3. the ADK session service persists that delta. ``app:``-prefixed keys are
     ADK *app-scoped* state, so every session of the app sees every case.

The session service is ADK's ``SqliteSessionService`` when a ``db_path`` is
given (durable across restarts), otherwise ``InMemorySessionService``.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import json
import uuid
from typing import AsyncGenerator, Optional

from google.adk.agents import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event, EventActions
from google.adk.runners import Runner
from google.adk.sessions import BaseSessionService, InMemorySessionService
from google.genai import types
from pydantic import BaseModel

from src.a2a_bridge.bridge import GuardianVerdictMessage
from src.adk_layer.adk_runtime import APP_NAME
from src.adk_layer.callbacks.enforcement_callbacks import GuardianDecision, combine_verdicts
from src.audit import log_decision
from src.config import allowlist as load_allowlist
from src.crewai_layer.schemas import InspectionVerdict

CASE_PREFIX = "app:case:"
USER_ID = "guardian"
REGISTRY_SESSION = "case-registry"


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


def _content_text(content: types.Content | None) -> str:
    if content is None or not content.parts:
        return ""
    return "".join(p.text or "" for p in content.parts)


class CaseManagerAgent(BaseAgent):
    """Deterministic ADK agent: verdict message in -> case state + decision out."""

    allowlist: dict = {}

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        msg = GuardianVerdictMessage(**json.loads(_content_text(ctx.user_content)))
        log_decision({"layer": "a2a", "event": "a2a_message_received",
                      "case_id": msg.case_id, "tool_name": msg.tool_name})
        decision = combine_verdicts(
            static_verdict=_verdict(msg.static_verdict, msg.combined_confidence),
            runtime_verdict=_verdict(msg.runtime_verdict, msg.combined_confidence),
            is_behaviorally_anomalous=msg.behavioral_anomaly,
            requested_scope=None,
            allowlist=self.allowlist,
        )
        case = Case(
            case_id=msg.case_id, tool_name=msg.tool_name,
            static_verdict=msg.static_verdict, runtime_verdict=msg.runtime_verdict,
            behavioral_anomaly=msg.behavioral_anomaly, combined_confidence=msg.combined_confidence,
            evidence=msg.evidence, decision=decision.value, timestamp=msg.timestamp,
        )
        log_decision({"layer": "enforcement", "case_id": msg.case_id,
                      "tool_name": msg.tool_name, "decision": decision.value, "via": "a2a"})
        yield Event(
            invocation_id=ctx.invocation_id,
            author=self.name,
            branch=ctx.branch,
            content=types.Content(role="model", parts=[types.Part(text=case.model_dump_json())]),
            actions=EventActions(state_delta={CASE_PREFIX + case.case_id: case.model_dump()}),
        )


def _run_sync(coro):
    """Run a coroutine to completion from sync code, even inside a running loop."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


class PipelineManager:
    def __init__(self, allowlist: Optional[dict] = None, db_path: Optional[str] = None,
                 session_service: Optional[BaseSessionService] = None):
        self._allowlist = allowlist if allowlist is not None else load_allowlist()
        if session_service is None:
            if db_path is not None:
                from google.adk.sessions.sqlite_session_service import SqliteSessionService

                session_service = SqliteSessionService(db_path=str(db_path))
            else:
                session_service = InMemorySessionService()
        self.session_service = session_service
        self.agent = CaseManagerAgent(
            name="pipeline_manager",
            description="MCP Guardian case manager: turns verdict messages into enforced cases.",
            allowlist=self._allowlist,
        )
        self.runner = Runner(app_name=APP_NAME, agent=self.agent,
                             session_service=self.session_service)

    def register_with(self, a2a_client) -> None:
        a2a_client.register("pipeline_manager", self.handle_message)

    async def handle_message(self, payload: dict) -> Case:
        """Run one ADK invocation of the case manager for this payload."""
        session = await self.session_service.create_session(
            app_name=APP_NAME, user_id=USER_ID, session_id=f"case-{uuid.uuid4().hex}")
        msg = types.Content(role="user", parts=[types.Part(text=json.dumps(payload))])
        result: Case | None = None
        async for event in self.runner.run_async(user_id=USER_ID, session_id=session.id,
                                                 new_message=msg):
            text = _content_text(event.content)
            if event.author == self.agent.name and text:
                result = Case.model_validate_json(text)
        if result is None:
            raise RuntimeError("case manager produced no case event")
        return result

    async def _app_state(self) -> dict:
        session = await self.session_service.get_session(
            app_name=APP_NAME, user_id=USER_ID, session_id=REGISTRY_SESSION)
        if session is None:
            session = await self.session_service.create_session(
                app_name=APP_NAME, user_id=USER_ID, session_id=REGISTRY_SESSION)
        return dict(session.state)

    async def aget_case(self, case_id: str) -> Case:
        state = await self._app_state()
        return Case(**state[CASE_PREFIX + case_id])

    async def aall_cases(self) -> list[Case]:
        state = await self._app_state()
        return [Case(**v) for k, v in state.items() if k.startswith(CASE_PREFIX)]

    def get_case(self, case_id: str) -> Case:
        """Sync read of a case from ADK app state (raises KeyError if absent)."""
        return _run_sync(self.aget_case(case_id))

    def all_cases(self) -> list[Case]:
        return _run_sync(self.aall_cases())
