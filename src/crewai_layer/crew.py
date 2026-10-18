"""Phase 3.4 / 4 — assemble and run the inspection crews.

``run_static_analysis`` (Phase 3) and ``run_runtime_inspection`` (Phase 4) both
follow the same policy: use the LLM-backed CrewAI agent when provider credentials
are configured, otherwise fall back to the deterministic heuristic so the
pipeline stays fully runnable and testable offline. The two paths share the
``InspectionVerdict`` output contract, so callers never branch on which ran.

Phase 11.4 — which path ACTUALLY ran is now explicit. ``analyze_static`` /
``analyze_runtime`` return ``(verdict, engine)`` where engine is one of:

    "llm"                 the CrewAI agent produced a valid structured verdict
    "heuristic"           the deterministic path was chosen (use_llm False / no key)
    "heuristic_fallback"  the LLM path was attempted but failed (exception or
                          unparseable output) and the heuristic answered instead
    "timeout"             the LLM call exceeded ``timeouts.*_s`` in settings.yaml;
                          the verdict is ``suspicious`` so the policy ESCALATES
                          (an inconclusive agent must never silently allow)

Every audit record carries this value, so heuristic numbers can never be
reported as LLM numbers by accident.
"""
from __future__ import annotations

import concurrent.futures
import logging
import os
import time

# CrewAI phones home with anonymous telemetry by default; this gateway inspects
# potentially sensitive tool text, so keep it off.
os.environ.setdefault("CREWAI_DISABLE_TELEMETRY", "true")
os.environ.setdefault("CREWAI_DISABLE_TRACKING", "true")
os.environ.setdefault("OTEL_SDK_DISABLED", "true")

from src.crewai_layer.heuristics import runtime_heuristic, static_heuristic
from src.crewai_layer.schemas import InspectionVerdict

log = logging.getLogger(__name__)

ENGINE_LLM = "llm"
ENGINE_HEURISTIC = "heuristic"
ENGINE_FALLBACK = "heuristic_fallback"
ENGINE_TIMEOUT = "timeout"

# Agent calls run on this pool so they can be abandoned on timeout. A timed-out
# call keeps its worker thread until the provider returns (Python cannot kill a
# thread); the pool size bounds how many can pile up.
_POOL = concurrent.futures.ThreadPoolExecutor(max_workers=8, thread_name_prefix="crew")

_PROVIDER_KEY_ENV = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "gemini": "GOOGLE_API_KEY",
    "google": "GOOGLE_API_KEY",
}

# LiteLLM-style model ids CrewAI understands, per provider.
_CREWAI_DEFAULT_MODELS = {
    "openai": "gpt-4o-mini",
    "anthropic": "anthropic/claude-haiku-4-5-20251001",
    "gemini": "gemini/gemini-2.0-flash",
    "google": "gemini/gemini-2.0-flash",
    "ollama": "ollama/llama3.1",
}


_CHAIN_PROVIDERS = ("openrouter", "ollama")


def _provider() -> str:
    from src.config import settings

    settings()  # ensures .env is loaded into os.environ (shell values win)
    return (os.environ.get("LLM_PROVIDER") or settings().get("llm", {}).get("provider", "openai")).lower()


def uses_chain() -> bool:
    """OpenRouter / Ollama go through the fallback chain (src/llm_chain.py)."""
    return _provider() in _CHAIN_PROVIDERS


def llm_available() -> bool:
    """True when crewai is importable AND the active provider can answer: a key for
    hosted providers, a reachable server with the model pulled for Ollama, and for
    the OpenRouter chain a key or a reachable local fallback."""
    try:
        import crewai  # noqa: F401
    except ImportError:
        return False
    if uses_chain():
        from src.llm_chain import chain_available

        return chain_available()
    return bool(os.environ.get(_PROVIDER_KEY_ENV.get(_provider(), "OPENAI_API_KEY")))


def _crewai_llm():
    """The CrewAI LLM for the configured provider (temperature from settings)."""
    from crewai import LLM

    from src.config import settings

    provider = (os.environ.get("LLM_PROVIDER") or "openai").lower()
    model = os.environ.get("LLM_MODEL") or _CREWAI_DEFAULT_MODELS.get(provider, "gpt-4o-mini")
    kwargs = {"temperature": settings().get("llm", {}).get("temperature", 0.0)}
    if provider == "ollama":
        kwargs["base_url"] = os.environ.get("LOCAL_LLM_ENDPOINT", "http://localhost:11434")
    return LLM(model=model, **kwargs)


def _timeout_s(kind: str) -> float:
    """``timeouts.static_analysis_s`` / ``timeouts.runtime_inspection_s``."""
    from src.config import settings

    override = os.environ.get("GUARDIAN_AGENT_TIMEOUT_S")
    if override:
        return float(override)
    return float(settings().get("timeouts", {}).get(f"{kind}_s", 30))


def _timeout_verdict(kind: str, seconds: float) -> InspectionVerdict:
    return InspectionVerdict(
        verdict="suspicious", confidence=0.0,
        reasoning=(f"The {kind.replace('_', ' ')} agent did not answer within {seconds:g}s. "
                   "An inconclusive inspection is escalated for human review rather "
                   "than silently allowed."),
    )


def _kickoff_with_timeout(kind: str, agent, task_builder, *args):
    """Run ``_kickoff`` with the configured wall-clock budget. Returns
    ``((verdict_or_None, meta), timed_out)``; exceptions propagate to the caller."""
    seconds = _timeout_s(kind)
    future = _POOL.submit(_kickoff, agent, task_builder, *args)
    try:
        return future.result(timeout=seconds), False
    except concurrent.futures.TimeoutError:
        future.cancel()
        log.warning("%s agent timed out after %ss", kind, seconds)
        return (None, {}), True


def _make_llm():
    if uses_chain():
        from src.crewai_layer.chain_llm import ChainCrewLLM

        return ChainCrewLLM()
    return _crewai_llm()


def _kickoff(agent, task_builder, *args) -> tuple[InspectionVerdict | None, dict]:
    """Run one CrewAI crew. Returns ``(verdict_or_None, meta)``; ``meta`` names the
    provider/model that answered (read in THIS thread, where the call happened)."""
    from crewai import Crew

    llm = _make_llm()
    agent = agent.model_copy(update={"llm": llm, "verbose": False, "max_iter": 3})
    task = task_builder(agent, *args)
    result = Crew(agents=[agent], tasks=[task]).kickoff()
    verdict = getattr(result, "pydantic", None)
    if uses_chain():
        from src.crewai_layer.chain_llm import pop_meta

        meta = pop_meta(getattr(llm, "token", None)) or {}
    else:
        meta = {"provider": _provider(), "model": os.environ.get("LLM_MODEL")}
    return (verdict if isinstance(verdict, InspectionVerdict) else None), meta


def _analyze(kind: str, heuristic_call, agent_import, task_builder_import, args: tuple,
             use_llm: bool | None):
    """Shared engine selection. Returns ``(verdict, engine, meta)``."""
    if use_llm is None:
        use_llm = llm_available()
    if not use_llm:
        return heuristic_call(), ENGINE_HEURISTIC, {}
    agent, builder = agent_import(), task_builder_import()
    meta: dict = {}
    try:
        (verdict, meta), timed_out = _kickoff_with_timeout(kind, agent, builder, *args)
    except Exception as exc:  # network/provider errors must not crash the gateway
        log.warning("%s LLM path failed: %s", kind, exc)
        verdict, timed_out, meta = None, False, {"error": f"{type(exc).__name__}: {str(exc)[:200]}"}
    if timed_out:
        return _timeout_verdict(kind, _timeout_s(kind)), ENGINE_TIMEOUT, {"error": "timeout"}
    if verdict is None:
        return heuristic_call(), ENGINE_FALLBACK, meta
    return verdict, ENGINE_LLM, meta


def analyze_static_meta(
    tool_name: str, tool_description: str, tool_schema: dict, use_llm: bool | None = None
) -> tuple[InspectionVerdict, str, dict]:
    """Static verdict + engine + ``meta`` (provider/model/method/latency of the call)."""
    def agent():
        from src.crewai_layer.agents.static_analysis_agent import static_analysis_agent
        return static_analysis_agent

    def builder():
        from src.crewai_layer.tasks.static_analysis_task import build_static_analysis_task
        return build_static_analysis_task

    return _analyze("static_analysis",
                    lambda: static_heuristic(tool_name, tool_description, tool_schema),
                    agent, builder, (tool_name, tool_description, tool_schema), use_llm)


def analyze_runtime_meta(
    tool_name: str, tool_response: str, use_llm: bool | None = None
) -> tuple[InspectionVerdict, str, dict]:
    """Runtime verdict + engine + ``meta`` for a tool's live RESPONSE body."""
    def agent():
        from src.crewai_layer.agents.runtime_inspection_agent import runtime_inspection_agent
        return runtime_inspection_agent

    def builder():
        from src.crewai_layer.tasks.runtime_inspection_task import build_runtime_inspection_task
        return build_runtime_inspection_task

    return _analyze("runtime_inspection", lambda: runtime_heuristic(tool_name, tool_response),
                    agent, builder, (tool_name, tool_response), use_llm)


def analyze_static(
    tool_name: str, tool_description: str, tool_schema: dict, use_llm: bool | None = None
) -> tuple[InspectionVerdict, str]:
    """Static verdict for a tool's metadata, plus the engine that produced it."""
    verdict, engine, _meta = analyze_static_meta(tool_name, tool_description, tool_schema, use_llm)
    return verdict, engine


def analyze_runtime(
    tool_name: str, tool_response: str, use_llm: bool | None = None
) -> tuple[InspectionVerdict, str]:
    """Runtime verdict for a tool's live RESPONSE body, plus the engine."""
    verdict, engine, _meta = analyze_runtime_meta(tool_name, tool_response, use_llm)
    return verdict, engine


def run_static_analysis(
    tool_name: str, tool_description: str, tool_schema: dict, use_llm: bool | None = None
) -> InspectionVerdict:
    """Return an InspectionVerdict for a tool's metadata."""
    return analyze_static(tool_name, tool_description, tool_schema, use_llm)[0]


def run_runtime_inspection(
    tool_name: str, tool_response: str, use_llm: bool | None = None
) -> InspectionVerdict:
    """Return an InspectionVerdict for a tool's live RESPONSE body."""
    return analyze_runtime(tool_name, tool_response, use_llm)[0]


def analyze_runtime_timed(
    tool_name: str, tool_response: str, use_llm: bool | None = None
) -> tuple[InspectionVerdict, str, float]:
    """``(verdict, engine, elapsed_ms)`` — latency is a first-class report number."""
    verdict, engine, elapsed_ms, _meta = analyze_runtime_timed_meta(tool_name, tool_response, use_llm)
    return verdict, engine, elapsed_ms


def analyze_runtime_timed_meta(
    tool_name: str, tool_response: str, use_llm: bool | None = None
) -> tuple[InspectionVerdict, str, float, dict]:
    start = time.monotonic()
    verdict, engine, meta = analyze_runtime_meta(tool_name, tool_response, use_llm=use_llm)
    return verdict, engine, (time.monotonic() - start) * 1000, meta


def run_runtime_inspection_timed(
    tool_name: str, tool_response: str, use_llm: bool | None = None
) -> tuple[InspectionVerdict, float]:
    """As above, but also returns per-call latency in milliseconds.

    This agent runs on EVERY tool call in production use, so its overhead is a
    first-class number for the final report — measure it from day one.
    """
    verdict, _engine, elapsed_ms = analyze_runtime_timed(tool_name, tool_response, use_llm)
    return verdict, elapsed_ms
