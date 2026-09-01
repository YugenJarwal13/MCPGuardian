"""Phase 5.1 — SQLite-backed persistent fingerprint store.

One row per ``tool_id`` holding its ToolFingerprint as serialized JSON.
Persistent across process restarts so drift is measured across the whole project
lifetime, not just one session (this persistence is the ADK "stateful" piece the
Monitoring/Observability module asks for).
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from src.adk_layer.state.session_schema import ToolFingerprint


class ToolFingerprintStore:
    def __init__(self, db_path: str | Path = "logs/fingerprints.db"):
        if db_path not in (":memory:",):
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path))
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS fingerprints (tool_id TEXT PRIMARY KEY, data TEXT)"
        )
        self._conn.commit()

    def get(self, tool_id: str) -> ToolFingerprint:
        row = self._conn.execute(
            "SELECT data FROM fingerprints WHERE tool_id=?", (tool_id,)
        ).fetchone()
        if row:
            return ToolFingerprint(**json.loads(row[0]))
        return ToolFingerprint(tool_id=tool_id)

    def update(self, fingerprint: ToolFingerprint) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO fingerprints VALUES (?, ?)",
            (fingerprint.tool_id, fingerprint.model_dump_json()),
        )
        self._conn.commit()

    def all_ids(self) -> list[str]:
        return [r[0] for r in self._conn.execute("SELECT tool_id FROM fingerprints").fetchall()]

    def close(self) -> None:
        self._conn.close()
