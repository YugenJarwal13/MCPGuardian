"""Convenience aggregator over all four data sources.

Downstream code (static-analysis batch, evaluation, dashboard) imports from here
so it never needs to know which loaders exist or which are async.
"""
from __future__ import annotations

from src.data.benign_control_set import load_benign_cases
from src.data.custom_fixtures.generate_fixtures import load_custom_cases
from src.data.dvmcp_loader import load_dvmcp_cases
from src.data.mcptox_loader import load_mcptox_cases
from src.data.schemas import ToolTestCase


async def load_all_cases(prefer_live: bool = True) -> list[ToolTestCase]:
    """DVMCP (async) + MCPTox + benign + custom, concatenated."""
    dvmcp = await load_dvmcp_cases(prefer_live=prefer_live)
    return dvmcp + load_mcptox_cases() + load_benign_cases() + load_custom_cases()


async def load_by_source(prefer_live: bool = True) -> dict[str, list[ToolTestCase]]:
    return {
        "dvmcp": await load_dvmcp_cases(prefer_live=prefer_live),
        "mcptox": load_mcptox_cases(),
        "benign": load_benign_cases(),
        "custom": load_custom_cases(),
    }
