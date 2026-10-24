"""Input guard: validates what a *user* hands to the gateway before it reaches the pipeline.

Scope, stated plainly: this app has no chat box. The user-controlled inputs are the JSON arguments of
the tool call being tested and the MCP server URL. The guard therefore checks those: size and shape
limits, control/zero-width characters, instruction-injection phrasing (the same patterns the static
detector uses) and plainly abusive language. It is deterministic (no model call) and is separate from
the Guardian pipeline, which inspects what *servers* send. It has not been evaluated on any benchmark.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from src.crewai_layer.heuristics import _CONTROL_CHARS, _DIRECTIVE_PATTERNS, _ZERO_WIDTH

MAX_ARGS_BYTES = 8 * 1024
MAX_DEPTH = 6
MAX_STRING = 4000
MAX_URL = 2048

_ABUSE = re.compile(
    r"\b(kill yourself|go die|i will (kill|hurt|find) you|fuck(ing)? (you|off)|you (stupid|worthless) (idiot|bot|piece))\b|"
    r"\b(asshole|bastard|bitch|cunt|motherfucker)\b", re.I)


@dataclass(frozen=True)
class GuardResult:
    ok: bool
    category: str = "ok"          # ok | size | shape | control_chars | injection | abuse | url
    reason: str = ""


OK = GuardResult(True)


def _walk(value: Any, depth: int = 0):
    if depth > MAX_DEPTH:
        raise ValueError("nested too deeply")
    if isinstance(value, dict):
        for k, v in value.items():
            yield str(k)
            yield from _walk(v, depth + 1)
    elif isinstance(value, (list, tuple)):
        for v in value:
            yield from _walk(v, depth + 1)
    elif isinstance(value, str):
        yield value


def check_text(text: str) -> GuardResult:
    if len(text) > MAX_STRING:
        return GuardResult(False, "size", f"a value is longer than {MAX_STRING} characters")
    if _CONTROL_CHARS.search(text) or _ZERO_WIDTH.search(text):
        return GuardResult(False, "control_chars", "contains control or zero-width characters")
    for label, pat in _DIRECTIVE_PATTERNS:
        if pat.search(text):
            return GuardResult(False, "injection", f"looks like an instruction aimed at the AI ({label.replace('_', ' ')})")
    if _ABUSE.search(text):
        return GuardResult(False, "abuse", "contains abusive language")
    return OK


def check_arguments(args: Any) -> GuardResult:
    """Validate the JSON arguments of a tool call. ``None`` / ``{}`` are fine."""
    if args in (None, {}):
        return OK
    if not isinstance(args, dict):
        return GuardResult(False, "shape", "arguments must be a JSON object")
    try:
        if len(json.dumps(args).encode("utf-8")) > MAX_ARGS_BYTES:
            return GuardResult(False, "size", f"arguments are larger than {MAX_ARGS_BYTES // 1024} KB")
        for text in _walk(args):
            res = check_text(text)
            if not res.ok:
                return res
    except (TypeError, ValueError) as exc:
        return GuardResult(False, "shape", f"arguments are not plain JSON ({exc})")
    return OK


def check_url(url: str) -> GuardResult:
    if not isinstance(url, str) or len(url) > MAX_URL:
        return GuardResult(False, "url", "the address is missing or too long")
    if _CONTROL_CHARS.search(url) or _ZERO_WIDTH.search(url) or any(c.isspace() for c in url.strip()):
        return GuardResult(False, "url", "the address contains spaces or control characters")
    return OK
