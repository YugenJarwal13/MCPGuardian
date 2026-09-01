"""Phase 3.5 — static-analysis behaviour tests (deterministic path)."""
from __future__ import annotations

from src.crewai_layer.crew import run_static_analysis
from src.crewai_layer.heuristics import static_heuristic
from src.data.benign_control_set import load_benign_cases
from src.data.dvmcp_loader import load_dvmcp_cases

BENIGN = load_benign_cases()


async def _dvmcp():
    return await load_dvmcp_cases(prefer_live=False)


async def test_flags_dvmcp_tool_poisoning_challenge():
    cases = await _dvmcp()
    case = next(c for c in cases if c.attack_category == "tool_poisoning")
    verdict = run_static_analysis(case.tool_name, case.tool_description, case.tool_schema, use_llm=False)
    assert verdict.verdict in ("suspicious", "malicious")
    assert verdict.flagged_phrases


async def test_flags_prompt_injection_challenge():
    cases = await _dvmcp()
    case = next(c for c in cases if c.attack_category == "prompt_injection")
    verdict = run_static_analysis(case.tool_name, case.tool_description, case.tool_schema, use_llm=False)
    assert verdict.verdict == "malicious"


async def test_flags_excessive_scope_challenge():
    cases = await _dvmcp()
    case = next(c for c in cases if c.attack_category == "excessive_permission_scope")
    verdict = run_static_analysis(case.tool_name, case.tool_description, case.tool_schema, use_llm=False)
    assert verdict.verdict in ("suspicious", "malicious")


def test_does_not_flag_benign_calculator():
    case = next(c for c in BENIGN if c.tool_name == "calculator")
    verdict = run_static_analysis(case.tool_name, case.tool_description, case.tool_schema, use_llm=False)
    assert verdict.verdict == "clean"


def test_does_not_flag_any_benign_metadata():
    # None of the benign control tools' METADATA should be flagged (their tricky
    # instruction-adjacent words live in sample_response, tested in Phase 4).
    for case in BENIGN:
        verdict = static_heuristic(case.tool_name, case.tool_description, case.tool_schema)
        assert verdict.verdict == "clean", f"false positive on {case.tool_name}: {verdict.flagged_phrases}"
