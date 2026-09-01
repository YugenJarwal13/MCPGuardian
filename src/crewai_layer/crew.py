"""Phase 3.4 / 4 — assemble and run the inspection crews.

``run_static_analysis`` (Phase 3) and ``run_runtime_inspection`` (Phase 4) both
follow the same policy: use the LLM-backed CrewAI agent when provider credentials
are configured, otherwise fall back to the deterministic heuristic so the
pipeline stays fully runnable and testable offline. The two paths share the
``InspectionVerdict`` output contract, so callers never branch on which ran.
"""
from __future__ import annotations

import os

from src.crewai_layer.heuristics import static_heuristic
from src.crewai_layer.schemas import InspectionVerdict

_PROVIDER_KEY_ENV = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "gemini": "GOOGLE_API_KEY",
    "google": "GOOGLE_API_KEY",
}


def llm_available() -> bool:
    """True when crewai is importable AND the active provider has a key set.
    Ollama (local) is treated as always-available if selected."""
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


def run_static_analysis(
    tool_name: str, tool_description: str, tool_schema: dict, use_llm: bool | None = None
) -> InspectionVerdict:
    """Return an InspectionVerdict for a tool's metadata."""
    if use_llm is None:
        use_llm = llm_available()

    if not use_llm:
        return static_heuristic(tool_name, tool_description, tool_schema)

    # LLM path — lazy imports so this module loads without crewai installed.
    from crewai import Crew

    from src.crewai_layer.agents.static_analysis_agent import static_analysis_agent
    from src.crewai_layer.tasks.static_analysis_task import build_static_analysis_task

    task = build_static_analysis_task(
        static_analysis_agent, tool_name, tool_description, tool_schema
    )
    crew = Crew(agents=[static_analysis_agent], tasks=[task])
    result = crew.kickoff()
    verdict = getattr(result, "pydantic", None)
    # Defensive: if structured output failed, fall back rather than crash a demo.
    return verdict if isinstance(verdict, InspectionVerdict) else static_heuristic(
        tool_name, tool_description, tool_schema
    )
