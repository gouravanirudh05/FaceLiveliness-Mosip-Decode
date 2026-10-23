"""Input helpers: still images and video sources -> RGB frames with timestamps."""

from __future__ import annotations

import enum
from pathlib import Path
from typing import Iterable, Iterator, Union

import cv2
import numpy as np


class InputError(ValueError):
    pass


class FrameEncoding(enum.Enum):
    ENCODED = "encoded"     # JPEG / PNG / BMP / WebP ... (anything OpenCV decodes)
    RAW_RGB = "raw_rgb"
    RAW_BGR = "raw_bgr"


ImageInput = Union[np.ndarray, bytes, bytearray, str, Path]


def decode_frame(data: bytes, encoding: FrameEncoding = FrameEncoding.ENCODED,
                 width: int = 0, height: int = 0) -> np.ndarray:
    """Bytes -> HxWx3 uint8 RGB."""
    if encoding is FrameEncoding.ENCODED:
        if not data:
            raise InputError("empty image data")
        try:
            bgr = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        except cv2.error as e:
            raise InputError(f"cannot decode image data: {e}") from e
        if bgr is None:
            raise InputError("cannot decode image data")
        return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    if width <= 0 or height <= 0:
        raise InputError("raw frames need positive width and height")
    if len(data) != width * height * 3:
        raise InputError(f"raw frame has {len(data)} bytes, expected {width * height * 3}")
    arr = np.frombuffer(data, np.uint8).reshape(height, width, 3)
    return np.ascontiguousarray(arr if encoding is FrameEncoding.RAW_RGB else arr[..., ::-1])


def load_image(image: ImageInput) -> np.ndarray:
    """ndarray (assumed RGB, uint8, HxWx3 or HxW), encoded bytes, or a file path -> RGB."""
    if isinstance(image, np.ndarray):
        if image.dtype != np.uint8:
            raise InputError("image arrays must be uint8")
        if image.ndim == 2:
            return cv2.cvtColor(image, cv2.COLOR_GRAY2RGB)
        if image.ndim == 3 and image.shape[2] == 4:
            return np.ascontiguousarray(image[..., :3])
        if image.ndim != 3 or image.shape[2] != 3:
            raise InputError("image arrays must be HxW, HxWx3 or HxWx4")
        return np.ascontiguousarray(image)
    if isinstance(image, (bytes, bytearray)):
        return decode_frame(bytes(image))
    path = Path(image)
    try:
        data = path.read_bytes()
    except OSError as e:
        raise InputError(f"cannot read image {path}: {e}") from e
    return decode_frame(data)


VideoSource = Union[str, Path, int, Iterable]


def iter_video(source: VideoSource, *, max_frames: int | None = None) -> Iterator[tuple[np.ndarray, int]]:
    """Yield (rgb, timestamp_ms) from a video file, URL/RTSP stream, camera index, or an
    iterable of RGB frames / (rgb, timestamp_ms) pairs (25 fps timestamps assumed for bare frames)."""
    count = 0
    if isinstance(source, (str, Path, int)):
        cap = cv2.VideoCapture(source if isinstance(source, int) else str(source))
        if not cap.isOpened():
            raise InputError(f"cannot open video source {source!r}")
        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        fps = fps if 1.0 <= fps <= 240.0 else 25.0
        last_ts = -1
        try:
            while max_frames is None or count < max_frames:
                ok, bgr = cap.read()
                if not ok:
                    break
                ts = int(cap.get(cv2.CAP_PROP_POS_MSEC))
                if ts <= last_ts:                       # some containers/cameras report 0 / repeats
                    ts = int(round(count * 1000.0 / fps))
                    ts = max(ts, last_ts + 1)
                last_ts = ts
                yield cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB), ts
                count += 1
        finally:
            cap.release()
        return
    for item in source:
        if max_frames is not None and count >= max_frames:
            break
        if isinstance(item, tuple):
            rgb, ts = item
        else:
            rgb, ts = item, int(round(count * 40))
        yield load_image(rgb), int(ts)
        count += 1
