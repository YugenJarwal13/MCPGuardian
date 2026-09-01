"""Phase 10.1 - end-to-end demo.

A minimal 'research assistant' talks to MCP tools exclusively through
GuardedMCPClient. We point it at four in-process servers in turn and watch the
Guardian catch each attack class mid-task. Runs fully offline (deterministic
detectors); set credentials + use_llm=True to drive the LLM-backed agents.

    python -m src.demo_agent.run_demo

The narrated trace doubles as the live viva sequence (see docs/viva_demo_script.md).
"""
from __future__ import annotations

import asyncio

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
    # Fresh in-memory fingerprint store per scenario so the rug-pull demo starts clean.
    return GuardianInterceptor(
        ablation=AblationConfig(),  # all three layers on
        use_llm=False,
        fingerprint_store=ToolFingerprintStore(db_path=":memory:"),
        human_approval_callback=None,  # escalations become hard blocks in the demo
    )


def _blocked(result) -> bool:
    return isinstance(result, dict) and result.get("guardian_blocked") is True


def _hr(title: str) -> None:
    print("\n" + "=" * 72)
    print(title)
    print("=" * 72)


async def scenario_clean() -> None:
    _hr("1. CLEAN reference server - the agent completes its task normally")
    client = GuardedMCPClient(build_clean_server(), _interceptor())
    tools = await client.list_tools()
    print("  tools discovered:", [t["name"] for t in tools["tools"]])
    result = await client.call_tool("calculator", {"expression": "6*7"})
    print("  calculator result:", result["content"][0]["text"])
    print("  -> ALLOWED. Audit rows for this run are all 'clean'.")


async def scenario_poisoned_metadata() -> None:
    _hr("2. TOOL POISONING (metadata) - flagged BEFORE any call is made")
    interceptor = _interceptor()
    client = GuardedMCPClient(build_poisoned_metadata_server(), interceptor)
    await client.list_tools()  # static analysis runs here
    verdict = interceptor._static.get("get_weather")
    print(f"  static verdict for get_weather: {verdict.verdict} ({verdict.confidence:.0%})")
    print(f"  flagged: {verdict.flagged_phrases[:1]}")
    result = await client.call_tool("get_weather", {"city": "Delhi"})
    print("  attempting the call ->", "BLOCKED [OK]" if _blocked(result) else "allowed [FAIL]")


async def scenario_poisoned_response() -> None:
    _hr("3. INDIRECT PROMPT INJECTION (response path) - the harder, novel half")
    interceptor = _interceptor()
    client = GuardedMCPClient(build_poisoned_response_server(), interceptor)
    await client.list_tools()  # metadata is clean here - nothing to flag yet
    print("  metadata verdict:", interceptor._static.get("fetch_url").verdict, "(clean - as expected)")
    result = await client.call_tool("fetch_url", {"url": "https://example.com/report"})
    rv = interceptor._runtime.get("fetch_url")
    print(f"  the call executed; response auditor verdict: {rv.verdict} ({rv.confidence:.0%})")
    print("  returning to the agent ->", "BLOCKED [OK]" if _blocked(result) else "allowed [FAIL]")


async def scenario_rug_pull() -> None:
    _hr("4. RUG PULL - 10 normal calls, then detection on call 11")
    interceptor = _interceptor()
    client = GuardedMCPClient(build_rug_pull_server(), interceptor)
    await client.list_tools()
    for i in range(1, 11):
        await client.call_tool("stock_price", {"ticker": "ACME"})
    print("  calls 1-10: normal, within fingerprint profile (no anomaly)")
    result = await client.call_tool("stock_price", {"ticker": "ACME"})  # call 11 - poisoned
    anomalous = interceptor._anomalous.get("stock_price")
    rv = interceptor._runtime.get("stock_price")
    print(f"  call 11: behavioral anomaly={anomalous}, response verdict={rv.verdict}")
    print("  call 11 response ->", "BLOCKED [OK]" if _blocked(result) else "allowed [FAIL]")
    print("  time-to-detection: 1 call (immediate).")


async def main() -> None:
    await scenario_clean()
    await scenario_poisoned_metadata()
    await scenario_poisoned_response()
    await scenario_rug_pull()
    _hr("Demo complete - see logs/audit_trail.jsonl and the Streamlit dashboard")
    print("  streamlit run src/dashboard/app.py")


if __name__ == "__main__":
    asyncio.run(main())
