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

Every audit record carries this value, so heuristic numbers can never be
reported as LLM numbers by accident.
"""
from __future__ import annotations

import logging
import os
import time

from src.crewai_layer.heuristics import runtime_heuristic, static_heuristic
from src.crewai_layer.schemas import InspectionVerdict

log = logging.getLogger(__name__)

ENGINE_LLM = "llm"
ENGINE_HEURISTIC = "heuristic"
ENGINE_FALLBACK = "heuristic_fallback"

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


def llm_available() -> bool:
    """True when crewai is importable AND the active provider has a key set.
    Ollama (local) is treated as always-available if selected."""
    from src.config import settings

    settings()  # ensures .env is loaded into os.environ
    provider = (os.environ.get("LLM_PROVIDER") or "openai").lower()
    if provider == "ollama":
        key_ok = True
    else:
        key_ok = bool(os.environ.get(_PROVIDER_KEY_ENV.get(provider, "OPENAI_API_KEY")))
    if not key_ok:
        return False
    try:
        import crewai  # noqa: F401
        return True
    except ImportError:
        return False


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


def _kickoff(agent, task_builder, *args) -> InspectionVerdict | None:
    from crewai import Crew

    agent = agent.model_copy(update={"llm": _crewai_llm(), "verbose": False})
    task = task_builder(agent, *args)
    result = Crew(agents=[agent], tasks=[task]).kickoff()
    verdict = getattr(result, "pydantic", None)
    return verdict if isinstance(verdict, InspectionVerdict) else None


def analyze_static(
    tool_name: str, tool_description: str, tool_schema: dict, use_llm: bool | None = None
) -> tuple[InspectionVerdict, str]:
    """Static verdict for a tool's metadata, plus the engine that produced it."""
    if use_llm is None:
        use_llm = llm_available()
    if not use_llm:
        return static_heuristic(tool_name, tool_description, tool_schema), ENGINE_HEURISTIC

    # LLM path — lazy imports so this module loads without crewai installed.
    from src.crewai_layer.agents.static_analysis_agent import static_analysis_agent
    from src.crewai_layer.tasks.static_analysis_task import build_static_analysis_task

    try:
        verdict = _kickoff(static_analysis_agent, build_static_analysis_task,
                           tool_name, tool_description, tool_schema)
    except Exception as exc:  # network/provider errors must not crash the gateway
        log.warning("static LLM path failed for %s: %s", tool_name, exc)
        verdict = None
    if verdict is None:
        return static_heuristic(tool_name, tool_description, tool_schema), ENGINE_FALLBACK
    return verdict, ENGINE_LLM


def analyze_runtime(
    tool_name: str, tool_response: str, use_llm: bool | None = None
) -> tuple[InspectionVerdict, str]:
    """Runtime verdict for a tool's live RESPONSE body, plus the engine."""
    if use_llm is None:
        use_llm = llm_available()
    if not use_llm:
        return runtime_heuristic(tool_name, tool_response), ENGINE_HEURISTIC

    from src.crewai_layer.agents.runtime_inspection_agent import runtime_inspection_agent
    from src.crewai_layer.tasks.runtime_inspection_task import build_runtime_inspection_task

    try:
        verdict = _kickoff(runtime_inspection_agent, build_runtime_inspection_task,
                           tool_name, tool_response)
    except Exception as exc:
        log.warning("runtime LLM path failed for %s: %s", tool_name, exc)
        verdict = None
    if verdict is None:
        return runtime_heuristic(tool_name, tool_response), ENGINE_FALLBACK
    return verdict, ENGINE_LLM


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
    start = time.monotonic()
    verdict, engine = analyze_runtime(tool_name, tool_response, use_llm=use_llm)
    return verdict, engine, (time.monotonic() - start) * 1000


def run_runtime_inspection_timed(
    tool_name: str, tool_response: str, use_llm: bool | None = None
) -> tuple[InspectionVerdict, float]:
    """As above, but also returns per-call latency in milliseconds.

    This agent runs on EVERY tool call in production use, so its overhead is a
    first-class number for the final report — measure it from day one.
    """
    verdict, _engine, elapsed_ms = analyze_runtime_timed(tool_name, tool_response, use_llm)
    return verdict, elapsed_ms
