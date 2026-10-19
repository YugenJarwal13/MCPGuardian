"""A CrewAI-native LLM backed by ``src.llm_chain.ChainLLM``.

CrewAI's agent loop (ReAct) only accepts text containing ``Final Answer:``; a bare
JSON reply makes it re-prompt the model until ``max_iter`` — which multiplies
latency and (on a quota-limited key) burns requests. This LLM therefore returns
``Thought: ...\\nFinal Answer: <json>`` so one call completes the agent, and
``output_pydantic`` then parses the JSON into an ``InspectionVerdict``.

The per-call metadata (provider, model, structured method, latency, ...) is kept
thread-locally so ``crew.py`` can attach it to the verdict that call produced.
"""
from __future__ import annotations

import json
import threading
import uuid
from typing import Any, Optional

from crewai import BaseLLM

from src.llm_chain import ChainLLM, get_chain

# CrewAI may run ``call`` on a different thread than the one that built the agent,
# so per-call metadata is handed back through a token-keyed table, not a thread-local.
_META: dict[str, dict] = {}
_META_LOCK = threading.Lock()


def pop_meta(token: Optional[str]) -> Optional[dict]:
    with _META_LOCK:
        return _META.pop(token, None) if token else None


class ChainCrewLLM(BaseLLM):
    llm_type: str = "chain"
    model: str = "guardian-chain"
    temperature: float | None = 0.0

    chain: Any = None          # the ChainLLM; defaults to the process-wide one
    token: str = ""            # identifies this instance's call in the metadata table

    def __init__(self, chain: Optional[ChainLLM] = None, **kwargs: Any):
        kwargs.setdefault("model", "guardian-chain")
        kwargs.setdefault("token", uuid.uuid4().hex)
        super().__init__(chain=chain or get_chain(), **kwargs)

    def call(self, messages, tools=None, callbacks=None, available_functions=None,
             from_task=None, from_agent=None, response_model=None):
        system_parts: list[str] = []
        user_parts: list[str] = []
        if isinstance(messages, str):
            user_parts.append(messages)
        else:
            for m in messages:
                content = m.get("content") if isinstance(m, dict) else str(m)
                if isinstance(content, list):  # multimodal-style content parts
                    content = "\n".join(p.get("text", "") for p in content if isinstance(p, dict))
                role = m.get("role", "user") if isinstance(m, dict) else "user"
                (system_parts if role == "system" else user_parts).append(content or "")
        verdict, meta = self.chain.complete("\n\n".join(system_parts), "\n\n".join(user_parts))
        with _META_LOCK:
            _META[self.token] = meta
        return ("Thought: I have inspected the input and can give the final verdict.\n"
                f"Final Answer: {json.dumps(verdict)}")

    def supports_function_calling(self) -> bool:
        return False

    def supports_stop_words(self) -> bool:
        return False

    def get_context_window_size(self) -> int:
        return 100_000
