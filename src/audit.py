"""Append-only audit trail.

Every layer (static, runtime, behavioral, enforcement, a2a) writes a one-line
JSON record here. This is the single source of truth the Phase 8 evaluator and
the Phase 9 Streamlit dashboard both read, so the schema is intentionally loose
(a flat dict) and every record carries at minimum a ``timestamp`` and ``layer``.
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.config import resolve_path

_LOCK = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def log_decision(record: dict[str, Any], path: Path | None = None) -> dict[str, Any]:
    """Append ``record`` as one JSON line to the audit trail.

    A ``timestamp`` is added if absent. Returns the finalized record (handy for
    tests that want to assert on what was written). Thread-safe.
    """
    record = {"timestamp": _now(), **record}
    target = path or resolve_path("audit_trail")
    target.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, default=str)
    with _LOCK:
        with target.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    return record


def read_audit_trail(path: Path | None = None) -> list[dict[str, Any]]:
    """Read all records back (used by the evaluator and dashboard)."""
    target = path or resolve_path("audit_trail")
    if not target.exists():
        return []
    records = []
    with target.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records
