"""Phase 9 — Streamlit audit-trail dashboard.

Makes the Monitoring/Observability story concrete and clickable: filter down to
``malicious``, show the class was actually caught, click into one row and read the
agent's own ``reasoning`` out loud. Also renders the Phase 5 fingerprint-drift
chart inline (not just as a standalone PNG).

Run:  streamlit run src/dashboard/app.py
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

# Resolve the audit trail relative to the repo root (two levels up from here).
REPO_ROOT = Path(__file__).resolve().parents[2]
AUDIT_PATH = REPO_ROOT / "logs" / "audit_trail.jsonl"

DISPLAY_COLS = ["timestamp", "case_id", "source", "layer", "tool_name", "verdict",
                "decision", "confidence", "anomalous", "reasoning"]


@st.cache_data(ttl=5)
def load_records() -> pd.DataFrame:
    if not AUDIT_PATH.exists():
        return pd.DataFrame()
    records = []
    with AUDIT_PATH.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    df = pd.DataFrame(records)
    for col in DISPLAY_COLS:
        if col not in df.columns:
            df[col] = None
    return df


def main() -> None:
    st.set_page_config(page_title="MCP Guardian — Audit Trail", layout="wide")
    st.title("🛡️ MCP Guardian — Audit Trail")

    df = load_records()
    if df.empty:
        st.warning(
            f"No audit records yet at `{AUDIT_PATH}`. Generate some with:\n\n"
            "`python -m src.crewai_layer.batch_static` or `python -m src.evaluation.run_eval`"
        )
        return

    # Sidebar filters.
    st.sidebar.header("Filters")
    layers = sorted(x for x in df["layer"].dropna().unique())
    layer_filter = st.sidebar.multiselect("Layer", options=layers, default=layers)

    verdicts = sorted(x for x in df["verdict"].dropna().unique())
    verdict_filter = st.sidebar.multiselect("Verdict", options=verdicts, default=verdicts)

    sources = sorted(x for x in df["source"].dropna().unique())
    source_filter = st.sidebar.multiselect("Source", options=sources, default=sources)

    mask = df["layer"].isin(layer_filter)
    if verdicts:
        mask &= df["verdict"].isin(verdict_filter) | df["verdict"].isna()
    if sources:
        mask &= df["source"].isin(source_filter) | df["source"].isna()
    filtered = df[mask]

    st.subheader(f"Showing {len(filtered)} of {len(df)} decisions")
    st.dataframe(filtered[DISPLAY_COLS], use_container_width=True, height=380)

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Verdict breakdown")
        vc = filtered["verdict"].dropna().value_counts()
        if not vc.empty:
            st.bar_chart(vc)
        else:
            st.caption("No verdict-bearing rows in the current filter.")
    with col2:
        st.subheader("Decisions by layer")
        lc = filtered["layer"].dropna().value_counts()
        if not lc.empty:
            st.bar_chart(lc)

    # Click-into detail.
    st.subheader("Inspect a single decision")
    if not filtered.empty:
        idx = st.selectbox("Row", options=list(filtered.index),
                           format_func=lambda i: f"{filtered.loc[i, 'layer']} · "
                                                 f"{filtered.loc[i, 'tool_name']} · "
                                                 f"{filtered.loc[i, 'verdict'] or filtered.loc[i, 'decision']}")
        st.json(json.loads(filtered.loc[idx].to_json()))

    # Fingerprint-drift chart, rendered inline (Phase 5 reuse).
    st.subheader("Fingerprint drift (rug-pull demo tool)")
    try:
        from src.evaluation.drift_chart import compute_drift_series

        s = compute_drift_series()
        drift_df = pd.DataFrame(
            {"mean_length": s["mean_length"], "z_score": s["z_score"]}, index=s["calls"]
        )
        drift_df.index.name = "call #"
        st.line_chart(drift_df)
        st.caption("Flat line for 10 calls, then a spike at call 11 — the rug pull.")
    except Exception as exc:  # pragma: no cover - dashboard convenience only
        st.caption(f"Drift chart unavailable: {exc}")


if __name__ == "__main__":
    main()
