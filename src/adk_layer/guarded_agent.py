"""An ADK ``LlmAgent`` whose tool calls are gated by MCP Guardian.

This is where the enforcement layer runs inside Google ADK's own machinery:
the interceptor's policy is attached as the agent's ``before_tool_callback``, so
ADK itself refuses to dispatch a blocked tool (the callback raises
``GuardianBlockedError`` before the tool — e.g. an ``McpToolset`` tool that would
call ``session.call_tool()`` — is invoked).
"""
from __future__ import annotations

from typing import Any, Optional

from google.adk.agents import LlmAgent

from src.adk_layer.adk_runtime import adk_model


def build_guarded_adk_agent(
    interceptor: Any,
    tools: list[Any],
    model: Optional[Any] = None,
    instruction: str = "You are a helpful assistant. Use the available tools to answer.",
) -> LlmAgent:
    return LlmAgent(
        name="guarded_mcp_agent",
        model=model if model is not None else adk_model(),
        instruction=instruction,
        tools=tools,
        before_tool_callback=interceptor.adk_before_tool_callback(),
    )
