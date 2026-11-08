"""Credential scan for tool RESPONSES.

The runtime inspector looks for instructions hidden in a reply. A reply that simply *contains* a secret (an API
key, a signed token, a private key) has no instruction in it, so a data leak of that kind passes the language
model as "ordinary data". This deterministic scan closes that gap: a reply carrying credential-like values is
raised to ``suspicious`` (a human decides) and the values are shown only in redacted form.

Deliberately conservative patterns: well-known token formats, plus ``name: value`` pairs where the name says it is a
secret and the value looks like one. It is a safety net, not a data-loss-prevention product.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_RULES: list[tuple[str, re.Pattern]] = [
    ("JSON web token", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")),
    ("private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("AWS access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b")),
    ("Slack token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b")),
    ("API key (sk- style)", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("bearer token", re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{20,}")),
    ("secret value", re.compile(
        r"(?i)\b(api[_ -]?key|access[_ -]?token|auth[_ -]?token|refresh[_ -]?token|client[_ -]?secret|secret[_ -]?key|"
        r"password|passwd)\b[\"']?\s*[:=]\s*[\"']?([A-Za-z0-9_\-./+=]{8,})")),
]


@dataclass(frozen=True)
class Finding:
    kind: str
    redacted: str


def _redact(value: str) -> str:
    return f"{value[:4]}…{value[-2:]} ({len(value)} chars)" if len(value) > 10 else "…"


def scan(text: str) -> list[Finding]:
    """Credential-like values in ``text``, redacted. Empty when none."""
    found: list[Finding] = []
    seen: set[str] = set()
    for kind, pat in _RULES:
        for m in pat.finditer(text or ""):
            value = m.group(2) if kind == "secret value" else m.group(0)
            if value in seen or value.lower() in ("password", "example", "changeme", "redacted"):
                continue
            seen.add(value)
            found.append(Finding(kind, _redact(value)))
    return found


def redact_text(text: str) -> str:
    """``text`` with every credential-like value replaced, for anything shown or logged."""
    out = text or ""
    for kind, pat in _RULES:
        if kind == "secret value":
            out = pat.sub(lambda m: m.group(0).replace(m.group(2), _redact(m.group(2))), out)
        else:
            out = pat.sub(lambda m: f"[{kind} {_redact(m.group(0))}]", out)
    return out
