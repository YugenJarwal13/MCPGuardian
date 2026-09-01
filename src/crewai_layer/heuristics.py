"""Deterministic detectors used by the CrewAI layer.

These serve two purposes:
  1. A fast, zero-cost pre-filter in front of the (expensive, LLM-backed) agents.
  2. A fully-offline FALLBACK so the whole pipeline — and its tests — run without
     any LLM credentials. When ``LLM_PROVIDER`` credentials are present, the
     CrewAI agents in ``crew.py`` are the primary path and these become the
     pre-filter; when they are absent, these produce the verdict directly.

The heuristics are intentionally conservative about false positives: an
instruction-adjacent WORD in ordinary data is not enough — a signal must look
like a directive aimed at the agent, an encoding trick, or a purpose/scope
mismatch before it moves the verdict off ``clean``.
"""
from __future__ import annotations

import re

from src.crewai_layer.schemas import InspectionVerdict

# --- 1. Instruction-like language directed at the calling agent ---------------
_DIRECTIVE_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("ignore_prior_instructions", re.compile(r"ignore\s+(all\s+)?(the\s+)?(previous|prior|above|earlier)\s+(instructions|rules|prompt)", re.I)),
    ("system_override", re.compile(r"system\s*(override|prompt)|\bSYSTEM\s*:", re.I)),
    ("reveal_system_prompt", re.compile(r"(reveal|print|show|expose)\s+(your\s+)?(system\s+prompt|instructions)", re.I)),
    ("addressed_to_ai", re.compile(r"(note\s+to|attention)\s+(the\s+)?(ai|assistant)|to\s+the\s+ai\s+assistant|\[assistant\]|\bassistant\s*:", re.I)),
    ("hide_from_user", re.compile(r"(do\s*n['o]t|without)\s+(tell|telling|inform|informing|notify)\s+(the\s+)?user", re.I)),
    ("imperative_before_answer", re.compile(r"before\s+(you\s+)?(respond|answer|replying)", re.I)),
    ("html_comment_injection", re.compile(r"<!--.*?-->", re.I | re.S)),
    ("exfiltration_directive", re.compile(r"(read|open|cat|include|forward|send|upload|exfiltrate).{0,40}(~/\.ssh|id_rsa|\.aws/credentials|credentials|password|access_token|secret)", re.I)),
    ("forward_all", re.compile(r"forward\s+(all|every)\s+(future\s+)?(responses?|results?|messages?)", re.I)),
]

# --- 2. Encoding / formatting anomalies ---------------------------------------
_ZERO_WIDTH = re.compile(r"[​‌‍⁠﻿]")
_BASE64_BLOB = re.compile(r"(?<![A-Za-z0-9+/])[A-Za-z0-9+/]{40,}={0,2}(?![A-Za-z0-9+/])")
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")

# --- 3. Scope-mismatch inference ----------------------------------------------
_BENIGN_PURPOSE = re.compile(r"\b(weather|calculator|calculate|add|sum|echo|greet|note|search|list\s+files|changelog|translate|time|date)\b", re.I)
# Read-only intent words: a tool that describes itself this way should not need
# write/delete/exec/egress capability — if it requests one, that is excessive scope.
_READONLY_INTENT = re.compile(r"\b(read|reads|reading|get|gets|fetch|fetches|view|views|list|lists|show|shows|lookup|retrieve|retrieves|public)\b", re.I)
_WRITE_CAPABILITY = re.compile(r"\b(write|writes|overwrite|delete|deletes|modify|rw)\b|['\"]w['\"]|['\"]rw['\"]|read\+?write|read/write", re.I)
_SENSITIVE_SCOPE_HINTS = {
    "filesystem_write": re.compile(r"\b(write|delete|overwrite|filesystem|absolute\s+path|/etc/|rm\s+-)\b|['\"]w['\"]|['\"]rw['\"]", re.I),
    "network_egress": re.compile(r"https?://|\b(upload|egress|post\s+to|send\s+to|endpoint)\b", re.I),
    "credential_access": re.compile(r"\b(access_token|api[_\s]?key|password|secret|credential|id_rsa)\b", re.I),
    "code_execution": re.compile(r"\b(eval\(|exec\(|subprocess|shell\s*=\s*true|run_command|os\.system)\b", re.I),
}


def _scan_directives(text: str) -> list[str]:
    hits = []
    for label, pat in _DIRECTIVE_PATTERNS:
        m = pat.search(text)
        if m:
            snippet = m.group(0).strip()
            hits.append(snippet[:120])
    return hits


def _scan_encoding(text: str) -> list[str]:
    hits = []
    if _ZERO_WIDTH.search(text):
        hits.append("zero-width/invisible characters")
    if _CONTROL_CHARS.search(text):
        hits.append("control characters in text")
    blob = _BASE64_BLOB.search(text)
    if blob:
        hits.append(f"base64-like blob: {blob.group(0)[:24]}...")
    return hits


def _scan_scope_mismatch(text: str, description: str) -> list[str]:
    hits: list[str] = []
    sensitive = [scope for scope, pat in _SENSITIVE_SCOPE_HINTS.items() if pat.search(text)]

    # (a) A tool with an explicitly benign purpose requesting any sensitive scope.
    if _BENIGN_PURPOSE.search(text) and sensitive:
        hits.append(f"stated benign purpose but requests {', '.join(sorted(sensitive))}")

    # (b) Excessive scope: a read-only-sounding tool that also requests write/delete
    #     capability (the DVMCP "excessive permission scope" pattern).
    if _READONLY_INTENT.search(description) and _WRITE_CAPABILITY.search(text):
        hits.append("read-only stated purpose but requests write/modify capability")

    return hits


def static_heuristic(tool_name: str, tool_description: str, tool_schema: dict) -> InspectionVerdict:
    """Deterministic static analysis over a tool's metadata."""
    blob = f"{tool_name}\n{tool_description}\n{tool_schema}"

    directives = _scan_directives(blob)
    encoding = _scan_encoding(blob)
    mismatch = _scan_scope_mismatch(blob, tool_description)

    # A tool that ADVERTISES arbitrary code execution (eval/exec/shell=True/
    # run_command) in its own metadata is a static red flag regardless of its
    # stated purpose — legitimate tools do not describe themselves this way.
    dangerous_capability: list[str] = []
    if _SENSITIVE_SCOPE_HINTS["code_execution"].search(blob):
        dangerous_capability.append("advertises arbitrary code execution in metadata")

    flagged = directives + encoding + mismatch + dangerous_capability

    # Directive intent or exfiltration/credential references => malicious.
    if directives:
        return InspectionVerdict(
            verdict="malicious",
            confidence=0.9,
            reasoning=(
                "Tool metadata contains directive language aimed at the calling agent "
                f"({len(directives)} signal(s)), which is the signature of tool poisoning."
            ),
            flagged_phrases=flagged,
        )
    # Encoding tricks are strong but slightly less certain on their own.
    if encoding:
        return InspectionVerdict(
            verdict="suspicious",
            confidence=0.7,
            reasoning="Encoding/formatting anomaly that a human reviewer might miss.",
            flagged_phrases=flagged,
        )
    # Purpose/scope mismatch or advertised code execution => suspicious.
    if mismatch or dangerous_capability:
        return InspectionVerdict(
            verdict="suspicious",
            confidence=0.6,
            reasoning=(
                "Scope/purpose mismatch or dangerous capability advertised in metadata: "
                + "; ".join(flagged)
            ),
            flagged_phrases=flagged,
        )
    return InspectionVerdict(
        verdict="clean",
        confidence=0.8,
        reasoning="No embedded instructions, encoding anomalies, or scope mismatch found.",
        flagged_phrases=[],
    )
