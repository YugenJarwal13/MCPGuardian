"""Phase 11.2 — enforcement through Google ADK's own tool-dispatch machinery.

A scripted ``BaseLlm`` (no API key needed) makes a real ADK ``LlmAgent`` emit a
function call; ADK then runs the Guardian ``before_tool_callback``. A blocked
tool's body must never execute.
"""
from __future__ import annotations

from typing import AsyncGenerator

import pytest
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.tools import FunctionTool
from google.genai import types

from src.adk_layer.adk_runtime import run_agent_once
from src.adk_layer.callbacks.enforcement_callbacks import GuardianBlockedError
from src.adk_layer.guarded_agent import build_guarded_adk_agent
from src.crewai_layer.schemas import InspectionVerdict
from src.evaluation.ablation_config import AblationConfig
from src.mcp_gateway.interceptor import GuardianInterceptor

ALLOWLIST = {
    "always_require_human_approval": [{"scope": "filesystem_write"}],
    "auto_block_on_verdict": ["malicious"],
    "escalate_on_verdict": ["suspicious"],
}


class ScriptedLlm(BaseLlm):
    """Calls ``tool_name`` once, then answers 'done'."""

    tool_name: str = ""

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        already_called = any(
            p.function_response for c in llm_request.contents for p in (c.parts or [])
        )
        if already_called:
            part = types.Part(text="done")
        else:
            part = types.Part(function_call=types.FunctionCall(name=self.tool_name, args={"city": "Paris"}))
        yield LlmResponse(content=types.Content(role="model", parts=[part]))


def _setup(verdict: str):
    calls: list[str] = []

    def get_weather(city: str) -> str:
        """Returns the weather for a city."""
        calls.append(city)
        return f"Sunny in {city}"

    interceptor = GuardianInterceptor(ablation=AblationConfig(), use_llm=False, allowlist=ALLOWLIST)
    interceptor._static["get_weather"] = InspectionVerdict(
        verdict=verdict, confidence=0.9, reasoning="test")
    agent = build_guarded_adk_agent(
        interceptor, tools=[FunctionTool(get_weather)],
        model=ScriptedLlm(model="scripted", tool_name="get_weather"))
    return agent, calls


async def test_adk_callback_blocks_malicious_tool_before_dispatch():
    agent, calls = _setup("malicious")
    with pytest.raises(GuardianBlockedError):
        await run_agent_once(agent, "weather in Paris?")
    assert calls == []  # the tool body never ran


async def test_adk_callback_allows_clean_tool():
    agent, calls = _setup("clean")
    assert await run_agent_once(agent, "weather in Paris?") == "done"
    assert calls == ["Paris"]
