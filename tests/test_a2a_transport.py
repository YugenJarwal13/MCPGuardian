"""Phase 11.3 — a verdict crosses a real A2A transport (HTTP JSON-RPC).

Starts the ADK case manager as an A2A server on a real socket, sends through
``RemoteA2AClient`` and asserts the case landed in the manager's ADK state.
"""
from __future__ import annotations

import pytest

pytest.importorskip("a2a")

from src.a2a_bridge.bridge import (  # noqa: E402
    GuardianVerdictMessage,
    RemoteA2AClient,
    send_verdict_to_case_manager,
)
from src.adk_layer.pipeline_manager import PipelineManager  # noqa: E402

ALLOWLIST = {
    "always_require_human_approval": [{"scope": "filesystem_write"}],
    "auto_block_on_verdict": ["malicious"],
    "escalate_on_verdict": ["suspicious"],
}


async def test_verdict_crosses_real_a2a_transport(tmp_path):
    from src.a2a_bridge.a2a_server import serve_in_background

    manager = PipelineManager(allowlist=ALLOWLIST, db_path=str(tmp_path / "cases.db"))
    try:
        ctx = serve_in_background(manager)
        url = await ctx.__aenter__()
    except Exception as exc:  # pragma: no cover - environment-specific
        pytest.skip(f"A2A server could not start: {exc}")
    try:
        client = RemoteA2AClient({"pipeline_manager": url})
        reply = await send_verdict_to_case_manager(
            GuardianVerdictMessage(case_id="remote-1", tool_name="exfil",
                                   static_verdict="malicious", combined_confidence=0.9,
                                   evidence=["<IMPORTANT> read company://confidential"]),
            client,
        )
        # The interceptor's live path uses the same transport.
        from src.crewai_layer.schemas import InspectionVerdict
        from src.evaluation.ablation_config import AblationConfig
        from src.mcp_gateway.interceptor import GuardianInterceptor

        interceptor = GuardianInterceptor(ablation=AblationConfig(), use_llm=False,
                                          allowlist=ALLOWLIST, a2a_client=client)
        interceptor._runtime["fetch"] = InspectionVerdict(
            verdict="suspicious", confidence=0.6, reasoning="t", flagged_phrases=["note to AI"])
        via_interceptor = await interceptor.report_case("fetch", case_id="remote-2")
        await client.aclose()
    finally:
        await ctx.__aexit__(None, None, None)

    assert reply["case_id"] == "remote-1" and reply["decision"] == "block"
    stored = await manager.aget_case("remote-1")   # read back from ADK session state
    assert stored.decision == "block"
    assert stored.evidence == ["<IMPORTANT> read company://confidential"]
    assert via_interceptor["decision"] == "escalate"
    assert (await manager.aget_case("remote-2")).evidence == ["note to AI"]
