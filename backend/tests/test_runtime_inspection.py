"""Phase 4.4 — runtime-inspection behaviour tests (deterministic path).

The critical pair: it must FLAG response-path attacks (DVMCP 5 & 6) while NOT
flagging benign data that merely contains instruction-adjacent words.
"""
from __future__ import annotations

from src.crewai_layer.crew import run_runtime_inspection
from src.data.dvmcp_loader import load_dvmcp_cases


async def _dvmcp():
    return await load_dvmcp_cases(prefer_live=False)


async def test_flags_indirect_prompt_injection_challenge():
    cases = await _dvmcp()
    case = next(c for c in cases if c.attack_category == "indirect_prompt_injection")
    verdict = run_runtime_inspection(case.tool_name, case.sample_response, use_llm=False)
    assert verdict.verdict in ("suspicious", "malicious")


async def test_flags_tool_shadowing_challenge():
    cases = await _dvmcp()
    case = next(c for c in cases if c.attack_category == "tool_shadowing")
    verdict = run_runtime_inspection(case.tool_name, case.sample_response, use_llm=False)
    assert verdict.verdict in ("suspicious", "malicious")


async def test_flags_rug_pull_response_directive():
    cases = await _dvmcp()
    case = next(c for c in cases if c.attack_category == "rug_pull")
    verdict = run_runtime_inspection(case.tool_name, case.sample_response, use_llm=False)
    assert verdict.verdict in ("suspicious", "malicious")


def test_does_not_flag_benign_response_mentioning_trigger_words():
    # instruction-adjacent word "ignore" in an ordinary, non-directive sentence.
    verdict = run_runtime_inspection(
        "changelog_tool", "Please ignore v1, use v2 of this API.", use_llm=False
    )
    assert verdict.verdict == "clean"


def test_does_not_flag_article_about_prompt_injection():
    verdict = run_runtime_inspection(
        "web_search",
        "This article explains how attackers try to make AI assistants ignore their instructions.",
        use_llm=False,
    )
    assert verdict.verdict == "clean"
