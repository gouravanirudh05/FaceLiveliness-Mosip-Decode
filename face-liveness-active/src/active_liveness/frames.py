"""Decode frames as delivered by a device adapter into HxWx3 uint8 RGB arrays."""

from __future__ import annotations

from enum import Enum

import cv2
import numpy as np


class FrameEncoding(Enum):
    JPEG = "jpeg"
    PNG = "png"
    RAW_RGB = "raw_rgb"
    RAW_BGR = "raw_bgr"


class FrameDecodeError(ValueError):
    pass


def decode_frame(data: bytes, encoding: FrameEncoding, width: int = 0, height: int = 0) -> np.ndarray:
    if not data:
        raise FrameDecodeError("empty frame data")
    if encoding in (FrameEncoding.JPEG, FrameEncoding.PNG):
        try:
            bgr = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
        except cv2.error as e:
            raise FrameDecodeError(f"cannot decode {encoding.value} frame: {e}") from e
        if bgr is None:
            raise FrameDecodeError(f"cannot decode {encoding.value} frame (corrupt or incomplete)")
        return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    if encoding in (FrameEncoding.RAW_RGB, FrameEncoding.RAW_BGR):
        if width <= 0 or height <= 0:
            raise FrameDecodeError("raw frames need a positive width and height")
        expected = width * height * 3
        if len(data) != expected:
            raise FrameDecodeError(f"raw frame has {len(data)} bytes, expected {expected} "
                                   f"for {width}x{height}x3")
        arr = np.frombuffer(data, dtype=np.uint8).reshape(height, width, 3)
        return arr[:, :, ::-1].copy() if encoding is FrameEncoding.RAW_BGR else arr.copy()
    raise FrameDecodeError(f"unsupported encoding {encoding}")
