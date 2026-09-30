"""Plug-in point for a passive liveness / PAD engine (not implemented here).

Intended hybrid flow, owned by whichever orchestrator combines the two:

    engine.start()
    for frame, ts in stream:
        result = engine.process_frame(frame, ts)
        if result is not None:
            break
    if result.attack_detected:
        -> reject (PAD failure; do NOT start active liveness)
    elif result.score >= passive_threshold:
        -> accept
    else:
        -> ActiveLivenessSession(policy, workflow, passive_score=result.score)
           (or StartSession.passive_score over gRPC)

The active module only consumes ``PassiveResult.score``: a score below
``escalation.passive_weak_threshold`` makes the active sequence harder.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, runtime_checkable

import numpy as np


@dataclass(frozen=True)
class PassiveResult:
    score: float                      # liveness confidence in [0, 1]
    attack_detected: bool             # PAD verdict
    details: Mapping[str, Any] = field(default_factory=dict)   # diagnostics / audit only, never shown to users

    def __post_init__(self):
        if not 0.0 <= self.score <= 1.0:
            raise ValueError("score must be within [0, 1]")


@runtime_checkable
class PassiveLivenessEngine(Protocol):
    def start(self) -> None:
        """Begin a new evaluation (clears any per-session state)."""

    def process_frame(self, rgb: np.ndarray, timestamp_ms: int) -> PassiveResult | None:
        """Consume one HxWx3 uint8 RGB frame; return a result once enough frames were seen."""

    def close(self) -> None: ...
