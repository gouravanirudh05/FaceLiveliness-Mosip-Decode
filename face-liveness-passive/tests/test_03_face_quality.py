"""Face detection, the dlib-matched model crop, and the capture-quality gate."""

import cv2
import numpy as np
import pytest

from passive_liveness.config import QualityConfig
from passive_liveness.face import DetectedFace, FaceDetector, FaceDetectorError, crop_box, extract_crop
from passive_liveness.quality import assess
from passive_liveness.types import NonResponseReason as R

from conftest import ROOT

LANDMARKER = ROOT / "models" / "face_landmarker.task"


@pytest.fixture(scope="module")
def detector():
    with FaceDetector(LANDMARKER) as d:
        yield d


# ---------------------------------------------------------------- detection

def test_one_face_with_landmarks_pose_and_blendshapes(detector, portrait):
    faces = detector.detect(portrait)
    assert len(faces) == 1
    f = faces[0]
    assert f.landmarks.shape == (478, 2)
    x0, y0, x1, y1 = f.box
    assert 0 <= x0 < x1 <= portrait.shape[1] and 0 <= y0 < y1 <= portrait.shape[0]
    assert abs(f.yaw_deg) < 15 and abs(f.pitch_deg) < 15
    assert 0 <= f.eye_blink < 0.5                                   # eyes open
    assert len(f.blendshapes) == 52


def test_no_face_and_two_faces_sorted_largest_first(detector, portrait, business):
    assert detector.detect(np.zeros_like(portrait)) == []
    small = cv2.resize(portrait, None, fx=0.8, fy=0.8)   # FaceLandmarker misses much smaller faces
    canvas = np.zeros((portrait.shape[0], portrait.shape[1] + small.shape[1], 3), np.uint8)
    canvas[:, :portrait.shape[1]] = portrait
    canvas[:small.shape[0], portrait.shape[1]:] = small
    faces = detector.detect(canvas)
    assert len(faces) == 2 and faces[0].size > faces[1].size


def test_video_mode_needs_increasing_timestamps(portrait):
    with FaceDetector(LANDMARKER, video=True) as d:
        assert len(d.detect(portrait, 100)) == 1
        with pytest.raises(FaceDetectorError):
            d.detect(portrait, 100)


def test_bad_input_and_missing_model(detector, tmp_path):
    with pytest.raises(FaceDetectorError):
        detector.detect(np.zeros((10, 10), np.uint8))
    with pytest.raises(FaceDetectorError, match="not found"):
        FaceDetector(tmp_path / "x.task")


# ---------------------------------------------------------------- crop

def test_crop_is_a_centred_square_scaled_from_the_landmark_extent():
    box, clip = crop_box((400, 300, 600, 550), 1280, 960, 1.17)
    x0, y0, x1, y1 = box
    assert x1 - x0 == y1 - y0 == int(250 * 1.17)
    assert ((x0 + x1) // 2, (y0 + y1) // 2) == (500, 425)
    assert clip == 0.0


def test_crop_at_the_border_is_clamped_like_upstream():
    # upstream: top-left clamped to 0, then the side shrunk to fit -> still square
    box, clip = crop_box((0, 10, 200, 210), 640, 480, 1.17)
    assert box[0] == 0 and box[2] - box[0] == box[3] - box[1]
    assert 0 < clip < 0.5
    box, clip = crop_box((500, 380, 640, 480), 640, 480, 1.17)
    assert box[2] <= 640 and box[3] <= 480 and box[2] - box[0] == box[3] - box[1]
    assert clip > 0


def test_crop_matches_dlib_calibration_on_a_real_face(detector, portrait):
    """Crop side = 1.3 x dlib box; dlib box measured at 0.90 x the landmark extent."""
    f = detector.detect(portrait)[0]
    box, _ = crop_box(f.box, portrait.shape[1], portrait.shape[0], 1.17)
    crop = extract_crop(portrait, box)
    assert crop.shape[0] == crop.shape[1] == int(f.size * 1.17)


# ---------------------------------------------------------------- quality gate

def face(size=200, yaw=0.0, pitch=0.0) -> DetectedFace:
    return DetectedFace(np.zeros((478, 2), np.float32), (0, 0, size, size), yaw, pitch, 0.0)


def textured(brightness=128, seed=0):
    rng = np.random.default_rng(seed)
    img = np.clip(rng.normal(brightness, 30, (224, 224, 3)), 0, 255).astype(np.uint8)
    return img


@pytest.mark.parametrize("face_, crop, clip, expected", [
    (face(), textured(), 0.0, ()),
    (face(size=40), textured(), 0.0, (R.FACE_TOO_SMALL,)),
    (face(), cv2.GaussianBlur(textured(), (0, 0), 6), 0.0, (R.TOO_BLURRY,)),
    (face(), textured(15), 0.0, (R.TOO_DARK,)),
    (face(), textured(245), 0.0, (R.TOO_BRIGHT,)),
    (face(yaw=50), textured(), 0.0, (R.POSE_OUT_OF_RANGE,)),
    (face(pitch=-40), textured(), 0.0, (R.POSE_OUT_OF_RANGE,)),
    (face(), textured(), 0.4, (R.FACE_CUT_OFF,)),
    (face(size=40, yaw=60), textured(15), 0.5, (R.FACE_TOO_SMALL, R.TOO_DARK, R.POSE_OUT_OF_RANGE, R.FACE_CUT_OFF)),
])
def test_quality_gate(face_, crop, clip, expected):
    q = assess(face_, crop, clip, QualityConfig())
    assert q.reasons == expected
    assert q.passed is (not expected)


def test_real_photo_passes_quality(detector, portrait):
    f = detector.detect(portrait)[0]
    box, clip = crop_box(f.box, portrait.shape[1], portrait.shape[0], 1.17)
    q = assess(f, extract_crop(portrait, box), clip, QualityConfig())
    assert q.passed, q
    assert q.sharpness > QualityConfig().min_sharpness
