"""GuardianInterceptor — the orchestration point every MCP call routes through.

Wiring, by phase:
    Phase 3  -> screen_tool_metadata  runs the static-analysis crew
    Phase 4  -> screen_tool_response  runs the runtime-inspection crew
    Phase 5  -> screen_tool_response  also updates the behavioural fingerprint
    Phase 6  -> pre_call_check        combines verdicts + enforces allow/block/escalate

Default construction (``GuardianInterceptor()``) leaves every layer off, so it is
a faithful pass-through (the Phase 2 plumbing contract). Use
``build_default_interceptor()`` for a fully-wired instance.
"""
from __future__ import annotations

import json
import uuid
from typing import Any, Awaitable, Callable, Optional

from src.adk_layer.behavioral_anomaly_agent import BehavioralAnomalyAgent
from src.adk_layer.callbacks.enforcement_callbacks import (
    GuardianBlockedError,
    GuardianDecision,
    combine_verdicts,
    enforce,
    make_guardian_before_tool_callback,
)
from src.adk_layer.state.session_schema import ToolFingerprint
from src.adk_layer.state.tool_fingerprint_store import ToolFingerprintStore
from src.audit import log_decision
from src.config import allowlist as load_allowlist
from src.crewai_layer.crew import run_runtime_inspection_timed, run_static_analysis
from src.crewai_layer.schemas import InspectionVerdict
from src.data.schemas import ToolTestCase
from src.evaluation.ablation_config import AblationConfig


# --- helpers to read heterogeneous MCP shapes (attribute objects OR dicts) ----
def _attr(obj: Any, name: str, default=None):
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _iter_tools(listed: Any):
    tools = _attr(listed, "tools", listed)
    return tools if isinstance(tools, list) else []


def _tool_fields(tool: Any) -> tuple[str, str, dict]:
    name = _attr(tool, "name", "") or ""
    desc = _attr(tool, "description", "") or ""
    schema = _attr(tool, "inputSchema", None) or _attr(tool, "tool_schema", None) or {}
    return name, desc, (schema if isinstance(schema, dict) else {"raw": schema})


def _response_text_and_keys(response: Any) -> tuple[str, set[str]]:
    # MCP CallToolResult -> .content list of items with .text; else stringify.
    content = _attr(response, "content", None)
    if isinstance(content, list):
        parts = [str(_attr(item, "text", item)) for item in content]
        text = "\n".join(parts)
    else:
        text = response if isinstance(response, str) else json.dumps(response, default=str)
    keys: set[str] = set()
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            keys = set(parsed.keys())
    except (json.JSONDecodeError, TypeError):
        pass
    return text, keys


def _refusal(tool_name: str, reason: str) -> dict:
    """An MCP-shaped refusal result — never a raw Python exception surfaced to the
    reasoning agent."""
    return {
        "isError": True,
        "guardian_blocked": True,
        "content": [{"type": "text", "text": f"[MCP Guardian] {reason}"}],
        "tool_name": tool_name,
    }


class GuardianInterceptor:
    def __init__(
        self,
        ablation: Optional[AblationConfig] = None,
        use_llm: Optional[bool] = None,
        fingerprint_store: Optional[ToolFingerprintStore] = None,
        anomaly_agent: Optional[BehavioralAnomalyAgent] = None,
        allowlist: Optional[dict] = None,
        human_approval_callback: Optional[Callable[[str], Awaitable[bool]]] = None,
        a2a_client: Optional[Any] = None,
    ):
        # No ablation given => legacy no-op configuration (Phase 2 contract).
        self._ablation = ablation or AblationConfig(
            enable_static=False, enable_runtime=False, enable_behavioral=False
        )
        self._use_llm = use_llm
        self._store = fingerprint_store
        self._anomaly_agent = anomaly_agent or BehavioralAnomalyAgent(use_llm=use_llm)
        self._allowlist = allowlist if allowlist is not None else load_allowlist()
        self._human = human_approval_callback
        # When set (RemoteA2AClient on the live path), every screened call's
        # combined verdict is shipped to the ADK case manager over A2A.
        self._a2a = a2a_client
        self._evidence: dict[str, list[str]] = {}

        # Per-tool verdict cache the enforcement gate reads at call time.
        self._static: dict[str, InspectionVerdict] = {}
        self._runtime: dict[str, InspectionVerdict] = {}
        self._anomalous: dict[str, bool] = {}
        self._scope: dict[str, Optional[str]] = {}

    # -- Phase 3: metadata screening ------------------------------------------
    async def screen_tool_metadata(self, tools: Any) -> Any:
        if not self._ablation.enable_static:
            return tools
        for tool in _iter_tools(tools):
            name, desc, schema = _tool_fields(tool)
            verdict = run_static_analysis(name, desc, schema, use_llm=self._use_llm)
            self._static[name] = verdict
            self._scope[name] = ToolTestCase(
                case_id="live", source="custom", tool_name=name, tool_description=desc,
                tool_schema=schema, ground_truth_label="clean",
            ).requested_scope()
            log_decision({
                "layer": "static", "tool_name": name, "verdict": verdict.verdict,
                "confidence": verdict.confidence, "reasoning": verdict.reasoning,
                "flagged_phrases": verdict.flagged_phrases,
            })
        return tools

    # -- Phase 6: pre-call enforcement gate -----------------------------------
    def verdicts_for(self, name: str) -> dict:
        """Everything ``combine_verdicts`` needs for one tool (minus allowlist)."""
        return {
            "static_verdict": self._static.get(name),
            "runtime_verdict": self._runtime.get(name),
            "is_behaviorally_anomalous": self._anomalous.get(name, False),
            "requested_scope": self._scope.get(name),
        }

    def adk_before_tool_callback(self):
        """The same gate as ``pre_call_check``, as a Google ADK
        ``before_tool_callback`` (see ``src/adk_layer/guarded_agent.py``)."""
        return make_guardian_before_tool_callback(
            self.verdicts_for, self._allowlist, human_approval_callback=self._human
        )

    async def pre_call_check(self, name: str, arguments: dict, session: Any) -> Optional[Any]:
        decision = combine_verdicts(allowlist=self._allowlist, **self.verdicts_for(name))
        try:
            await enforce(decision, name, human_approval_callback=self._human)
        except GuardianBlockedError as exc:
            log_decision({"layer": "enforcement", "tool_name": name,
                          "decision": decision.value, "blocked": True, "reason": str(exc)})
            return _refusal(name, str(exc))
        log_decision({"layer": "enforcement", "tool_name": name,
                      "decision": decision.value, "blocked": False})
        return None

    # -- Phase 7 / 11.3: CrewAI verdict -> A2A -> ADK case manager -------------
    async def report_case(self, name: str, case_id: Optional[str] = None) -> Optional[Any]:
        """Send this tool's current combined verdict to the case manager over the
        configured A2A transport. Returns the manager's case (or None if no
        transport is configured)."""
        if self._a2a is None:
            return None
        from src.a2a_bridge.bridge import GuardianVerdictMessage, send_verdict_to_case_manager

        static, runtime = self._static.get(name), self._runtime.get(name)
        confs = [v.confidence for v in (static, runtime) if v is not None]
        message = GuardianVerdictMessage(
            case_id=case_id or f"{name}-{uuid.uuid4().hex[:8]}",
            tool_name=name,
            static_verdict=static.verdict if static else None,
            runtime_verdict=runtime.verdict if runtime else None,
            behavioral_anomaly=self._anomalous.get(name, False),
            combined_confidence=max(confs) if confs else 0.0,
            evidence=[*(static.flagged_phrases if static else []),
                      *(runtime.flagged_phrases if runtime else []),
                      *self._evidence.get(name, [])],
        )
        return await send_verdict_to_case_manager(message, self._a2a)

    # -- Phase 4/5: response screening ----------------------------------------
    async def screen_tool_response(self, name: str, response: Any) -> Any:
        text, keys = _response_text_and_keys(response)

        if self._ablation.enable_runtime:
            verdict, elapsed_ms = run_runtime_inspection_timed(name, text, use_llm=self._use_llm)
            self._runtime[name] = verdict
            log_decision({"layer": "runtime", "tool_name": name, "verdict": verdict.verdict,
                          "confidence": verdict.confidence, "reasoning": verdict.reasoning,
                          "flagged_phrases": verdict.flagged_phrases, "latency_ms": round(elapsed_ms, 3)})
        else:
            verdict = None

        if self._ablation.enable_behavioral and self._store is not None:
            fp = self._store.get(name)
            fp, report = await self._anomaly_agent.analyze_async(fp, text, keys, latency_ms=0.0)
            self._store.update(fp)
            self._anomalous[name] = report.is_anomalous
            if report.is_anomalous:
                self._evidence[name] = [f"z={report.evidence['z_score']}",
                                        *(f"new_key:{k}" for k in report.evidence["new_keys"])]
            log_decision({"layer": "behavioral", "tool_name": name,
                          "anomalous": report.is_anomalous, "reasoning": report.explanation,
                          "evidence": report.evidence, "engine": report.engine,
                          "statistical_anomaly": report.statistical_anomaly})

        # Post-response enforcement: block/redact a malicious response.
        decision = combine_verdicts(
            static_verdict=self._static.get(name),
            runtime_verdict=self._runtime.get(name),
            is_behaviorally_anomalous=self._anomalous.get(name, False),
            requested_scope=self._scope.get(name),
            allowlist=self._allowlist,
        )
        if decision == GuardianDecision.BLOCK:
            log_decision({"layer": "enforcement", "tool_name": name, "decision": "block",
                          "blocked": True, "phase": "response", "reason": "malicious response"})
            return _refusal(name, "Response blocked: injected instruction detected.")
        return response


def build_default_interceptor(
    ablation: Optional[AblationConfig] = None,
    use_llm: Optional[bool] = None,
    human_approval_callback: Optional[Callable[[str], Awaitable[bool]]] = None,
) -> GuardianInterceptor:
    """A fully-wired interceptor: all three layers on (unless overridden by
    ``ablation``), backed by the persistent fingerprint store."""
    from src.config import resolve_path

    return GuardianInterceptor(
        ablation=ablation or AblationConfig(),
        use_llm=use_llm,
        fingerprint_store=ToolFingerprintStore(db_path=resolve_path("fingerprint_db")),
        human_approval_callback=human_approval_callback,
    )
