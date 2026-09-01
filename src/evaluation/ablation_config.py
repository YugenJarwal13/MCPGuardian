"""Phase 4.5 — ablation scaffolding.

A single toggle set so Phase 8 can produce the static-only / runtime-only /
combined comparison table without duplicating pipeline code. Both inspection
agents and the behavioral layer respect these flags (skip execution when off).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class AblationConfig:
    enable_static: bool = True
    enable_runtime: bool = True
    enable_behavioral: bool = True

    def label(self) -> str:
        on = [n for n, v in (
            ("static", self.enable_static),
            ("runtime", self.enable_runtime),
            ("behavioral", self.enable_behavioral),
        ) if v]
        if len(on) == 3:
            return "combined"
        if len(on) == 1:
            return f"{on[0]}_only"
        return "+".join(on) if on else "none"


# The three canonical configurations Phase 8 tabulates.
CONFIGS: dict[str, AblationConfig] = {
    "static_only": AblationConfig(enable_static=True, enable_runtime=False, enable_behavioral=False),
    "runtime_only": AblationConfig(enable_static=False, enable_runtime=True, enable_behavioral=False),
    "combined": AblationConfig(enable_static=True, enable_runtime=True, enable_behavioral=True),
}
