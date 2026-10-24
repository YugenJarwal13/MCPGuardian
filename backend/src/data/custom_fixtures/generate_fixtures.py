"""Custom fixtures: the hand-written tool-RESPONSE benchmark.

``fixtures.json`` is generated from ``response_cases.py`` (50 cases: injected
responses, plain benign data and hard negatives). The loader path is unchanged so
downstream code never special-cases it.
"""
from __future__ import annotations

import json
from pathlib import Path

from src.data.schemas import ToolTestCase

FIXTURES_PATH = Path(__file__).with_name("fixtures.json")


def load_custom_cases() -> list[ToolTestCase]:
    if not FIXTURES_PATH.exists():
        return []
    raw = json.loads(FIXTURES_PATH.read_text(encoding="utf-8"))
    return [ToolTestCase(**r) for r in raw]


def generate() -> None:
    from src.data.custom_fixtures.response_cases import generate as _generate

    _generate()


if __name__ == "__main__":
    generate()
