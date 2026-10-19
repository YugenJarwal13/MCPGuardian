"""Test-suite safety net: with a real OpenRouter key in ``.env``, any test that
leaves ``use_llm=None`` would auto-detect an LLM and spend quota (and be slow and
nondeterministic). Auto-detection is therefore forced off for tests; tests that
want the LLM path pass ``use_llm=True`` together with a fake transport/chain."""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _no_ambient_llm(monkeypatch):
    from src.crewai_layer import crew

    monkeypatch.setattr(crew, "llm_available", lambda: False)
    monkeypatch.setenv("LLM_CACHE", "off")
