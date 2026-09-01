"""Phase 1.6 — custom fixtures (BACKUP ONLY).

Defer writing real content here until Phase 3/4 evaluation reveals a specific
attack shape neither DVMCP nor MCPTox covers well (e.g. a poisoning style tailored
to the Phase 10 demo agent's exact tool names). Until then this emits an empty
list and ``fixtures.json`` stays an empty array — the loader path exists so
downstream code never has to special-case its absence.
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
    """Placeholder generator. Fill in only when a real coverage gap appears."""
    fixtures: list[dict] = []
    FIXTURES_PATH.write_text(json.dumps(fixtures, indent=2), encoding="utf-8")
    print(f"Wrote {len(fixtures)} custom fixtures to {FIXTURES_PATH}")


if __name__ == "__main__":
    generate()
