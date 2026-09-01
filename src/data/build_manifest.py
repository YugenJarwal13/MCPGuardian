"""Phase 1.7 — dataset manifest.

Runs every loader once and dumps a composition summary to ``data_manifest.json``
so the whole team can see counts per source and per attack category at a glance.
"""
from __future__ import annotations

import asyncio
import json
from collections import Counter

from src.config import REPO_ROOT
from src.data.datasets import load_by_source


async def build_manifest() -> dict:
    by_source = await load_by_source()
    by_category: Counter[str] = Counter()
    for cases in by_source.values():
        for c in cases:
            by_category[c.attack_category or "clean"] += 1

    manifest = {
        "dvmcp_count": len(by_source["dvmcp"]),
        "mcptox_count": len(by_source["mcptox"]),
        "benign_count": len(by_source["benign"]),
        "custom_count": len(by_source["custom"]),
        "total": sum(len(v) for v in by_source.values()),
        "by_category": dict(sorted(by_category.items())),
    }
    out = REPO_ROOT / "data_manifest.json"
    out.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


if __name__ == "__main__":
    m = asyncio.run(build_manifest())
    print(json.dumps(m, indent=2))
