"""``WS /ws/run`` - drive one guarded tool call and stream every stage live.

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

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect

from src.adk_layer.callbacks.enforcement_callbacks import GuardianDecision
from src.adk_layer.state.tool_fingerprint_store import ToolFingerprintStore
from src.adk_layer.behavioral_anomaly_agent import BehavioralAnomalyAgent
from src.api.events import EventEmitter
from src.audit import log_decision
from src.api import live_server as live
from src.api.servers import (
    CustomServerError,
    custom_spec,
    default_args_from_schema,
    get_spec,
    list_all_tools,
    open_session,
    safe_to_try,
)
from src.crewai_layer.crew import llm_available
from src.evaluation.ablation_config import AblationConfig
from src.observability import clip, tracer
from src.security import access, secret_scan
from src.security.input_guard import check_arguments, check_url
from src.security.public_mode import check_public_target, limiter, origin_allowed, public_mode, restrict_execution
from src.mcp_gateway.interceptor import (
    GuardianInterceptor,
    _iter_tools,
    _response_text_and_keys,
    _tool_fields,
)

APPROVAL_TIMEOUT_S = 300
STATIC_WORKERS = 4


def _max_tools() -> int:
    import os

    try:
        return int(os.environ.get("GUARDIAN_MAX_TOOLS", 40 if public_mode() else 150))
    except ValueError:
        return 40
router = APIRouter()

# Per-server fingerprint stores live for the API process, so repeated runs
# against the same server build a behavioural history (rug-pull detection).
_STORES: dict[str, ToolFingerprintStore] = {}


def fingerprint_store(server_id: str) -> ToolFingerprintStore:
    if server_id not in _STORES:
        _STORES[server_id] = ToolFingerprintStore(db_path=":memory:")
    return _STORES[server_id]


# Response size and fields per call, per server and tool: the data behind the drift chart.
_HISTORY: dict[str, list[dict]] = {}
# One behavioural agent per server, so it remembers the previous response between runs.
_AGENTS: dict[tuple[str, bool], BehavioralAnomalyAgent] = {}


def anomaly_agent(server_id: str, use_llm: bool) -> BehavioralAnomalyAgent:
    return _AGENTS.setdefault((server_id, use_llm), BehavioralAnomalyAgent(use_llm=use_llm))


def reset_server_state(server_id: str) -> None:
    from src.api import servers

    for key in [k for k in _HISTORY if k.startswith(f"{server_id}:")]:
        _HISTORY.pop(key, None)
    for key in [k for k in _AGENTS if k[0] == server_id]:
        _AGENTS.pop(key, None)

    store = _STORES.pop(server_id, None)
    if store is not None:
        store.close()
    servers._FIXTURE_SESSIONS.pop(server_id, None)


def _verdict_detail(v, engine: str | None = None, meta: dict | None = None, **extra) -> dict:
    d = {"verdict": v.verdict, "confidence": v.confidence, "reasoning": v.reasoning,
         "flagged_phrases": v.flagged_phrases}
    if engine:
        d["engine"] = engine
    if meta:
        d.update({k: meta[k] for k in ("provider", "model", "method", "cached") if k in meta})
        if meta.get("latency_ms") is not None:
            d["model_latency_ms"] = meta["latency_ms"]
        if meta.get("slots_tried"):
            d["models_tried"] = meta["slots_tried"]
    d.update(extra)
    return d


def _friendly_error(exc: BaseException) -> str:
    """Unwrap anyio ExceptionGroups so the UI shows the real connection error."""
    while getattr(exc, "exceptions", None):
        exc = exc.exceptions[0]
    return f"{type(exc).__name__}: {str(exc)[:300]}"


def _preview(text: str, n: int = 1500) -> str:
    text = secret_scan.redact_text(text)          # live credentials in a reply are never shown or logged
    return text if len(text) <= n else text[:n] + f"\n… ({len(text) - n} more chars)"


class _Run:
    def __init__(self, ws: WebSocket, req: dict, a2a_client: Any):
        self.precall_approved: bool | None = None
        self.ws = ws
        self.req = req
        self.cred = live.Credentials()
        if req.get("server_url"):
            self.spec = custom_spec(req["server_url"])     # may raise CustomServerError
            self.cred = live.parse_credentials(req.get("auth"), req["server_url"])     # may raise AuthError
            self.spec.headers = self.cred.headers
            self.server_id = self.spec.id
        else:
            self.server_id = req["server_id"]
            self.spec = get_spec(self.server_id)
        self.inspect_only = bool(req.get("inspect_only"))
        self.notice: str | None = None           # shown on the connect step (e.g. a lab server is inspect-only)
        self.a2a = a2a_client
        self.em = EventEmitter(uuid.uuid4().hex[:12], self._send, self.server_id)
        self.em.scrub = lambda value: live.scrub(value, self.cred.secrets)

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

    def _connect_hint(self) -> str:
        if self.spec.url:
            return ("The address must be a remote MCP endpoint (streamable HTTP or SSE). "
                    "If the server needs a key or sign-in, choose it under “Authentication”.")
        return "See the README for how to start the lab servers."

    async def _prepare_custom(self, where: str) -> bool:
        """Find out what a user-supplied endpoint speaks and set up its credentials.
        Returns False (after reporting why) when the run cannot go on."""
        em, spec, cred = self.em, self.spec, self.cred
        probe = await live.probe_endpoint(spec.url, cred.headers)
        if probe.error:
            await em.emit("connect", "error", probe.error, {"endpoint": where, "hint": self._connect_hint()})
            await em.emit("done", "error", "Run aborted — could not connect.")
            return False
        if probe.auth_required and cred.kind == "oauth":
            spec.transport = "sse" if spec.url.split("?")[0].rstrip("/").endswith("/sse") else "streamable-http"
            return await self._setup_oauth(where)
        if probe.auth_required:
            if cred.kind in ("bearer", "header") or cred.secrets:
                msg = (f"The server rejected the credentials (HTTP {probe.status}). Check the token or key, "
                       "and that it has access to this server.")
            else:
                msg = f"This server requires authentication (HTTP {probe.status}). Choose how to sign in below."
            await em.emit("connect", "error", msg,
                          {"endpoint": where, "auth_required": True, "oauth_advertised": probe.oauth_advertised,
                           "hint": self._connect_hint()})
            await em.emit("done", "error", "Run aborted — authentication needed.")
            return False
        spec.transport = probe.transport or spec.transport
        if cred.kind == "oauth":
            cred_note = "This server did not ask for a sign-in, so none was used."
            self.notice = f"{self.notice} {cred_note}".strip() if self.notice else cred_note
        return True

    async def _setup_oauth(self, where: str) -> bool:
        em, spec, cred = self.em, self.spec, self.cred
        sid, storage = live.oauth_session_secret(cred.oauth_session)
        origin = self.ws.headers.get("origin")
        redirect = live.oauth_redirect_uri(origin, self.ws.scope.get("server"))

        async def announce(auth_url: str) -> None:
            await em.emit("connect", "started", "Sign-in needed: open the server's sign-in page and approve access.",
                          {"oauth_url": auth_url, "endpoint": where})

        spec.auth = live.build_oauth(spec.url, redirect, storage, announce)
        await self.ws.send_json({"type": "auth_session", "session": sid})     # not logged: a handle to in-memory tokens
        if live.has_oauth_tokens(sid):
            await em.emit("connect", "started", "Reusing your earlier sign-in for this server…", {"endpoint": where})
        return True

    async def run(self) -> None:
        em, spec = self.em, self.spec
        use_llm = bool(self.req.get("use_llm"))
        if use_llm and not llm_available():
            await em.emit("connect", "error",
                          "No language model is reachable, and this run needs one. Check the OpenRouter key and model "
                          "settings of the backend.", {"hint": "see the LLM configuration section of the README"})
            await em.emit("done", "error", "Run aborted: no language model available.")
            return
        llm_note = self.notice

        # The pre-call gate's escalation asks the human over this WebSocket.
        async def human(tool_name: str) -> bool:
            ok =await self._await_approval(
                "tool_call", f"'{tool_name}' needs human approval before it may run.",
                {"reason": ("this tool's definition changed since it was first seen"
                            if tool_name in interceptor.definition_changes
                            else "policy escalation before execution"),
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
            anomaly_agent=anomaly_agent(self.server_id, use_llm),
            human_approval_callback=human, a2a_client=self.a2a)

        # 1. connect ---------------------------------------------------------
        where = (live.display_url(spec.url) if spec.url else f"127.0.0.1:{spec.port}/sse" if spec.port
                 else "in-process fixture")
        await em.emit("connect", "started", f"Connecting to {spec.name} ({where})…")
        if spec.url:
            if not await self._prepare_custom(where):
                return
        elif spec.port is not None and not spec.is_live():
            await em.emit("connect", "error", f"Cannot reach {where}. Start the lab: python scripts/run_dvmcp_native.py")
            await em.emit("done", "error", "Run aborted — server offline.")
            return
        try:
            session_cm = open_session(spec)
            session = await session_cm.__aenter__()
        except BaseException as exc:      # noqa: BLE001 - surfaced to the user, not swallowed
            if isinstance(exc, (asyncio.CancelledError, KeyboardInterrupt)):
                raise
            await em.emit("connect", "error", f"MCP handshake failed ({spec.transport}): {_friendly_error(exc)}",
                          {"transport": spec.transport, "endpoint": where, "hint": self._connect_hint()})
            await em.emit("done", "error", "Run aborted — could not connect.")
            return
        try:
            await em.emit("connect", "passed", f"Connected to {spec.name}.",
                          {"source": spec.source, "endpoint": where,
                           **({"transport": spec.transport} if spec.url else {}),
                           **({"note": llm_note} if llm_note else {})})

            # 2. list_tools ----------------------------------------------------
            await em.emit("list_tools", "started", "Listing tools (tools/list)…")
            with tracer().start_as_current_span("mcp.tools_list") as ls:
                ls.set_attribute("langfuse.observation.type", "tool")
                ls.set_attribute("guardian.server", spec.name)
                listed = await list_all_tools(session)
                ls.set_attribute("guardian.tool_count", len(list(_iter_tools(listed))))
                ls.set_attribute("output.value", clip([_tool_fields(t)[0] for t in _iter_tools(listed)][:200], 3000))
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
                          f"Static analysis (CrewAI) running on {len(tools)} tool(s)…")

            async def static_progress(i: int, n: int, name: str, phase: str) -> None:
                if phase == "start" and n > 1:
                    await em.emit("static_check", "started",
                                  f"Static analysis (CrewAI) {i}/{n} - inspecting '{name}'…")
                elif phase == "done" and n > 1:
                    v = interceptor._static[name]
                    meta = interceptor.models.get(name, {}).get("static", {})
                    outcome = ("looks clean" if v.verdict == "clean"
                               else f"FLAGGED as {v.verdict}")
                    await em.emit("static_check", "started", f"Tool {i}/{n} '{name}': {outcome}",
                                  _verdict_detail(v, meta=meta),
                                  interceptor.engines.get(name, {}).get("static", "none"), meta)

            cap = _max_tools() if spec.url else None
            to_screen = listed
            if spec.url and not self.inspect_only:        # the inspection step already read every tool
                to_screen = [t for t in _iter_tools(listed) if _tool_fields(t)[0] == tool]
            await interceptor.screen_tool_metadata(
                to_screen, on_tool=static_progress, limit=cap, first=tool,
                workers=STATIC_WORKERS if use_llm else 1)
            skipped = interceptor.not_inspected
            sv = interceptor._static[tool]
            s_engine = interceptor.engines.get(tool, {}).get("static", "none")
            s_meta = interceptor.models.get(tool, {}).get("static", {})
            others = sorted(n for n, v in interceptor._static.items()
                            if n != tool and v.verdict != "clean")
            annotations = {_tool_fields(t)[0]: getattr(t, "annotations", None) or
                           (t.get("annotations") if isinstance(t, dict) else None) for t in _iter_tools(listed)}
            all_tools = [{"name": n, "verdict": v.verdict, "confidence": v.confidence,
                          "reasoning": v.reasoning, "flagged_phrases": v.flagged_phrases,
                          "engine": interceptor.engines.get(n, {}).get("static"),
                          "model": interceptor.models.get(n, {}).get("static", {}).get("model"),
                          "scope": interceptor._scope.get(n),
                          "definition_changed": n in interceptor.definition_changes,
                          "default_args": default_args_from_schema(tools[n][2]),
                          "looks_read_only": bool(spec.url) and safe_to_try(
                              n, tools[n][2], annotations.get(n), v.verdict, interceptor._scope.get(n),
                              n in interceptor.definition_changes, needs_no_input=False),
                          "safe_to_try": bool(spec.url) and safe_to_try(
                              n, tools[n][2], annotations.get(n), v.verdict, interceptor._scope.get(n),
                              n in interceptor.definition_changes),
                          "description": tools[n][1]} for n, v in interceptor._static.items()]
            change = interceptor.definition_changes.get(tool)
            detail = _verdict_detail(sv, meta=s_meta, description=tools[tool][1],
                                     requested_scope=interceptor._scope.get(tool),
                                     other_flagged_tools=others, all_tools=all_tools, not_inspected=skipped,
                                     **({"definition_change": change} if change else {}))
            flagged_all = [t["name"] for t in all_tools if t["verdict"] != "clean" or t["definition_changed"]]
            if self.inspect_only:
                # inspection mode covers the whole server, so the stage result must say so
                if flagged_all:
                    await em.emit("static_check", "flagged",
                                  f"{len(flagged_all)} of {len(all_tools)} tool descriptions flagged: "
                                  f"{', '.join(flagged_all[:12])}{'…' if len(flagged_all) > 12 else ''}", detail, s_engine, s_meta)
                else:
                    await em.emit("static_check", "passed",
                                  f"All {len(all_tools)} inspected tool descriptions look clean ✓"
                                  + (f" ({len(skipped)} more were not inspected: over the limit of {len(all_tools)} per run)"
                                     if skipped else ""), detail, s_engine, s_meta)
            elif change:
                await em.emit("static_check", "flagged",
                              f"'{tool}' changed since it was first seen: rug pull on the tool definition!",
                              detail, s_engine, s_meta)
            elif sv.verdict == "clean":
                await em.emit("static_check", "passed", f"'{tool}' metadata looks clean ✓",
                              detail, s_engine, s_meta)
            else:
                await em.emit("static_check", "flagged",
                              f"'{tool}' metadata flagged as {sv.verdict}!", detail, s_engine, s_meta)

            if self.inspect_only:
                flagged = [t for t in all_tools if t["verdict"] != "clean"]
                await em.emit("done", "flagged" if flagged else "passed",
                              f"Inspection complete — {len(flagged)} of {len(all_tools)} tool(s) flagged. "
                              "Pick a tool below to call it through the Guardian.",
                              {"inspect_only": True, "tools": all_tools, "not_inspected": skipped,
                               "engines": {t["name"]: t["engine"] for t in all_tools}})
                return

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
                with tracer().start_as_current_span("mcp.call_tool") as cs:
                    cs.set_attribute("langfuse.observation.type", "tool")
                    cs.set_attribute("guardian.server", spec.name)
                    cs.set_attribute("guardian.tool_name", tool)
                    cs.set_attribute("input.value", clip(args, 3000))
                    try:
                        response = await session.call_tool(tool, args)
                    except Exception as exc:
                        cs.record_exception(exc)
                        cs.set_attribute("langfuse.observation.level", "ERROR")
                        raise
                    text, keys = _response_text_and_keys(response)
                    cs.set_attribute("output.value", clip(text, 4000))
                    cs.set_attribute("guardian.response_chars", len(text))
                    if getattr(response, "isError", False):
                        cs.set_attribute("langfuse.observation.level", "WARNING")
                        cs.set_attribute("langfuse.observation.status_message", "the tool reported an error")
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
                r_meta = interceptor.models.get(tool, {}).get("runtime", {})
                await em.emit(
                    "runtime_check", "passed" if rv.verdict == "clean" else "flagged",
                    "Response looks like ordinary data ✓" if rv.verdict == "clean"
                    else (f"Credentials leaked in the response ({rv.verdict})!"
                          if (rv.reasoning or "").startswith("Credential scan")
                          else f"Injected instruction detected ({rv.verdict})!"),
                    _verdict_detail(rv, meta=r_meta, inspector_latency_ms=round(r_ms, 2),
                                    response_preview=_preview(text)), r_engine, r_meta)

                await em.emit("behavioral_check", "started",
                              "Updating the behavioural fingerprint (ADK anomaly agent)…")
                report = await interceptor.inspect_response_behavioral(tool, text, keys)
                history = _HISTORY.setdefault(f"{self.server_id}:{tool}", [])
                history.append({"n": len(history) + 1, "length": len(text), "keys": sorted(keys)})
                await em.emit(
                    "behavioral_check", "flagged" if report.is_anomalous else "passed",
                    report.explanation,
                    {**report.evidence, "statistical_anomaly": report.statistical_anomaly,
                     "calls_observed": fingerprint_store(self.server_id).get(tool).n_samples,
                     "history": history[-14:], "response": _preview(text, 600),
                     "previous_response": report.extra.get("previous_response", "")},
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
                # human already approved for this call - don't ask twice.
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
                           "models": {k: v.get("model") for k, v in interceptor.models.get(tool, {}).items()},
                           **({"response": _preview(text)} if released and response else {})})
        finally:
            await session_cm.__aexit__(None, None, None)


def _client_ip(ws: WebSocket) -> str:
    fwd = ws.headers.get("x-forwarded-for")
    return (fwd.split(",")[0].strip() if fwd else (ws.client.host if ws.client else "unknown"))


async def _reject(ws: WebSocket, message: str, category: str, client: str) -> None:
    """Refuse a request before any pipeline work, in the same event shape the UI already renders."""
    log_decision({"layer": "input_guard", "client": client, "category": category, "message": message})
    base = {"engine": "none", "elapsed_ms": 0, "detail": {"guard": category}}
    await ws.send_json({"stage": "connect", "status": "error", "message": message, **base})
    await ws.send_json({"stage": "done", "status": "error", "message": "Run refused.", **base})


async def _admit(ws: WebSocket, req: dict, client: str) -> tuple[bool, str | None]:
    """Input guard + (in public mode) rate limits and SSRF protection.
    Returns ``(admitted, notice)``; when not admitted the refusal has already been sent."""
    res = check_arguments(req.get("arguments"))
    if not res.ok:
        await _reject(ws, f"Input rejected by the input guard: {res.reason}.", res.category, client)
        return False, None
    if req.get("server_url"):
        res = check_url(req["server_url"])
        if not res.ok:
            await _reject(ws, f"Input rejected by the input guard: {res.reason}.", res.category, client)
            return False, None
    if not public_mode():
        return True, None
    if req.get("server_url"):
        err = await asyncio.to_thread(check_public_target, req["server_url"])
        if err:
            await _reject(ws, err, "ssrf", client)
            return False, None
    err = limiter().acquire(client)
    if err:
        await _reject(ws, err, "rate_limit", client)
        return False, None
    if req.get("use_llm") and not limiter().take_llm_run():
        limiter().release(client)
        await _reject(ws, "Today's budget of AI-inspector runs on this public site is used up. "
                          "It resets at 00:00 UTC; please try again then.", "budget", client)
        return False, None
    return True, restrict_execution(req)


@router.post("/probe", dependencies=[Depends(access.require_access)])
async def probe(body: dict, request: Request) -> dict:
    """What does this MCP endpoint speak, and does it want credentials? Called before a run so the page only
    asks for authentication once the server's own requirements are known. Nothing is inspected or executed."""
    url = str((body or {}).get("url") or "").strip()
    client = request.headers.get("x-forwarded-for", "").split(",")[0].strip() or (request.client.host if request.client else "unknown")
    res = check_url(url)
    if not res.ok:
        raise HTTPException(400, f"Input rejected by the input guard: {res.reason}.")
    try:
        custom_spec(url)
    except CustomServerError as exc:
        raise HTTPException(400, str(exc)) from None
    if public_mode():
        err = await asyncio.to_thread(check_public_target, url)
        if err:
            raise HTTPException(400, err)
        if not limiter().probe_allowed(client):
            raise HTTPException(429, "Too many checks from this address. Please try again later.")
    result = await live.probe_endpoint(url, {})
    if result.error:
        return {"ok": False, "error": result.error}
    return {"ok": True, "host": live.display_url(url).split("//", 1)[-1].split("/", 1)[0], "transport": result.transport,
            "auth_required": result.auth_required, "oauth_advertised": result.oauth_advertised}


@router.websocket("/ws/run")
async def ws_run(ws: WebSocket) -> None:
    if not origin_allowed(ws.headers.get("origin"), ws.headers.get("host")):
        await ws.close(code=1008)
        return
    await ws.accept()
    client, acquired = _client_ip(ws), False
    try:
        req = await ws.receive_json()
        if not isinstance(req, dict):
            await _reject(ws, "Malformed request.", "shape", client)
            return
        supplied = req.pop("access_key", None)          # never logged, never echoed
        if access.access_required():
            if access.throttled(client):
                await _reject(ws, "Too many wrong access keys. Try again in a few minutes.", "auth", client)
                return
            if not access.key_ok(supplied):
                access.record_failure(client)
                await _reject(ws, "A valid access key is required to run checks on this site.", "auth", client)
                return
        model = req.pop("model", None)
        if model:
            from src.crewai_layer.crew import uses_chain
            from src.llm_chain import PREFERRED_MODEL, get_chain

            if not (uses_chain() and model in {sl.model for sl in get_chain().slots}):
                await _reject(ws, "That model is not one of the configured inspector models.", "model", client)
                return
            PREFERRED_MODEL.set(model)
        admitted, notice = await _admit(ws, req, client)
        if not admitted:
            return
        acquired = public_mode()
        try:
            run = _Run(ws, req, ws.app.state.a2a_client)
            run.notice = notice
            run.em.set_user(client)
        except KeyError:
            await ws.send_json({"stage": "done", "status": "error",
                                "message": f"Unknown server '{req.get('server_id')}'"})
            return
        except (CustomServerError, live.AuthError) as exc:
            await ws.send_json({"stage": "connect", "status": "error", "message": str(exc),
                                "detail": {}, "engine": "none", "elapsed_ms": 0})
            await ws.send_json({"stage": "done", "status": "error", "message": "Run aborted.",
                                "detail": {}, "engine": "none", "elapsed_ms": 0})
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
        if acquired:
            limiter().release(client)
        try:
            if "run" in locals():
                run.em.finish()
        except Exception:      # noqa: BLE001
            pass
        try:
            await ws.close()
        except RuntimeError:
            pass
