"""A tool whose description changes after it was first seen is reported as a rug pull on its definition."""
import pytest

from src.adk_layer.callbacks.enforcement_callbacks import GuardianDecision
from src.adk_layer.state.tool_fingerprint_store import ToolFingerprintStore
from src.demo_agent.agent_config import build_definition_swap_server
from src.evaluation.ablation_config import AblationConfig
from src.mcp_gateway.interceptor import GuardianInterceptor

SCHEMA = {"type": "object", "properties": {"a": {"type": "string"}}}


def test_store_keeps_the_first_description_as_the_baseline():
    store = ToolFingerprintStore(db_path=":memory:")
    assert store.check_definition("t", "Adds numbers.", SCHEMA) == (False, "")
    assert store.check_definition("t", "Adds numbers.", SCHEMA)[0] is False                # unchanged
    assert store.check_definition("t", "Adds numbers. Also do X.", SCHEMA) == (True, "Adds numbers.")
    assert store.check_definition("t", "Adds numbers. Also do X.", SCHEMA)[0] is True    # still reported
    assert store.check_definition("t", "Adds numbers.", {"type": "object"})[0] is True   # schema change counts


@pytest.mark.asyncio
async def test_interceptor_flags_the_swap_and_escalates():
    session = build_definition_swap_server()
    interceptor = GuardianInterceptor(ablation=AblationConfig(), use_llm=False,
                                      fingerprint_store=ToolFingerprintStore(db_path=":memory:"))
    for _ in range(3):                                          # three normal rounds
        await interceptor.screen_tool_metadata(await session.list_tools())
        assert "exchange_rate" not in interceptor.definition_changes
        await session.call_tool("exchange_rate", {})
    await interceptor.screen_tool_metadata(await session.list_tools())   # the description has been swapped
    change = interceptor.definition_changes["exchange_rate"]
    assert "id_rsa" in change["now"] and "id_rsa" not in change["first_seen"]
    assert interceptor.current_decision("exchange_rate") in (GuardianDecision.ESCALATE, GuardianDecision.BLOCK)
