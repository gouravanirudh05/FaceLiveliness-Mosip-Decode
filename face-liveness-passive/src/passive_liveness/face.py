"""Face detection (MediaPipe FaceLandmarker) and the model input crop.

The FSFM checkpoints were fine-tuned on faces cropped from dlib's frontal-face box,
enlarged 1.3x into a square and clipped at the image border. dlib is not used here;
instead the crop is derived from MediaPipe's 478 landmarks. On the calibration set
(MediaPipe/scikit-image sample portraits, flipped, scaled and rotated; 43 detections)
dlib's box side was 0.90 x the landmark extent (std 0.06) with the same centre
(offset < 1 % of the face size), so ``crop_scale = 1.3 x 0.90 = 1.17``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np


class FaceDetectorError(RuntimeError):
    pass


@dataclass(frozen=True)
class DetectedFace:
    landmarks: np.ndarray                 # (478, 2) pixel coordinates
    box: tuple[int, int, int, int]        # landmark extent, px
    yaw_deg: float
    pitch_deg: float
    roll_deg: float
    blendshapes: dict[str, float] = field(default_factory=dict)

    @property
    def size(self) -> float:
        x0, y0, x1, y1 = self.box
        return float(max(x1 - x0, y1 - y0))

    @property
    def eye_blink(self) -> float | None:
        b = self.blendshapes
        if "eyeBlinkLeft" in b and "eyeBlinkRight" in b:
            return (b["eyeBlinkLeft"] + b["eyeBlinkRight"]) / 2
        return None


def pose_from_matrix(matrix: np.ndarray) -> tuple[float, float, float]:
    """(yaw, pitch, roll) in degrees from MediaPipe's facial transformation matrix
    (same convention as the active module: + yaw = subject's left, + pitch = up)."""
    r = np.asarray(matrix, dtype=float)[:3, :3]
    fx, fy, fz = r[:, 2]
    return (math.degrees(math.atan2(fx, fz)),
            math.degrees(math.atan2(fy, math.hypot(fx, fz))),
            math.degrees(math.atan2(r[1, 0], r[0, 0])))


class FaceDetector:
    """FaceLandmarker in IMAGE mode (independent stills) or VIDEO mode (one per stream;
    timestamps must strictly increase)."""

    def __init__(self, model_path: str | Path, *, max_faces: int = 2, video: bool = False):
        import mediapipe as mp
        from mediapipe.tasks.python import BaseOptions, vision

        model_path = Path(model_path)
        if not model_path.is_file():
            raise FaceDetectorError(f"FaceLandmarker model not found: {model_path}")
        self._mp = mp
        self.video = video
        options = vision.FaceLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(model_path)),
            running_mode=vision.RunningMode.VIDEO if video else vision.RunningMode.IMAGE,
            num_faces=max_faces,
            output_face_blendshapes=True,
            output_facial_transformation_matrixes=True,
        )
        try:
            self._landmarker = vision.FaceLandmarker.create_from_options(options)
        except Exception as e:  # noqa: BLE001 - MediaPipe raises bare RuntimeError/ValueError
            raise FaceDetectorError(f"cannot create FaceLandmarker: {e}") from e

    def detect(self, rgb: np.ndarray, timestamp_ms: int = 0) -> list[DetectedFace]:
        """Faces sorted largest first."""
        if not isinstance(rgb, np.ndarray) or rgb.dtype != np.uint8 or rgb.ndim != 3 or rgb.shape[2] != 3:
            raise FaceDetectorError("frame must be an HxWx3 uint8 RGB array")
        image = self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb))
        if self._landmarker is None:
            raise FaceDetectorError("detector is closed")
        try:
            result = (self._landmarker.detect_for_video(image, int(timestamp_ms)) if self.video
                      else self._landmarker.detect(image))
        except Exception as e:  # noqa: BLE001
            raise FaceDetectorError(f"FaceLandmarker failed: {e}") from e
        h, w = rgb.shape[:2]
        faces = []
        for i, lms in enumerate(result.face_landmarks):
            pts = np.array([(p.x * w, p.y * h) for p in lms], dtype=np.float32)
            x0, y0 = pts.min(axis=0)
            x1, y1 = pts.max(axis=0)
            yaw, pitch, roll = pose_from_matrix(result.facial_transformation_matrixes[i])
            shapes = ({c.category_name: float(c.score) for c in result.face_blendshapes[i]}
                      if result.face_blendshapes else {})
            faces.append(DetectedFace(pts, (int(x0), int(y0), int(math.ceil(x1)), int(math.ceil(y1))),
                                      yaw, pitch, roll, shapes))
        return sorted(faces, key=lambda f: f.size, reverse=True)

    def close(self) -> None:
        """Release the landmarker. Always close explicitly: MediaPipe's own finaliser can
        deadlock when it runs from the garbage collector."""
        if self._landmarker is not None:
            self._landmarker.close()
            self._landmarker = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def crop_box(face_box: tuple[int, int, int, int], frame_w: int, frame_h: int,
             scale: float) -> tuple[tuple[int, int, int, int], float]:
    """Square crop around the face, clipped like upstream (shifted/shrunk at the border).

    Returns ((x0, y0, x1, y1), clip) where clip is the fraction of the ideal square's area
    that had to be dropped because it fell outside the frame.
    """
    x0, y0, x1, y1 = face_box
    side = int(max(x1 - x0, y1 - y0) * scale)
    cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
    ix, iy = cx - side // 2, cy - side // 2                      # ideal (unclipped) top-left
    inside_w = max(0, min(ix + side, frame_w) - max(ix, 0))
    inside_h = max(0, min(iy + side, frame_h) - max(iy, 0))
    clip = 1.0 - (inside_w * inside_h) / float(side * side) if side > 0 else 1.0
    # upstream (get_boundingbox): clamp the top-left at 0, then shrink to fit
    x, y = max(ix, 0), max(iy, 0)
    side = min(frame_w - x, side)
    side = min(frame_h - y, side)
    return (x, y, x + side, y + side), round(clip, 4)


def extract_crop(rgb: np.ndarray, box: tuple[int, int, int, int]) -> np.ndarray:
    x0, y0, x1, y1 = box
    return np.ascontiguousarray(rgb[y0:y1, x0:x1])
