"""Synthetic presentation-attack renderings for tests.

These imitate the *physics* the heuristic cues look for (pixel-grid aliasing, a held
medium's straight edges, glare, a printer's reduced gamut). They are not a substitute
for a real PAD dataset and are never used to judge the FSFM models' accuracy.
"""

from __future__ import annotations

import cv2
import numpy as np


def head_shot(rgb: np.ndarray, face_box: tuple[int, int, int, int], factor: float = 2.4) -> np.ndarray:
    """Square head-and-shoulders crop around a face box (how a capture app frames a face)."""
    h, w = rgb.shape[:2]
    x0, y0, x1, y1 = face_box
    side = int(max(x1 - x0, y1 - y0) * factor)
    cx, cy = (x0 + x1) // 2, (y0 + y1) // 2 + int(0.1 * side)
    x, y = max(0, cx - side // 2), max(0, cy - side // 2)
    return np.ascontiguousarray(rgb[y:min(h, y + side), x:min(w, x + side)])


def _canvas(h: int, w: int, seed: int = 0) -> np.ndarray:
    """A plain room-like background: smooth gradient plus mild noise, no straight edges."""
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    base = 110 + 40 * np.sin(xx / w * np.pi) * np.cos(yy / h * np.pi / 2)
    img = np.stack([base * 1.05, base, base * 0.9], axis=-1) + rng.normal(0, 3, (h, w, 3))
    return np.clip(img, 0, 255).astype(np.uint8)


def _place(canvas: np.ndarray, item: np.ndarray, cx: int, cy: int) -> np.ndarray:
    out = canvas.copy()
    h, w = item.shape[:2]
    x0, y0 = cx - w // 2, cy - h // 2
    out[y0:y0 + h, x0:x0 + w] = item
    return out


def screen_replay(face_rgb: np.ndarray, *, out_size=(960, 1280), screen_px: int = 3, seed: int = 0) -> np.ndarray:
    """A phone/monitor showing the photo, filmed by a camera.

    The photo is rendered onto an RGB sub-pixel grid (each screen pixel = 3 coloured
    stripes), surrounded by a black bezel, given a glare streak, then resampled to the
    camera resolution - the resampling of the grid is what produces moire.
    """
    h_out, w_out = out_size
    fh, fw = face_rgb.shape[:2]
    scale = (0.62 * h_out) / fh
    disp_w, disp_h = int(fw * scale / screen_px), int(fh * scale / screen_px)
    shown = cv2.resize(face_rgb, (disp_w, disp_h), interpolation=cv2.INTER_AREA).astype(np.float32)
    big = np.repeat(np.repeat(shown, screen_px, axis=0), screen_px, axis=1)
    grid = np.zeros((screen_px, screen_px, 3), np.float32)
    for c in range(3):
        grid[:, c * screen_px // 3:(c + 1) * screen_px // 3 or screen_px, c] = 1.0
    grid[-1, :, :] *= 0.4                 # black matrix between pixel rows
    grid = grid * 0.35 + 0.65
    big *= np.tile(grid, (disp_h, disp_w, 1))
    yy, xx = np.mgrid[0:big.shape[0], 0:big.shape[1]]
    streak = np.exp(-((xx - 0.7 * big.shape[1]) + 0.6 * (yy - 0.3 * big.shape[0])) ** 2 / (2 * 40.0 ** 2))
    big = big + 255 * 0.6 * streak[..., None]
    bezel = int(0.06 * big.shape[1])
    device = np.full((big.shape[0] + 2 * bezel, big.shape[1] + 2 * bezel, 3), 15, np.float32)
    device[bezel:-bezel, bezel:-bezel] = big
    device = np.clip(device, 0, 255).astype(np.uint8)
    # the camera sees the device slightly smaller than 1:1 and slightly tilted -> the
    # sub-pixel grid aliases into a moire pattern
    cam_scale = 0.83
    dh, dw = device.shape[:2]
    m = cv2.getRotationMatrix2D((dw / 2, dh / 2), 3.0, cam_scale)
    device = cv2.warpAffine(device, m, (dw, dh), flags=cv2.INTER_LINEAR, borderValue=(15, 15, 15))
    keep = int(dh * (1 - cam_scale) / 2) - 4, int(dw * (1 - cam_scale) / 2) - 4
    device = device[max(0, keep[0]):dh - max(0, keep[0]), max(0, keep[1]):dw - max(0, keep[1])]
    dh, dw = device.shape[:2]
    if dh > h_out - 4 or dw > w_out - 4:
        f = min((h_out - 4) / dh, (w_out - 4) / dw)
        device = cv2.resize(device, None, fx=f, fy=f, interpolation=cv2.INTER_LINEAR)
    return _place(_canvas(h_out, w_out, seed), device, w_out // 2, h_out // 2)


def printed_photo(face_rgb: np.ndarray, *, out_size=(960, 1280), seed: int = 0) -> np.ndarray:
    """A paper print held in front of the camera: reduced gamut, white margin, soft focus."""
    h_out, w_out = out_size
    fh, fw = face_rgb.shape[:2]
    scale = (0.6 * h_out) / fh
    photo = cv2.resize(face_rgb, (int(fw * scale), int(fh * scale)), interpolation=cv2.INTER_AREA)
    photo = photo.astype(np.float32)
    grey = photo.mean(axis=2, keepdims=True)
    photo = grey + 0.45 * (photo - grey)                    # washed-out colour
    photo = 70 + photo * (130 / 255.0)                      # compressed tonal range (ink/paper)
    margin = int(0.05 * photo.shape[1])
    paper = np.full((photo.shape[0] + 2 * margin, photo.shape[1] + 2 * margin, 3), 225, np.float32)
    paper[margin:-margin, margin:-margin] = photo
    paper = cv2.GaussianBlur(np.clip(paper, 0, 255).astype(np.uint8), (3, 3), 0)
    canvas = _canvas(h_out, w_out, seed)
    canvas = (canvas.astype(np.float32) * 0.55).astype(np.uint8)   # darker room => visible paper edge
    return _place(canvas, paper, w_out // 2, h_out // 2)

