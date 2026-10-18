"""The LLM fallback chain behind the CrewAI inspection agents.

``.env`` describes an ordered chain, e.g.

    LLM_PROVIDER=openrouter
    LLM_MODEL=<primary slug>
    OPENROUTER_FALLBACK_MODELS=<slug>,<slug>
    LLM_STRUCTURED_METHODS=response_format,tool_call,json_parse      # one per model, primary first
    LLM_FALLBACK_PROVIDER=ollama / LLM_FALLBACK_MODEL=qwen3:4b        # final local fallback

Each model has its own structured-output method because free OpenRouter models
differ in what they support:

    response_format  OpenAI-style ``response_format: json_schema``
    tool_call        force a single function call whose arguments are the verdict
    json_parse       ask for JSON in plain text and extract it
    ollama_format    Ollama's native ``format`` JSON-schema constraint

``ChainLLM.complete(system, user)`` walks the chain: a slot that fails
*permanently* (HTTP 403/404/400) is disabled for the process; a daily-quota 429
disables the account-wide free tier until its reset; transient errors and
unparseable output are retried once and then fall through to the next slot.
Every answer carries ``meta`` (provider, model, method, latency, attempts, tokens,
slots tried) so each verdict records which model actually produced it.

Ephemeral shell overrides win over ``.env`` (``LLM_PROVIDER=ollama python -m ...``
forces the local model without editing any file).

Placeholder values such as ``<dots3-note-preview-free-id>`` in ``.env`` are mapped
to the verified OpenRouter slugs below (verified against GET /api/v1/models on
2026-10-18) instead of being sent to the API.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from src.config import REPO_ROOT, settings

log = logging.getLogger(__name__)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# Verified slugs for the placeholder names that appear in .env.
_PLACEHOLDER_SLUGS = {
    "dots": "dots-studio/dots-3-note-preview:free",
    "nemotron": "nvidia/nemotron-3.5-lightning:free",
    "inkling": "thinkingmachines/inkling-small:free",
}

VERDICT_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["clean", "suspicious", "malicious"]},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "reasoning": {"type": "string"},
        "flagged_phrases": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["verdict", "confidence", "reasoning", "flagged_phrases"],
    "additionalProperties": False,
}

METHODS = ("response_format", "tool_call", "json_parse", "ollama_format")


class ChainError(RuntimeError):
    """No slot could produce a valid verdict. (Message avoids rate-limit wording so
    CrewAI's own transient-retry wrapper does not re-run the whole chain.)"""


@dataclass
class Slot:
    provider: str            # "openrouter" | "ollama"
    model: str
    method: str
    disabled_reason: Optional[str] = None
    disabled_until: float = 0.0          # monotonic; 0 = not temporarily disabled

    @property
    def label(self) -> str:
        return f"{self.provider}:{self.model}"

    def usable(self) -> bool:
        if self.disabled_reason:
            return False
        return time.monotonic() >= self.disabled_until


def _is_placeholder(value: Optional[str]) -> bool:
    return not value or (value.strip().startswith("<") and value.strip().endswith(">"))


def _resolve_slug(value: str) -> str:
    if not _is_placeholder(value):
        return value.strip()
    low = value.lower()
    for key, slug in _PLACEHOLDER_SLUGS.items():
        if key in low:
            return slug
    raise ValueError(f"Unresolvable model placeholder in .env: {value!r}")


def _split_csv(value: Optional[str]) -> list[str]:
    return [v.strip() for v in (value or "").split(",") if v.strip()]


def build_slots(include_local_fallback: bool = True) -> list[Slot]:
    settings()  # loads .env into os.environ without overriding the shell
    provider = (os.environ.get("LLM_PROVIDER") or "openrouter").lower()
    slots: list[Slot] = []
    if provider == "openrouter":
        models = [os.environ.get("LLM_MODEL", "")] + _split_csv(os.environ.get("OPENROUTER_FALLBACK_MODELS"))
        methods = _split_csv(os.environ.get("LLM_STRUCTURED_METHODS")) or ["response_format"]
        for i, m in enumerate(models):
            if _is_placeholder(m) and not m:
                continue
            method = methods[i] if i < len(methods) else methods[-1]
            if method not in METHODS:
                raise ValueError(f"unknown structured method {method!r} (expected {METHODS})")
            slots.append(Slot("openrouter", _resolve_slug(m), method))
    elif provider == "ollama":
        slots.append(Slot("ollama", _local_model(), "ollama_format"))
        return slots           # an explicit local run never silently leaves Ollama
    else:
        raise ValueError(f"provider {provider!r} is not handled by the chain")
    fb = (os.environ.get("LLM_FALLBACK_PROVIDER") or "").lower()
    if include_local_fallback and fb == "ollama":
        slots.append(Slot("ollama", _local_model(), "ollama_format"))
    return slots


def _local_model() -> str:
    # An explicit LLM_MODEL only counts for Ollama when the shell chose Ollama.
    if (os.environ.get("LLM_PROVIDER") or "").lower() == "ollama" and os.environ.get("LLM_MODEL") \
            and not _is_placeholder(os.environ.get("LLM_MODEL")) and ":" in os.environ["LLM_MODEL"] \
            and "/" not in os.environ["LLM_MODEL"]:
        return os.environ["LLM_MODEL"]
    return os.environ.get("LLM_FALLBACK_MODEL") or "qwen3:4b"


# --------------------------------------------------------------------------- parsing
def extract_json_object(text: str) -> Optional[dict]:
    """The last balanced ``{...}`` in ``text`` that parses and has a ``verdict``."""
    text = (text or "").replace("```json", "```")
    found: Optional[dict] = None
    i = 0
    while i < len(text):
        if text[i] != "{":
            i += 1
            continue
        depth, j, in_str, esc = 0, i, False, False
        while j < len(text):
            c = text[j]
            if in_str:
                esc = (not esc) and c == "\\"
                if c == '"' and not esc:
                    in_str = False
            elif c == '"':
                in_str = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        if depth == 0 and j < len(text):
            try:
                obj = json.loads(text[i:j + 1])
                if isinstance(obj, dict) and "verdict" in obj:
                    found = obj
            except json.JSONDecodeError:
                pass
            i = j + 1
        else:
            i += 1
    return found


def normalize_verdict(obj: dict) -> Optional[dict]:
    """Coerce a model's JSON into the InspectionVerdict contract, or None."""
    try:
        verdict = str(obj.get("verdict", "")).strip().lower()
        if verdict not in ("clean", "suspicious", "malicious"):
            return None
        conf = float(obj.get("confidence", 0.5))
        if conf > 1.0 and conf <= 100.0:
            conf /= 100.0
        conf = min(1.0, max(0.0, conf))
        phrases = obj.get("flagged_phrases") or []
        if isinstance(phrases, str):
            phrases = [phrases]
        return {"verdict": verdict, "confidence": conf,
                "reasoning": str(obj.get("reasoning") or "").strip() or "(no reasoning given)",
                "flagged_phrases": [str(p) for p in phrases if str(p).strip()]}
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------- rate limiter
class _Bucket:
    """Blocking token bucket: at most ``per_minute`` acquisitions per rolling minute."""

    def __init__(self, per_minute: float):
        self.interval = 60.0 / max(per_minute, 0.1)
        self._next = 0.0
        self._lock = threading.Lock()

    def acquire(self) -> None:
        with self._lock:
            now = time.monotonic()
            wait = max(0.0, self._next - now)
            self._next = max(now, self._next) + self.interval
        if wait:
            time.sleep(wait)


# --------------------------------------------------------------------------- cache
class _Cache:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()
        self._data: dict[str, dict] = {}
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                try:
                    rec = json.loads(line)
                    self._data[rec["key"]] = rec
                except (json.JSONDecodeError, KeyError):
                    continue

    def get(self, key: str) -> Optional[dict]:
        return self._data.get(key)

    def put(self, key: str, verdict: dict, meta: dict) -> None:
        rec = {"key": key, "verdict": verdict, "meta": meta}
        with self._lock:
            self._data[key] = rec
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec) + "\n")


# --------------------------------------------------------------------------- chain
Transport = Callable[[Slot, dict, float], tuple[int, dict, dict]]   # -> (status, headers, json)


class ChainLLM:
    def __init__(self, slots: Optional[list[Slot]] = None, transport: Optional[Transport] = None,
                 rpm: Optional[float] = None, timeout_s: float = 150.0,
                 cache_path: Optional[Path] = None, use_cache: Optional[bool] = None,
                 max_tokens: int = 2500):
        self.slots = slots if slots is not None else build_slots()
        self._transport = transport or self._http
        self.timeout_s = timeout_s
        self.max_tokens = max_tokens
        self.free_tier_exhausted_until = 0.0
        rpm = rpm or float(os.environ.get("OPENROUTER_RPM", "16"))
        self._bucket = _Bucket(rpm)
        if use_cache is None:
            use_cache = os.environ.get("LLM_CACHE", "on").lower() != "off"
        self._cache = _Cache(cache_path or (REPO_ROOT / "logs" / "llm_cache.jsonl")) if use_cache else None
        self._lock = threading.Lock()
        self.events: list[str] = []          # human-readable chain events (disabled slots, quota)

    # -- identity ---------------------------------------------------------------
    @property
    def chain_id(self) -> str:
        return " > ".join(f"{s.provider}:{s.model}:{s.method}" for s in self.slots)

    def describe(self) -> list[dict]:
        return [{"provider": s.provider, "model": s.model, "method": s.method,
                 "usable": s.usable(), "disabled_reason": s.disabled_reason} for s in self.slots]

    # -- public ----------------------------------------------------------------
    def complete(self, system: str, user: str, extra_key: str = "") -> tuple[dict, dict]:
        """Return ``(verdict_dict, meta)``. Raises ChainError when nothing answers."""
        key = hashlib.sha256(json.dumps([system, user, extra_key, self.chain_id]).encode()).hexdigest()
        if self._cache is not None:
            hit = self._cache.get(key)
            if hit:
                return hit["verdict"], {**hit["meta"], "cached": True}
        tried: list[str] = []
        for slot in self.slots:
            if slot.provider == "openrouter" and time.monotonic() < self.free_tier_exhausted_until:
                tried.append(f"{slot.label}: free-tier daily quota exhausted")
                continue
            if not slot.usable():
                tried.append(f"{slot.label}: disabled ({slot.disabled_reason or 'cooling down'})")
                continue
            result = self._try_slot(slot, system, user, tried)
            if result is not None:
                verdict, meta = result
                meta["slots_tried"] = tried + [f"{slot.label}: ok"]
                meta["cached"] = False
                if self._cache is not None:
                    self._cache.put(key, verdict, meta)
                return verdict, meta
        raise ChainError("no LLM slot produced a valid verdict: " + "; ".join(tried))

    # -- one slot -----------------------------------------------------------------
    def _try_slot(self, slot: Slot, system: str, user: str, tried: list[str]):
        attempts = 0
        for attempt in range(2):
            attempts += 1
            if slot.provider == "openrouter":
                self._bucket.acquire()
            t0 = time.monotonic()
            try:
                status, headers, data = self._transport(slot, self._payload(slot, system, user), self.timeout_s)
            except Exception as exc:       # network error / timeout
                tried.append(f"{slot.label}: {type(exc).__name__}")
                continue
            elapsed = (time.monotonic() - t0) * 1000
            if status == 200:
                parsed = self._parse(slot, data)
                if parsed is not None:
                    usage = data.get("usage") or {}
                    return parsed, {
                        "provider": slot.provider, "model": slot.model, "method": slot.method,
                        "latency_ms": round(elapsed, 1), "attempts": attempts,
                        "tokens": {"prompt": usage.get("prompt_tokens") or data.get("prompt_eval_count"),
                                   "completion": usage.get("completion_tokens") or data.get("eval_count")},
                        "served_by": data.get("provider")}
                tried.append(f"{slot.label}: unparseable output")
                continue
            msg = json.dumps(data)[:300].lower()
            if status in (400, 401, 403, 404):
                self._disable(slot, f"HTTP {status}: {self._err(data)}")
                tried.append(f"{slot.label}: HTTP {status} (disabled)")
                return None
            if status == 429:
                if "per-day" in msg or "per day" in msg or "daily" in msg:
                    reset = self._reset_in(headers, data)
                    with self._lock:
                        self.free_tier_exhausted_until = time.monotonic() + reset
                        self.events.append(f"free-tier daily quota exhausted; resets in ~{reset/3600:.1f} h")
                    tried.append(f"{slot.label}: daily quota exhausted")
                    return None
                time.sleep(min(self._reset_in(headers, data, default=8.0), 30.0))
                tried.append(f"{slot.label}: throttled")
                continue
            tried.append(f"{slot.label}: HTTP {status}")
        return None

    def _disable(self, slot: Slot, reason: str) -> None:
        with self._lock:
            slot.disabled_reason = reason
            self.events.append(f"slot {slot.label} disabled: {reason}")
        log.warning("LLM slot %s disabled: %s", slot.label, reason)

    @staticmethod
    def _err(data: dict) -> str:
        e = data.get("error")
        return (e.get("message") if isinstance(e, dict) else str(e or data))[:160]

    @staticmethod
    def _reset_in(headers: dict, data: dict, default: float = 3600.0) -> float:
        h = {k.lower(): v for k, v in headers.items()}
        if "retry-after" in h:
            try:
                return float(h["retry-after"])
            except ValueError:
                pass
        reset = h.get("x-ratelimit-reset") or ((data.get("error") or {}).get("metadata") or {}).get("headers", {}).get("X-RateLimit-Reset")
        if reset:
            try:
                ts = float(reset)
                ts = ts / 1000.0 if ts > 1e11 else ts
                return max(1.0, ts - time.time())
            except ValueError:
                pass
        return default

    # -- payloads & parsing -----------------------------------------------------------------
    def _payload(self, slot: Slot, system: str, user: str) -> dict:
        if slot.method == "ollama_format":
            return {"model": slot.model, "stream": False, "think": False, "format": VERDICT_SCHEMA,
                    "options": {"temperature": 0, "num_ctx": 4096},
                    "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
        body: dict[str, Any] = {
            "model": slot.model, "temperature": 0, "max_tokens": self.max_tokens,
            "reasoning": {"effort": "low"},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
        if slot.method == "response_format":
            body["response_format"] = {"type": "json_schema", "json_schema": {
                "name": "InspectionVerdict", "strict": True, "schema": VERDICT_SCHEMA}}
        elif slot.method == "tool_call":
            body["tools"] = [{"type": "function", "function": {
                "name": "report_verdict", "description": "Report the inspection verdict.",
                "parameters": VERDICT_SCHEMA}}]
            body["tool_choice"] = {"type": "function", "function": {"name": "report_verdict"}}
        else:  # json_parse
            body["messages"][1]["content"] += (
                '\n\nRespond with ONLY a JSON object: {"verdict": "clean|suspicious|malicious", '
                '"confidence": 0-1, "reasoning": "...", "flagged_phrases": ["exact substrings"]}')
        return body

    @staticmethod
    def _parse(slot: Slot, data: dict) -> Optional[dict]:
        if slot.method == "ollama_format":
            text = (data.get("message") or {}).get("content", "")
        else:
            choices = data.get("choices") or []
            if not choices:
                return None
            msg = choices[0].get("message") or {}
            calls = msg.get("tool_calls") or []
            text = calls[0]["function"].get("arguments", "") if (slot.method == "tool_call" and calls) \
                else (msg.get("content") or "")
        obj = extract_json_object(text)
        return normalize_verdict(obj) if obj else None

    # -- real HTTP ------------------------------------------------------------------------
    def _http(self, slot: Slot, payload: dict, timeout: float) -> tuple[int, dict, dict]:
        import httpx

        if slot.provider == "ollama":
            url = os.environ.get("LOCAL_LLM_ENDPOINT", "http://localhost:11434").rstrip("/") + "/api/chat"
            headers = {}
        else:
            key = os.environ.get("OPENROUTER_API_KEY")
            if not key:
                return 401, {}, {"error": {"message": "OPENROUTER_API_KEY not set"}}
            url, headers = OPENROUTER_URL, {"Authorization": f"Bearer {key}",
                                            "X-Title": "MCP Guardian (course project)"}
        r = httpx.post(url, json=payload, headers=headers, timeout=timeout)
        try:
            data = r.json()
        except ValueError:
            data = {"error": {"message": r.text[:200]}}
        return r.status_code, dict(r.headers), data


_CHAIN: Optional[ChainLLM] = None
_CHAIN_LOCK = threading.Lock()


def get_chain() -> ChainLLM:
    global _CHAIN
    with _CHAIN_LOCK:
        if _CHAIN is None:
            _CHAIN = ChainLLM()
        return _CHAIN


def reset_chain() -> None:
    """Drop the cached chain (tests, or after changing env)."""
    global _CHAIN
    with _CHAIN_LOCK:
        _CHAIN = None


def chain_available() -> bool:
    """True when at least one slot could plausibly answer."""
    try:
        slots = build_slots()
    except ValueError:
        return False
    for s in slots:
        if s.provider == "openrouter" and os.environ.get("OPENROUTER_API_KEY"):
            return True
        if s.provider == "ollama" and _ollama_up(_local_model()):
            return True
    return False


def _ollama_up(model: str) -> bool:
    import urllib.request

    try:
        base = os.environ.get("LOCAL_LLM_ENDPOINT", "http://localhost:11434").rstrip("/")
        with urllib.request.urlopen(f"{base}/api/tags", timeout=2) as r:
            names = {m.get("name") for m in json.load(r).get("models", [])}
        return model in names or f"{model}:latest" in names
    except Exception:
        return False
