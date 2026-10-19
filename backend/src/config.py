"""Central configuration loader.

Reads ``config/settings.yaml`` and ``config/allowlist.yaml`` once and exposes
them as plain dicts, plus a couple of resolved convenience values. Also loads
``.env`` if ``python-dotenv`` is installed so ``os.environ`` is populated for the
LLM providers.

Kept dependency-light on purpose: everything here works even if the heavy agent
frameworks are not installed, so the deterministic layers (enforcement, metrics,
anomaly scoring) remain importable and testable in isolation.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

# Layout: <repo>/backend/src/config.py  ->  BACKEND_ROOT = <repo>/backend, REPO_ROOT = <repo>.
# Backend-owned files (config/, logs/, external/, reports) hang off BACKEND_ROOT; the
# frontend build and the markdown docs hang off REPO_ROOT.
BACKEND_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_ROOT.parent
CONFIG_DIR = BACKEND_ROOT / "config"


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:  # dotenv is optional; env may already be set another way.
        return
    # backend/.env wins if present; the repo-root .env is the other supported location.
    # load_dotenv never overrides variables already set in the shell.
    for env_path in (BACKEND_ROOT / ".env", REPO_ROOT / ".env"):
        if env_path.exists():
            load_dotenv(env_path)


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


@lru_cache(maxsize=1)
def settings() -> dict[str, Any]:
    """Parsed ``config/settings.yaml`` (cached)."""
    _load_dotenv()
    return _read_yaml(CONFIG_DIR / "settings.yaml")


@lru_cache(maxsize=1)
def allowlist() -> dict[str, Any]:
    """Parsed ``config/allowlist.yaml`` (cached)."""
    return _read_yaml(CONFIG_DIR / "allowlist.yaml")


def resolve_path(key: str) -> Path:
    """Resolve a ``paths.*`` entry from settings.yaml to an absolute path,
    creating the parent directory if needed."""
    rel = settings().get("paths", {}).get(key)
    if rel is None:
        raise KeyError(f"paths.{key} not defined in settings.yaml")
    path = BACKEND_ROOT / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def llm_provider() -> str:
    """The active LLM provider, env taking precedence over settings.yaml."""
    return os.environ.get("LLM_PROVIDER") or settings().get("llm", {}).get("provider", "openai")


def llm_model() -> str:
    return os.environ.get("LLM_MODEL") or settings().get("llm", {}).get("model", "gpt-4o-mini")
