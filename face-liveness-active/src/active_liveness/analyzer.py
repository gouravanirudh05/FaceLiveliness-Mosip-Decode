"""MediaPipe FaceLandmarker -> FaceObservation.

Head pose comes from the facial transformation matrix. MediaPipe's metric camera
space has +X = image right, +Y = image up, and the camera looking down -Z; column 2
of the rotation is the direction the face points (towards +Z when facing the camera).
With an un-mirrored camera the subject's left is on the image's right, so a positive
yaw (face pointing to image right) means the subject turned to *their* left.

Horizontal gaze is measured geometrically (iris centre between the eye corners)
rather than from eyeLookIn/Out blendshapes, so it does not depend on MediaPipe's
left/right blendshape naming.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Protocol, runtime_checkable

import numpy as np

from .types import FaceObservation


class AnalyzerError(RuntimeError):
    """The face analysis engine failed (as opposed to "no face in the frame")."""


@runtime_checkable
class FaceAnalyzer(Protocol):
    def analyze(self, rgb: np.ndarray, timestamp_ms: int) -> FaceObservation: ...

    def close(self) -> None: ...


# Landmark indices of the 478-point FaceLandmarker mesh.
# "Right"/"left" are the subject's; in an un-mirrored image the subject's right eye is on image-left.
_R_EYE_IMG_LEFT, _R_EYE_IMG_RIGHT, _R_IRIS = 33, 133, 468
_L_EYE_IMG_LEFT, _L_EYE_IMG_RIGHT, _L_IRIS = 362, 263, 473


def pose_from_matrix(matrix: np.ndarray) -> tuple[float, float, float]:
    """(yaw, pitch, roll) in degrees from a 4x4 facial transformation matrix."""
    r = np.asarray(matrix, dtype=float)[:3, :3]
    fx, fy, fz = r[:, 2]
    yaw = math.degrees(math.atan2(fx, fz))
    pitch = math.degrees(math.atan2(fy, math.hypot(fx, fz)))
    roll = math.degrees(math.atan2(r[1, 0], r[0, 0]))
    return yaw, pitch, roll


def gaze_horizontal(landmarks) -> float:
    """Mean iris position across both eyes in [-1, 1]; > 0 = towards image right."""
    ratios = []
    for a, b, iris in ((_R_EYE_IMG_LEFT, _R_EYE_IMG_RIGHT, _R_IRIS),
                       (_L_EYE_IMG_LEFT, _L_EYE_IMG_RIGHT, _L_IRIS)):
        width = landmarks[b].x - landmarks[a].x
        if abs(width) < 1e-6:
            continue
        ratios.append((landmarks[iris].x - landmarks[a].x) / width)
    if not ratios:
        return 0.0
    return max(-1.0, min(1.0, (sum(ratios) / len(ratios) - 0.5) * 2.0))


class MediaPipeFaceAnalyzer:
    """Wraps a FaceLandmarker in VIDEO mode (timestamps must strictly increase).

    Create one instance per session: VIDEO mode tracks the face across frames.
    """

    def __init__(self, model_path: str | Path, *, max_faces: int = 2, mirrored: bool = False):
        import mediapipe as mp
        from mediapipe.tasks.python import BaseOptions, vision

        model_path = Path(model_path)
        if not model_path.is_file():
            raise AnalyzerError(f"FaceLandmarker model not found: {model_path}")
        self._mp = mp
        self._mirror = -1.0 if mirrored else 1.0
        options = vision.FaceLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(model_path)),
            running_mode=vision.RunningMode.VIDEO,
            num_faces=max_faces,
            output_face_blendshapes=True,
            output_facial_transformation_matrixes=True,
        )
        try:
            self._landmarker = vision.FaceLandmarker.create_from_options(options)
        except Exception as e:  # noqa: BLE001 - MediaPipe raises bare RuntimeError/ValueError
            raise AnalyzerError(f"cannot create FaceLandmarker: {e}") from e

    def analyze(self, rgb: np.ndarray, timestamp_ms: int) -> FaceObservation:
        if not isinstance(rgb, np.ndarray) or rgb.dtype != np.uint8 or rgb.ndim != 3 or rgb.shape[2] != 3:
            raise AnalyzerError("frame must be an HxWx3 uint8 RGB array")
        image = self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb))
        try:
            result = self._landmarker.detect_for_video(image, int(timestamp_ms))
        except Exception as e:  # noqa: BLE001
            raise AnalyzerError(f"FaceLandmarker failed: {e}") from e
        return observation_from_result(result, timestamp_ms, self._mirror)

    def close(self) -> None:
        self._landmarker.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def observation_from_result(result, timestamp_ms: int, mirror: float = 1.0) -> FaceObservation:
    count = len(result.face_landmarks)
    if count != 1:
        return FaceObservation(timestamp_ms=timestamp_ms, face_count=count)
    lms = result.face_landmarks[0]
    yaw, pitch, roll = pose_from_matrix(result.facial_transformation_matrixes[0])
    blendshapes = {c.category_name: float(c.score) for c in result.face_blendshapes[0]}
    xs = [p.x for p in lms]
    ys = [p.y for p in lms]
    return FaceObservation(
        timestamp_ms=timestamp_ms,
        face_count=1,
        blendshapes=blendshapes,
        yaw_deg=yaw * mirror,
        pitch_deg=pitch,
        roll_deg=roll * mirror,
        gaze_horizontal=gaze_horizontal(lms) * mirror,
        face_box=(min(xs), min(ys), max(xs), max(ys)),
    )
