"""Capture-quality measurements and the gate that turns them into non-response reasons.

Frames failing the gate are *non-responses* in ISO/IEC 30107-3 terms (counted by
APNRR / BPNRR), not attack decisions.
"""

from __future__ import annotations

import cv2
import numpy as np

from .config import QualityConfig
from .face import DetectedFace
from .types import NonResponseReason, Quality

QUALITY_SIDE = 224   # crops are measured at model input size so thresholds are resolution independent


def measure(crop: np.ndarray) -> tuple[float, float, float]:
    """(sharpness, brightness, contrast) of an RGB crop."""
    grey = cv2.cvtColor(cv2.resize(crop, (QUALITY_SIDE, QUALITY_SIDE), interpolation=cv2.INTER_AREA),
                        cv2.COLOR_RGB2GRAY)
    sharpness = float(cv2.Laplacian(grey, cv2.CV_64F).var())
    return sharpness, float(grey.mean()), float(grey.std())


def assess(face: DetectedFace, crop: np.ndarray, clip: float, cfg: QualityConfig) -> Quality:
    sharpness, brightness, contrast = measure(crop)
    reasons = []
    if face.size < cfg.min_face_px:
        reasons.append(NonResponseReason.FACE_TOO_SMALL)
    if sharpness < cfg.min_sharpness:
        reasons.append(NonResponseReason.TOO_BLURRY)
    if brightness < cfg.min_brightness:
        reasons.append(NonResponseReason.TOO_DARK)
    if brightness > cfg.max_brightness:
        reasons.append(NonResponseReason.TOO_BRIGHT)
    if abs(face.yaw_deg) > cfg.max_abs_yaw_deg or abs(face.pitch_deg) > cfg.max_abs_pitch_deg:
        reasons.append(NonResponseReason.POSE_OUT_OF_RANGE)
    if clip > cfg.max_crop_clip:
        reasons.append(NonResponseReason.FACE_CUT_OFF)
    return Quality(passed=not reasons, reasons=tuple(reasons), face_px=round(face.size, 1),
                   sharpness=round(sharpness, 2), brightness=round(brightness, 2), contrast=round(contrast, 2))
