"""``WS /ws/run`` — drive one guarded tool call and stream every stage live.

Client -> server (first message):
    {"server_id": "dvmcp-ch2", "tool_name": "get_company_data",
     "arguments": {...}, "use_llm": true}
Client -> server (only when an event has status "escalate"):
    {"type": "approval", "approved": true | false}

This module does not re-implement the pipeline: every decision comes from the
existing ``GuardianInterceptor`` (static screen, pre-call gate with the human
approval callback, runtime + behavioural inspection, A2A case report). It only
calls those steps one at a time and emits an event around each.

Stage order (rendered upfront by the UI):
    connect -> list_tools -> static_check -> tool_call (includes the pre-call
    policy gate) -> runtime_check -> behavioral_check -> a2a_hop ->
    enforcement (post-response) -> done
"""
from __future__ import annotations

import asyncio
import uuid
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from src.adk_layer.callbacks.enforcement_callbacks import GuardianDecision
from src.adk_layer.state.tool_fingerprint_store import ToolFingerprintStore
from src.api.events import EventEmitter
from src.api.servers import default_args_from_schema, get_spec, open_session
from src.crewai_layer.crew import llm_available
from src.evaluation.ablation_config import AblationConfig
from src.mcp_gateway.interceptor import (
    GuardianInterceptor,
    _iter_tools,
    _response_text_and_keys,
    _tool_fields,
)

APPROVAL_TIMEOUT_S = 300
router = APIRouter()

# Per-server fingerprint stores live for the API process, so repeated runs
# against the same server build a behavioural history (rug-pull detection).
_STORES: dict[str, ToolFingerprintStore] = {}


def fingerprint_store(server_id: str) -> ToolFingerprintStore:
    if server_id not in _STORES:
        _STORES[server_id] = ToolFingerprintStore(db_path=":memory:")
    return _STORES[server_id]


def reset_server_state(server_id: str) -> None:
    from src.api import servers

    store = _STORES.pop(server_id, None)
    if store is not None:
        store.close()
    servers._FIXTURE_SESSIONS.pop(server_id, None)


def _verdict_detail(v, engine: str | None = None, **extra) -> dict:
    d = {"verdict": v.verdict, "confidence": v.confidence, "reasoning": v.reasoning,
         "flagged_phrases": v.flagged_phrases}
    if engine:
        d["engine"] = engine
    d.update(extra)
    return d


def _preview(text: str, n: int = 1500) -> str:
    return text if len(text) <= n else text[:n] + f"\n… ({len(text) - n} more chars)"


class _Run:
    def __init__(self, ws: WebSocket, req: dict, a2a_client: Any):
        self.precall_approved: bool | None = None
        self.ws = ws
        self.req = req
        self.server_id = req["server_id"]
        self.spec = get_spec(self.server_id)
        self.a2a = a2a_client
        self.em = EventEmitter(uuid.uuid4().hex[:12], self._send, self.server_id)

    async def _send(self, payload: dict) -> None:
        await self.ws.send_json(payload)
        await asyncio.sleep(0)   # let the frame flush before the next stage starts

    async def _await_approval(self, stage: str, message: str, detail: dict) -> bool:
        await self.em.emit(stage, "escalate", message, detail)
        try:
            while True:
                msg = await asyncio.wait_for(self.ws.receive_json(), APPROVAL_TIMEOUT_S)
                if msg.get("type") == "approval":
                    return bool(msg.get("approved"))
        except asyncio.TimeoutError:
            return False

    async def run(self) -> None:
        em, spec = self.em, self.spec
        use_llm = bool(self.req.get("use_llm"))
        llm_note = None
        if use_llm and not llm_available():
            use_llm = False
            llm_note = "LLM requested but no provider is configured — heuristic detectors used."

        # The pre-call gate's escalation asks the human over this WebSocket.
        async def human(tool_name: str) -> bool:
            ok =await self._await_approval(
                "tool_call", f"'{tool_name}' needs human approval before it may run.",
                {"reason": "policy escalation before execution",
                 "requested_scope": interceptor._scope.get(tool_name),
                 **({"static": _verdict_detail(interceptor._static[tool_name])}
                    if tool_name in interceptor._static else {})})
            await em.emit("tool_call", "passed" if ok else "blocked",
                          "Approved by human — executing." if ok else "Denied by human.")
            self.precall_approved = ok
            return ok

        interceptor = GuardianInterceptor(
            ablation=AblationConfig(), use_llm=use_llm,
            fingerprint_store=fingerprint_store(self.server_id),
            human_approval_callback=human, a2a_client=self.a2a)

        # 1. connect ---------------------------------------------------------
        where = f"127.0.0.1:{spec.port}/sse" if spec.port else "in-process fixture"
        await em.emit("connect", "started", f"Connecting to {spec.name} ({where})…")
        if spec.port is not None and not spec.is_live():
            await em.emit("connect", "error", f"Nothing is listening on port {spec.port}. "
                          "Start the lab: python scripts/run_dvmcp_native.py")
            await em.emit("done", "error", "Run aborted — server offline.")
            return
        async with open_session(spec) as session:
            await em.emit("connect", "passed", f"Connected to {spec.name}.",
                          {"source": spec.source, "endpoint": where,
                           **({"note": llm_note} if llm_note else {})})

            # 2. list_tools ----------------------------------------------------
            await em.emit("list_tools", "started", "Listing tools (tools/list)…")
            listed = await session.list_tools()
            tools = {(f := _tool_fields(t))[0]: f for t in _iter_tools(listed)}
            tool = self.req.get("tool_name") or spec.default_tool or next(iter(tools), None)
            if tool not in tools:
                await em.emit("list_tools", "error", f"Tool '{tool}' not offered by this server.",
                              {"tools": list(tools)})
                await em.emit("done", "error", "Run aborted.")
                return
            em.tool_name = tool
            args = self.req.get("arguments")
            if args is None:
                args = spec.default_args if tool == spec.default_tool else \
                    default_args_from_schema(tools[tool][2])
            await em.emit("list_tools", "passed", f"{len(tools)} tool(s) discovered.",
                          {"tools": list(tools), "selected": tool})

            # 3. static_check --------------------------------------------------
            await em.emit("static_check", "started",
                          f"Static analysis running on '{tool}' and its {len(tools) - 1} "
                          "sibling tool(s)…")
            await interceptor.screen_tool_metadata(listed)
            sv = interceptor._static[tool]
            s_engine = interceptor.engines.get(tool, {}).get("static", "none")
            others = sorted(n for n, v in interceptor._static.items()
                            if n != tool and v.verdict != "clean")
            detail = _verdict_detail(sv, description=tools[tool][1],
                                     requested_scope=interceptor._scope.get(tool),
                                     other_flagged_tools=others)
            if sv.verdict == "clean":
                await em.emit("static_check", "passed", f"'{tool}' metadata looks clean ✓",
                              detail, s_engine)
            else:
                await em.emit("static_check", "flagged",
                              f"'{tool}' metadata flagged as {sv.verdict}!", detail, s_engine)

            # 4. tool_call (pre-call policy gate, then the real call) ----------
            await em.emit("tool_call", "started", f"Policy gate for '{tool}'…",
                          {"arguments": args})
            refusal = await interceptor.pre_call_check(tool, args, session)
            response = None
            if refusal is not None:
                await em.emit("tool_call", "blocked",
                              "Blocked before execution — the server was never called.",
                              {"decision": interceptor.current_decision(tool).value,
                               "refusal": refusal["content"][0]["text"]})
            else:
                await em.emit("tool_call", "started", f"Calling '{tool}' on the server…",
                              {"arguments": args})
                response = await session.call_tool(tool, args)
                text, keys = _response_text_and_keys(response)
                await em.emit("tool_call", "passed", "Tool executed; response captured.",
                              {"response_preview": _preview(text)})

            # 5/6. runtime + behavioural ---------------------------------------
            if response is None:
                for stage in ("runtime_check", "behavioral_check"):
                    await em.emit(stage, "passed", "Skipped — the call never executed.",
                                  {"skipped": True})
            else:
                await em.emit("runtime_check", "started",
                              "Calling the CrewAI runtime inspector on the response, hold on…")
                rv, r_engine, r_ms = await interceptor.inspect_response_runtime(tool, text)
                await em.emit(
                    "runtime_check", "passed" if rv.verdict == "clean" else "flagged",
                    "Response looks like ordinary data ✓" if rv.verdict == "clean"
                    else f"Injected instruction detected ({rv.verdict})!",
                    _verdict_detail(rv, inspector_latency_ms=round(r_ms, 2),
                                    response_preview=_preview(text)), r_engine)

                await em.emit("behavioral_check", "started",
                              "Updating the behavioural fingerprint (ADK anomaly agent)…")
                report = await interceptor.inspect_response_behavioral(tool, text, keys)
                await em.emit(
                    "behavioral_check", "flagged" if report.is_anomalous else "passed",
                    report.explanation,
                    {**report.evidence, "statistical_anomaly": report.statistical_anomaly,
                     "calls_observed": fingerprint_store(self.server_id).get(tool).n_samples},
                    report.engine)

            # 7. a2a_hop -------------------------------------------------------
            await em.emit("a2a_hop", "started",
                          "Sending the combined verdict to the ADK case manager over A2A…")
            try:
                case = await interceptor.report_case(tool, case_id=f"{em.run_id}-{tool}")
                await em.emit("a2a_hop", "passed", "Case recorded by the ADK case manager.",
                              {"transport": "A2A JSON-RPC over HTTP",
                               "url": getattr(self.a2a, "_destinations", {}).get("pipeline_manager"),
                               "case_id": case.get("case_id"), "case_decision": case.get("decision"),
                               "round_trip_ms": case.get("_a2a_round_trip_ms")})
            except Exception as exc:  # the verdict still stands without the hop
                await em.emit("a2a_hop", "error", f"A2A hop failed: {exc}")

            # 8. enforcement (post-response) -----------------------------------
            await em.emit("enforcement", "started", "Applying the combined policy…")
            decision = interceptor.current_decision(tool)
            final = decision.value
            if refusal is not None:
                await em.emit("enforcement", "blocked", "Blocked — nothing reached the agent.",
                              {"decision": "block"})
                final = "block"
            elif decision == GuardianDecision.BLOCK:
                await em.emit("enforcement", "blocked",
                              "Flagged! Blocking — the response is withheld from the agent.",
                              {"decision": "block"})
            elif (decision == GuardianDecision.ESCALATE and self.precall_approved
                  and interceptor.current_decision(tool, include_scope=False)
                  == GuardianDecision.ALLOW):
                # The only reason to escalate is the tool's sensitive scope, which the
                # human already approved for this call — don't ask twice.
                await em.emit("enforcement", "passed",
                              "Allowed — covered by the human approval given before the call ✓",
                              {"decision": "allow", "approved_scope": interceptor._scope.get(tool)})
                final = "escalate_approved"
            elif decision == GuardianDecision.ESCALATE:
                ok = await self._await_approval(
                    "enforcement", "Response needs human review before the agent sees it.",
                    {"decision": "escalate", "anomalous": interceptor._anomalous.get(tool, False),
                     "requested_scope": interceptor._scope.get(tool)})
                final = "escalate_approved" if ok else "escalate_denied"
                await em.emit("enforcement", "passed" if ok else "blocked",
                              "Released by human reviewer." if ok else "Withheld by human reviewer.",
                              {"decision": final})
            else:
                await em.emit("enforcement", "passed", "Allowed — response delivered to the agent ✓",
                              {"decision": "allow"})

            released = final in ("allow", "escalate_approved")
            await em.emit("done", "passed" if released else "blocked",
                          "ALLOW" if final == "allow" else
                          "BLOCK" if final in ("block", "escalate_denied") else "ESCALATE → approved",
                          {"final_decision": final, "tool": tool,
                           "engines": interceptor.engines.get(tool, {}),
                           **({"response": _preview(text)} if released and response else {})})


@router.websocket("/ws/run")
async def ws_run(ws: WebSocket) -> None:
    await ws.accept()
    try:
        req = await ws.receive_json()
        try:
            run = _Run(ws, req, ws.app.state.a2a_client)
        except KeyError:
            await ws.send_json({"stage": "done", "status": "error",
                                "message": f"Unknown server '{req.get('server_id')}'"})
            return
        try:
            await run.run()
        except WebSocketDisconnect:
            raise
        except Exception as exc:
            await run.em.emit("done", "error", f"Pipeline error: {type(exc).__name__}: {exc}")
    except WebSocketDisconnect:
        return
    finally:
        try:
            await ws.close()
        except RuntimeError:
            pass
