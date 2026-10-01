"""Adapter for the active module's ``active_liveness.passive.PassiveLivenessEngine`` protocol.

    adapter = ActivePassiveAdapter(PassiveLivenessEngine.from_config())
    adapter.start()
    for rgb, ts in frames:
        r = adapter.process_frame(rgb, ts)      # active_liveness.passive.PassiveResult | None
        if r is not None:
            break

``PassiveResult.score`` is the fused bona fide probability; ``attack_detected`` is true
only for an ATTACK decision. A NON_RESPONSE (no usable face before the stream timed
out) yields score 0.0 with ``details["decision"] == "non_response"``, which the active
module treats as a weak passive score. The full StreamResult is in ``details``.
"""

from __future__ import annotations

import numpy as np

from active_liveness.passive import PassiveResult

from .engine import PassiveLivenessEngine, PassiveStream
from .types import Decision


class ActivePassiveAdapter:
    def __init__(self, engine: PassiveLivenessEngine):
        self.engine = engine
        self._stream: PassiveStream | None = None

    def start(self) -> None:
        self.close()
        self._stream = self.engine.open_stream(include_frames=False)

    def process_frame(self, rgb: np.ndarray, timestamp_ms: int) -> PassiveResult | None:
        if self._stream is None:
            raise RuntimeError("call start() first")
        self._stream.push(rgb, timestamp_ms)
        if not self._stream.done:
            return None
        r = self._stream.result()
        self.close()
        return PassiveResult(
            score=r.bonafide_probability if r.bonafide_probability is not None else 0.0,
            attack_detected=r.decision is Decision.ATTACK,
            details=r.to_dict(),
        )

    def close(self) -> None:
        if self._stream is not None:
            self._stream.close()
            self._stream = None
