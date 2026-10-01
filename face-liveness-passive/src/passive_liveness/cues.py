"""Heuristic presentation-attack cues (hand-crafted, uncalibrated).

The FSFM models say *whether* a face looks like a presentation attack, not *which*
instrument was used. These measurements give a rough PAI-species indication:

* ``moire``        – isolated peaks in the face crop's high-frequency spectrum, the
                     interference pattern produced when a camera films a pixel grid.
* ``border``       – long straight edges on 2-4 sides around the face: the edge of a
                     sheet of paper, a phone or a monitor held in front of the camera.
* ``glare``        – share of saturated, colourless pixels (specular reflection on
                     glossy paper or glass).
* ``low_range`` / ``low_saturation`` – compressed tonal range and washed-out colour,
                     typical of printed reproductions.
* temporal (streams only, see ``temporal.py``) – a face that only moves rigidly and never
  blinks behaves like a flat photograph.

Each indicator is in [0, 1]. They are reported as *indications* with their evidence and
must not be treated as classifier output.
"""

from __future__ import annotations

import cv2
import numpy as np

from .types import Cues

SPECTRUM_SIDE = 256


def _ramp(x: float, lo: float, hi: float) -> float:
    """0 at or below lo, 1 at or above hi, linear in between."""
    if hi == lo:
        return float(x >= hi)
    return float(np.clip((x - lo) / (hi - lo), 0.0, 1.0))


def moire_peak_ratio(crop: np.ndarray) -> float:
    """Prominence of the strongest isolated spectral peak in the mid/high band (log10 units).

    log-power minus its local average, so smooth spectra (blur, natural texture) score low
    and only narrow periodic spikes - aliasing of a pixel grid or halftone - score high.
    Only the DC rows/columns are excluded; the Hann window suppresses border leakage.
    """
    grey = cv2.cvtColor(cv2.resize(crop, (SPECTRUM_SIDE, SPECTRUM_SIDE), interpolation=cv2.INTER_AREA),
                        cv2.COLOR_RGB2GRAY).astype(np.float32)
    win = np.outer(np.hanning(SPECTRUM_SIDE), np.hanning(SPECTRUM_SIDE)).astype(np.float32)
    power = np.abs(np.fft.fftshift(np.fft.fft2((grey - grey.mean()) * win))) ** 2
    log_p = np.log10(power + 1e-6).astype(np.float32)
    prominence = log_p - cv2.blur(log_p, (15, 15))
    n = SPECTRUM_SIDE
    yy, xx = np.mgrid[0:n, 0:n] - n // 2
    r = np.hypot(xx, yy)
    band = (r > 0.12 * n) & (r < 0.48 * n) & (np.abs(xx) > 1) & (np.abs(yy) > 1)
    return float(prominence[band].max())


def border_sides(rgb: np.ndarray, face_box: tuple[int, int, int, int]) -> tuple[int, list[str]]:
    """Number of sides (0-4) around the face with a long straight edge, and which ones."""
    h, w = rgb.shape[:2]
    x0, y0, x1, y1 = face_box
    fs = max(x1 - x0, y1 - y0)
    rx0, ry0 = max(0, x0 - int(1.5 * fs)), max(0, y0 - int(1.5 * fs))
    rx1, ry1 = min(w, x1 + int(1.5 * fs)), min(h, y1 + int(1.5 * fs))
    region = cv2.cvtColor(rgb[ry0:ry1, rx0:rx1], cv2.COLOR_RGB2GRAY)
    if region.size == 0:
        return 0, []
    edges = cv2.Canny(cv2.GaussianBlur(region, (5, 5), 0), 50, 150)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=80,
                            minLineLength=int(0.8 * fs), maxLineGap=int(0.05 * fs) + 2)
    found = set()
    margin = 0.08 * fs
    for lx0, ly0, lx1, ly1 in (lines.reshape(-1, 4) if lines is not None else []):
        lx0, lx1, ly0, ly1 = lx0 + rx0, lx1 + rx0, ly0 + ry0, ly1 + ry0
        angle = abs(np.degrees(np.arctan2(ly1 - ly0, lx1 - lx0))) % 180
        mx, my = (lx0 + lx1) / 2, (ly0 + ly1) / 2
        if angle < 15 or angle > 165:                       # horizontal
            if min(lx0, lx1) < x1 and max(lx0, lx1) > x0:   # spans the face horizontally
                if my < y0 - margin:
                    found.add("top")
                elif my > y1 + margin:
                    found.add("bottom")
        elif 75 < angle < 105:                              # vertical
            if min(ly0, ly1) < y1 and max(ly0, ly1) > y0:
                if mx < x0 - margin:
                    found.add("left")
                elif mx > x1 + margin:
                    found.add("right")
    return len(found), sorted(found)


def face_mask(shape: tuple[int, int], landmarks: np.ndarray, offset: tuple[int, int]) -> np.ndarray:
    """Boolean mask of the landmark convex hull (facial skin) in crop coordinates."""
    pts = (landmarks - np.asarray(offset, np.float32)).astype(np.int32)
    mask = np.zeros(shape, np.uint8)
    cv2.fillConvexPoly(mask, cv2.convexHull(pts), 1)
    return mask.astype(bool)


def compute(rgb: np.ndarray, crop: np.ndarray, crop_box: tuple[int, int, int, int],
            face_box: tuple[int, int, int, int], landmarks: np.ndarray) -> Cues:
    """Cues for one face. Colour, tone and glare are measured on facial skin only."""
    mask = face_mask(crop.shape[:2], landmarks, crop_box[:2])
    if mask.sum() < 50:
        mask = np.ones(crop.shape[:2], bool)
    hsv = cv2.cvtColor(crop, cv2.COLOR_RGB2HSV)[mask]
    grey = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)[mask]
    sat = hsv[:, 1].astype(np.float32) / 255.0
    glare = float(((hsv[:, 2] >= 250) & (hsv[:, 1] <= 30)).mean())
    p1, p99 = np.percentile(grey, [1, 99])
    dyn_range = float((p99 - p1) / 255.0)
    moire = moire_peak_ratio(crop)
    sides, which = border_sides(rgb, face_box)

    values = {
        "moire_peak_ratio": round(moire, 4),
        "border_sides": float(sides),
        "glare_fraction": round(glare, 5),
        "dynamic_range": round(dyn_range, 4),
        "saturation_mean": round(float(sat.mean()), 4),
    }
    # Ramps calibrated on synthetic renderings (tests/synth.py) vs. sample portraits:
    # moire prominence ~1.1-1.3 on camera images and prints, ~3.0 on a filmed screen.
    s_moire = _ramp(moire, 1.6, 2.4)
    s_border = _ramp(sides, 1, 3)              # one straight edge is common in rooms; 3+ is a frame
    s_glare = _ramp(glare, 0.01, 0.06)
    s_range = _ramp(-dyn_range, -0.65, -0.45)  # tonal range below ~0.45 => strongly compressed
    s_sat = _ramp(-float(sat.mean()), -0.20, -0.12)
    # A held medium (border) supports both species; the medium-specific cues pick between them.
    screen_specific = max(s_moire, 0.7 * s_glare)
    print_specific = 0.5 * s_range + 0.5 * s_sat
    indicators = {
        "screen_replay": round(0.3 * s_border + 0.7 * screen_specific, 4),
        "print": round(0.3 * s_border + 0.7 * print_specific, 4),
    }
    evidence = []
    if s_moire > 0.5:
        evidence.append(f"periodic high-frequency pattern (moire), peak ratio {moire:.2f}")
    if sides >= 2:
        evidence.append(f"straight edges around the face on {sides} sides ({', '.join(which)})")
    if s_glare > 0.5:
        evidence.append(f"specular glare on {glare:.1%} of the face crop")
    if s_range > 0.5:
        evidence.append(f"compressed tonal range ({dyn_range:.2f})")
    if s_sat > 0.5:
        evidence.append(f"washed-out colour (mean saturation {sat.mean():.2f})")
    return Cues(values=values, indicators=indicators, evidence=tuple(evidence))
