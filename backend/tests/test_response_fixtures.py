"""The hand-written response benchmark is well-formed and original."""
from __future__ import annotations

import json
import re
from collections import Counter

from src.data.custom_fixtures.generate_fixtures import FIXTURES_PATH, load_custom_cases
from src.data.custom_fixtures.response_cases import build


def test_fixtures_json_is_in_sync_with_source():
    assert json.loads(FIXTURES_PATH.read_text(encoding="utf-8")) == build()


def test_shape_and_balance():
    cases = load_custom_cases()
    assert 30 <= len(cases) <= 50
    assert len({c.case_id for c in cases}) == len(cases)
    assert all(c.source == "custom" and c.sample_response for c in cases)
    groups = Counter(c.case_id.split("-")[2] for c in cases)
    assert groups["atk"] >= 20 and groups["ben"] >= 5 and groups["hn"] >= 10   # hard negatives present
    assert all((c.ground_truth_label == "malicious") == (c.case_id.split("-")[2] == "atk") for c in cases)
    assert all(c.attack_category for c in cases if c.ground_truth_label == "malicious")
    assert len({c.attack_category for c in cases if c.attack_category}) >= 6      # several attack classes


def test_tool_descriptions_are_plain_so_only_the_response_carries_the_attack():
    from src.crewai_layer.heuristics import static_heuristic

    for c in load_custom_cases():
        assert static_heuristic(c.tool_name, c.tool_description, c.tool_schema).verdict == "clean", c.case_id


def test_not_copied_from_upstream_exploit_text():
    """Written in our own words: none of the upstream exploit phrasings appear."""
    blob = " ".join(c.sample_response for c in load_custom_cases() if c.ground_truth_label == "malicious").lower()
    for banned in ("ignore all previous instructions", "system://api_keys", "system://admin",
                   "company://confidential", "<important>", "<hidden>"):
        assert banned not in blob
    assert not re.search(r"you are now a helpful assistant that will help me", blob)
