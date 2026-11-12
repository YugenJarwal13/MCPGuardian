"""Which agent is calling the model, and what each run has spent.

Two context variables travel with the work (including into worker threads, which copy the context):

* ``CURRENT_AGENT`` names the agent making a model call, so every model call is traced under its agent
  (``static_inspector.llm``, ``runtime_inspector.llm``) and cost can be grouped per agent in Langfuse.
* ``RUN_USAGE`` is one mutable record per pipeline run. Every model call adds its tokens and cost to it, and
  the run's totals become Langfuse scores when the run ends.

Cost: the provider's own figure is used when it reports one (OpenRouter does; it is 0 for free-tier models, and
absent for a local model). Separately, a clearly labelled *reference* cost prices the same tokens at
``GUARDIAN_REF_PRICE_IN_PER_M`` / ``GUARDIAN_REF_PRICE_OUT_PER_M`` USD per million tokens, so a free or local
model still shows what the run would cost on a paid one. It is an estimate, never mixed into the provider cost.
"""
from __future__ import annotations

import contextvars
import os
import threading
from dataclasses import dataclass, field
from typing import Any, Optional

CURRENT_AGENT: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("guardian_agent", default=None)
RUN_USAGE: contextvars.ContextVar[Optional["RunUsage"]] = contextvars.ContextVar("guardian_run_usage", default=None)

AGENT_LABELS = {
    "static_analysis": "static_inspector",
    "runtime_inspection": "runtime_inspector",
    "behavioral_anomaly_judge": "behaviour_judge",
    "pipeline_manager": "case_manager",
}


def agent_label(kind: str | None) -> str:
    return AGENT_LABELS.get(kind or "", kind or "llm")


def reference_prices() -> tuple[float, float]:
    def num(name: str, default: float) -> float:
        try:
            return float(os.environ.get(name, default))
        except ValueError:
            return default

    return num("GUARDIAN_REF_PRICE_IN_PER_M", 0.30), num("GUARDIAN_REF_PRICE_OUT_PER_M", 1.20)


def reference_price_label() -> str:
    pin, pout = reference_prices()
    return f"${pin:g} in / ${pout:g} out per 1M tokens"


def reference_cost(tokens_in: int, tokens_out: int) -> float:
    pin, pout = reference_prices()
    return tokens_in / 1e6 * pin + tokens_out / 1e6 * pout


@dataclass
class AgentUsage:
    calls: int = 0              # model calls actually made
    cached: int = 0             # answers served from the local cache (no model call, no tokens, no cost)
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0       # what the provider reported (0 for free models)
    cost_known: bool = False    # False when the provider reported nothing (a local model)


@dataclass
class RunUsage:
    agents: dict[str, AgentUsage] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def add(self, agent: str, meta: dict[str, Any]) -> None:
        with self._lock:
            u = self.agents.setdefault(agent, AgentUsage())
            if meta.get("cached"):
                u.cached += 1
                return
            u.calls += 1
            tokens = meta.get("tokens") or {}
            u.tokens_in += int(tokens.get("prompt") or 0)
            u.tokens_out += int(tokens.get("completion") or 0)
            if meta.get("cost_usd") is not None:
                u.cost_usd += float(meta["cost_usd"])
                u.cost_known = True

    def totals(self) -> AgentUsage:
        t = AgentUsage()
        for u in self.agents.values():
            t.calls += u.calls
            t.cached += u.cached
            t.tokens_in += u.tokens_in
            t.tokens_out += u.tokens_out
            t.cost_usd += u.cost_usd
            t.cost_known = t.cost_known or u.cost_known
        return t

    def as_dict(self) -> dict[str, dict]:
        with self._lock:
            return {name: {"calls": u.calls, "cached": u.cached, "tokens_in": u.tokens_in,
                           "tokens_out": u.tokens_out, "cost_usd": round(u.cost_usd, 6),
                           "reference_cost_usd": round(reference_cost(u.tokens_in, u.tokens_out), 6)}
                    for name, u in self.agents.items()}


def record(meta: dict[str, Any]) -> None:
    """Add one model call to the current run (a no-op outside a run)."""
    run = RUN_USAGE.get()
    if run is not None:
        run.add(agent_label(CURRENT_AGENT.get()) if CURRENT_AGENT.get() else "llm", meta)
