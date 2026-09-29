"""Shared Google ADK plumbing: model selection + a one-shot runner helper.

Every ADK ``LlmAgent`` in this package gets its model from ``adk_model()`` so the
provider follows the same ``LLM_PROVIDER`` env var the CrewAI layer uses:
    gemini / google -> native Gemini model string (needs GOOGLE_API_KEY)
    anything else   -> ADK's LiteLlm wrapper ("openai/...", "anthropic/...",
                       "ollama_chat/...") so one .env drives both frameworks.
"""
from __future__ import annotations

import os
import uuid
from typing import Any

APP_NAME = "mcp_guardian"

_DEFAULT_MODELS = {
    "gemini": "gemini-2.0-flash",
    "google": "gemini-2.0-flash",
    "openai": "openai/gpt-4o-mini",
    "anthropic": "anthropic/claude-haiku-4-5-20251001",
    "ollama": "ollama_chat/llama3.1",
}


def adk_model() -> Any:
    provider = (os.environ.get("LLM_PROVIDER") or "openai").lower()
    name = os.environ.get("ADK_MODEL") or _DEFAULT_MODELS.get(provider, _DEFAULT_MODELS["openai"])
    if provider in ("gemini", "google"):
        return name
    from google.adk.models.lite_llm import LiteLlm

    return LiteLlm(model=name)


async def run_agent_once(agent: Any, prompt: str) -> str:
    """Run an ADK agent for one turn in a throwaway in-memory session and return
    the final response text."""
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService
    from google.genai import types

    service = InMemorySessionService()
    runner = Runner(app_name=APP_NAME, agent=agent, session_service=service)
    session = await service.create_session(app_name=APP_NAME, user_id="guardian",
                                           session_id=uuid.uuid4().hex)
    msg = types.Content(role="user", parts=[types.Part(text=prompt)])
    final = ""
    async for event in runner.run_async(user_id="guardian", session_id=session.id,
                                        new_message=msg):
        if event.is_final_response() and event.content and event.content.parts:
            final = "".join(p.text or "" for p in event.content.parts)
    return final
