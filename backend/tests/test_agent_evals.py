"""The evaluation suite's own arithmetic: trajectory scoring, the policy oracle, evidence grounding, the budget cap."""
from __future__ import annotations

import pytest

from src.evaluation import agent_evals as ae


def test_trajectory_scores_follow_the_adk_criteria():
    exp = ["a", "b", "c"]
    assert ae.trajectory_scores(exp, ["a", "b", "c"]) == {"exact": True, "in_order": True, "any_order": True, "precision": 1.0, "recall": 1.0}
    extra = ae.trajectory_scores(exp, ["a", "x", "b", "c"])
    assert not extra["exact"] and extra["in_order"] and extra["any_order"] and extra["precision"] == 0.75 and extra["recall"] == 1.0
    swapped = ae.trajectory_scores(exp, ["b", "a", "c"])
    assert not swapped["in_order"] and swapped["any_order"]
    missing = ae.trajectory_scores(exp, ["a", "c"])
    assert not missing["any_order"] and missing["recall"] == pytest.approx(0.667, abs=1e-3)


def test_skipped_stages_do_not_count_as_run():
    ev = [{"stage": "connect", "message": "ok"}, {"stage": "runtime_check", "message": "Skipped - the call never executed."},
          {"stage": "done", "message": "BLOCK"}]
    assert ae._stages(ev) == ["connect", "done"]


def test_the_policy_oracle_matches_the_written_rules():
    assert ae.oracle("malicious", None, False, "code_execution") == "block"        # block beats a sensitive scope
    assert ae.oracle("clean", "clean", False, "filesystem_write") == "escalate"    # a sensitive scope always needs a human
    assert ae.oracle("suspicious", None, False, None) == "escalate"
    assert ae.oracle("clean", "clean", True, None) == "escalate"
    assert ae.oracle(None, None, False, None) == "allow"


def test_the_policy_and_the_statistics_evaluations_run_without_a_model():
    assert ae.eval_policy()["disagreements"] == 0
    stats = ae.eval_behaviour_stats()
    assert stats["series_with_a_false_alarm"] == 0 and stats["changes"]["new_key"]["detection_rate_pct"] == 100.0
    assert stats["changes"]["same_length_different_content"]["detected"] == 0          # the known blind spot


def test_the_budget_counts_requests_and_the_helpers_are_safe_on_empty_input():
    b = ae.Budget(3)
    b.used, b.judge = 2, 1
    assert b.left() == 0 and b.total == 3
    assert ae.wilson(0, 0) is None and ae.pct(1, 4) == 25.0 and ae.pct(0, 0) is None


def test_the_report_renders_from_partial_results():
    text = ae.render_report({"policy": {"combinations": 160, "disagreements": 0},
                             "a2a": {"messages": 4, "fidelity": 1.0, "decision_matches_policy": 1.0, "round_trip_ms_p50": 1,
                                     "round_trip_ms_p95": 2, "round_trip_ms_max": 3, "finding_fixed": "x"}})
    assert "Policy conformance" in text and "Not evaluated, and why" in text
