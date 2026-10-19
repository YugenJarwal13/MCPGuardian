"""Phase 10 — end-to-end demo behaviour is locked by tests.

Proves the four demo scenarios route through the real GuardedMCPClient +
interceptor pipeline and produce the expected allow/block outcomes.
"""
from __future__ import annotations

from src.adk_layer.state.tool_fingerprint_store import ToolFingerprintStore
from src.demo_agent.agent_config import (
    build_clean_server,
    build_poisoned_metadata_server,
    build_poisoned_response_server,
    build_rug_pull_server,
)
from src.evaluation.ablation_config import AblationConfig
from src.mcp_gateway.client_wrapper import GuardedMCPClient
from src.mcp_gateway.interceptor import GuardianInterceptor


def _interceptor() -> GuardianInterceptor:
    return GuardianInterceptor(
        ablation=AblationConfig(),
        use_llm=False,
        fingerprint_store=ToolFingerprintStore(db_path=":memory:"),
        human_approval_callback=None,
    )


def _blocked(result) -> bool:
    return isinstance(result, dict) and result.get("guardian_blocked") is True


async def test_clean_server_allows():
    client = GuardedMCPClient(build_clean_server(), _interceptor())
    await client.list_tools()
    result = await client.call_tool("calculator", {"expression": "6*7"})
    assert not _blocked(result)


async def test_poisoned_metadata_blocked_pre_call():
    session = build_poisoned_metadata_server()
    client = GuardedMCPClient(session, _interceptor())
    await client.list_tools()
    result = await client.call_tool("get_weather", {"city": "Delhi"})
    assert _blocked(result)
    assert session.call_log == []  # never reached the underlying server


async def test_poisoned_response_blocked_on_response():
    client = GuardedMCPClient(build_poisoned_response_server(), _interceptor())
    await client.list_tools()
    result = await client.call_tool("fetch_url", {"url": "https://example.com"})
    assert _blocked(result)


async def test_rug_pull_detected_at_call_11():
    interceptor = _interceptor()
    client = GuardedMCPClient(build_rug_pull_server(), interceptor)
    await client.list_tools()
    for _ in range(10):
        r = await client.call_tool("stock_price", {"ticker": "ACME"})
        assert not _blocked(r)
    r11 = await client.call_tool("stock_price", {"ticker": "ACME"})
    assert _blocked(r11)
    assert interceptor._anomalous.get("stock_price") is True
