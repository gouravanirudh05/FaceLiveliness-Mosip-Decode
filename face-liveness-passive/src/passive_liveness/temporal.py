"""Temporal cues over a stream's analysed frames.

A printed photo (or a still image on a screen) can be moved, but its *expression* never
changes and its eyes never blink. Expression change is measured with MediaPipe's
blendshapes (eyeBlink, jawOpen, mouthSmile, ...). A photo swayed smoothly by hand
(25 fps; +-40 px, +-8 deg, +-6 % scale) changed no blendshape by more than 0.12 in the
tests, whereas a blink or smile changes one by 0.5 or more. Abrupt frame-to-frame jumps
(e.g. +-10 deg between consecutive samples) can produce spurious changes of up to ~0.6;
that only errs towards "live-like", i.e. the print hint is not raised.

Landmark-geometry residuals were evaluated and rejected: MediaPipe's tracked mesh
deforms when a photo is moved quickly, so they did not separate a moved photo from a
changing expression.

Live users do not necessarily blink or move within a one-second window, so a static
face is weak evidence; it only raises the *print* indicator, never the decision.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np

from .types import TemporalCues

EXPRESSION_BLENDSHAPES = ("eyeBlinkLeft", "eyeBlinkRight", "jawOpen", "mouthSmileLeft",
                          "mouthSmileRight", "browInnerUp", "mouthPucker", "mouthFunnel")
BLINK_CLOSED, BLINK_OPEN = 0.5, 0.25      # eyeBlink levels counted as a closed / open eye
STATIC_BELOW, LIVE_ABOVE = 0.20, 0.35     # expression range: static photo .. clearly changing face


@dataclass
class _Sample:
    centre: np.ndarray
    size: float
    blendshapes: dict[str, float]
    score: float | None


class TemporalTracker:
    def __init__(self):
        self._samples: list[_Sample] = []

    def add(self, landmarks: np.ndarray, size: float, blendshapes: dict[str, float], score: float | None) -> None:
        self._samples.append(_Sample(landmarks.mean(axis=0), max(size, 1.0), dict(blendshapes), score))

    def cues(self) -> TemporalCues:
        s = self._samples
        out = TemporalCues(frames=len(s))
        if len(s) >= 2:
            moves = [float(np.linalg.norm(b.centre - a.centre)) / ((a.size + b.size) / 2) for a, b in zip(s, s[1:])]
            out = replace(out, head_motion=round(float(np.mean(moves)), 5))
            shapes = [x.blendshapes for x in s if x.blendshapes]
            if len(shapes) >= 2:
                ranges = {k: max(b[k] for b in shapes) - min(b[k] for b in shapes)
                          for k in EXPRESSION_BLENDSHAPES if all(k in b for b in shapes)}
                if ranges:
                    out = replace(out, expression_range=round(max(ranges.values()), 4))
                if "eyeBlinkLeft" in ranges and "eyeBlinkRight" in ranges:
                    blink = [(b["eyeBlinkLeft"] + b["eyeBlinkRight"]) / 2 for b in shapes]
                    out = replace(out, blink_detected=bool(max(blink) >= BLINK_CLOSED and min(blink) <= BLINK_OPEN))
        scores = [x.score for x in s if x.score is not None]
        if len(scores) >= 2:
            out = replace(out, score_std=round(float(np.std(scores)), 4))
        return out


def static_face_score(t: TemporalCues) -> float | None:
    """1 = expression never changed (photo-like); 0 = clear expression change or a blink."""
    if t.expression_range is None:
        return None
    if t.blink_detected:
        return 0.0
    return round(float(np.clip((LIVE_ABOVE - t.expression_range) / (LIVE_ABOVE - STATIC_BELOW), 0.0, 1.0)), 4)
