"""Phase 10.1 - end-to-end demo.

A minimal 'research assistant' talks to MCP tools exclusively through
GuardedMCPClient. We point it at four in-process servers in turn and watch the
Guardian catch each attack class mid-task. Runs fully offline (deterministic
detectors); set credentials + use_llm=True to drive the LLM-backed agents.

    python -m src.demo_agent.run_demo                 # offline fixtures
    python -m src.demo_agent.run_demo --live          # real DVMCP servers (ports 9001-9010)
    python -m src.demo_agent.run_demo --live --interactive   # you approve/deny escalations

``--live`` needs the lab running (``python scripts/run_dvmcp_native.py``). The
live UI (``scripts/run_api.sh`` + ``scripts/run_frontend.sh``) is the primary
viva demo; this terminal version is the fallback (see docs/viva_demo_script.md).
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib

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


# --------------------------------------------------------------------------- live
DVMCP_HOST = "127.0.0.1"


@contextlib.asynccontextmanager
async def _live_session(port: int):
    from mcp import ClientSession
    from mcp.client.sse import sse_client

    async with sse_client(f"http://{DVMCP_HOST}:{port}/sse") as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session


def _live_interceptor(interactive: bool) -> GuardianInterceptor:
    from src.adk_layer.callbacks.enforcement_callbacks import cli_human_approval

    async def reviewer_approves(tool_name: str) -> bool:
        print(f"  [reviewer] '{tool_name}' escalated for human approval -> APPROVED "
              "(scripted; use --interactive to decide yourself)")
        return True

    return GuardianInterceptor(
        ablation=AblationConfig(), use_llm=None,   # LLM if configured, else heuristics
        fingerprint_store=ToolFingerprintStore(db_path=":memory:"),
        human_approval_callback=cli_human_approval if interactive else reviewer_approves,
    )


def _text(result) -> str:
    if isinstance(result, dict):
        return result["content"][0]["text"]
    return "\n".join(getattr(c, "text", str(c)) for c in result.content)


async def live_clean(interactive: bool) -> None:
    _hr("LIVE 1. Challenge 6 server, benign tool - read a public announcement")
    interceptor = _live_interceptor(interactive)
    async with _live_session(9006) as session:
        client = GuardedMCPClient(session, interceptor)
        await client.list_tools()
        v = interceptor._static["read_document"]
        print(f"  static verdict for read_document: {v.verdict} "
              f"[{interceptor.engines['read_document']['static']}]")
        result = await client.call_tool("read_document", {"document_name": "public_announcement.txt"})
        print("  ->", "BLOCKED" if _blocked(result) else "ALLOWED", "|", " ".join(_text(result).split())[:70])


async def live_poisoned_metadata(interactive: bool) -> None:
    _hr("LIVE 2. Challenge 10 - real <IMPORTANT> poisoned description, blocked pre-call")
    interceptor = _live_interceptor(interactive)
    async with _live_session(9010) as session:
        client = GuardedMCPClient(session, interceptor)
        await client.list_tools()
        v = interceptor._static["get_user_profile"]
        print(f"  static verdict for get_user_profile: {v.verdict} ({v.confidence:.0%}) "
              f"[{interceptor.engines['get_user_profile']['static']}]")
        print(f"  flagged: {v.flagged_phrases}")
        result = await client.call_tool("get_user_profile", {"username": "alice"})
        print("  attempting the call ->", "BLOCKED [OK]" if _blocked(result) else "allowed [FAIL]")


async def live_poisoned_response(interactive: bool) -> None:
    from src.api.servers import CH6_DEMO_DOCUMENT

    _hr("LIVE 3. Challenge 6 - injection echoed back in a real tool response")
    interceptor = _live_interceptor(interactive)
    async with _live_session(9006) as session:
        client = GuardedMCPClient(session, interceptor)
        await client.list_tools()
        print("  metadata verdict:", interceptor._static["upload_and_process_document"].verdict,
              "(the tool writes files, so policy asks a human first)")
        result = await client.call_tool("upload_and_process_document",
                                        {"document_name": "q3_report.txt", "content": CH6_DEMO_DOCUMENT})
        rv = interceptor._runtime.get("upload_and_process_document")
        if rv is not None:
            print(f"  the call executed; response auditor verdict: {rv.verdict} "
                  f"[{interceptor.engines['upload_and_process_document']['runtime']}] "
                  f"flagged={rv.flagged_phrases}")
        print("  returning to the agent ->", "BLOCKED [OK]" if _blocked(result) else "allowed [FAIL]")


async def live_known_gap(interactive: bool) -> None:
    _hr("LIVE 4. Challenge 2 - real tool poisoning (known gap for the heuristic path)")
    interceptor = _live_interceptor(interactive)
    async with _live_session(9002) as session:
        client = GuardedMCPClient(session, interceptor)
        await client.list_tools()
        v = interceptor._static["get_company_data"]
        engine = interceptor.engines["get_company_data"]["static"]
        print(f"  static verdict for get_company_data: {v.verdict} [{engine}]")
        if v.verdict == "clean":
            print("  -> MISSED. The regex heuristic has no rule for this <IMPORTANT> wording;")
            print("     this is the case the LLM agent (v2 prompt) is meant to catch.")


async def main_live(interactive: bool) -> None:
    for scenario in (live_clean, live_poisoned_metadata, live_poisoned_response, live_known_gap):
        try:
            await scenario(interactive)
        except OSError as exc:
            print(f"  lab not reachable ({exc}); start it: python scripts/run_dvmcp_native.py")
            return
    _hr("Live demo complete - see logs/audit_trail.jsonl and the Streamlit dashboard")


async def main() -> None:
    await scenario_clean()
    await scenario_poisoned_metadata()
    await scenario_poisoned_response()
    await scenario_rug_pull()
    _hr("Demo complete - see logs/audit_trail.jsonl and the Streamlit dashboard")
    print("  streamlit run src/dashboard/app.py")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true", help="use the running DVMCP lab")
    ap.add_argument("--interactive", action="store_true", help="approve escalations yourself")
    args = ap.parse_args()
    asyncio.run(main_live(args.interactive) if args.live else main())
