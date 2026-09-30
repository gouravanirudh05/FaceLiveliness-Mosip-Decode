"""Real MediaPipe FaceLandmarker on a public sample image.

The image (MediaPipe's own ``business-person.png`` test asset) is a single still, so
these tests check the analyzer's outputs and conventions, and that a *photo* - static,
or moved / rotated in front of the camera - cannot pass the session.
"""

import random

import cv2
import numpy as np
import pytest

from active_liveness.analyzer import AnalyzerError, MediaPipeFaceAnalyzer
from active_liveness.events import ChallengeResult, DecisionStatus
from active_liveness.session import ActiveLivenessSession, SessionStatus
from active_liveness.types import Workflow

from conftest import MODEL_PATH, SAMPLE_IMAGE
from sim import replace_policy

FRAME_MS = 40


@pytest.fixture(scope="module")
def image():
    bgr = cv2.imread(str(SAMPLE_IMAGE))
    assert bgr is not None, "sample image missing"
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)


def analyze(img, mirrored=False):
    with MediaPipeFaceAnalyzer(MODEL_PATH, mirrored=mirrored) as a:
        return a.analyze(img, 0)


def photo_in_frame(img, dx=0, dy=0, angle=0.0, size=(1280, 960), scale=0.55):
    """Place the photo on a webcam-sized canvas, as if held in front of the camera."""
    w, h = size
    small = cv2.resize(img, None, fx=scale, fy=scale)
    sh, sw = small.shape[:2]
    canvas = np.full((h, w, 3), 40, np.uint8)
    x0, y0 = (w - sw) // 2 + dx, (h - sh) // 2 + dy - 150
    xs, ys = max(0, x0), max(0, y0)
    xe, ye = min(w, x0 + sw), min(h, y0 + sh)
    canvas[ys:ye, xs:xe] = small[ys - y0:ye - y0, xs - x0:xe - x0]
    if angle:
        canvas = cv2.warpAffine(canvas, cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0), (w, h))
    return canvas


# ---------------------------------------------------------------- analyzer outputs

def test_single_face_is_analysed(image):
    o = analyze(image)
    assert o.face_count == 1
    assert len(o.blendshapes) == 52
    assert all(np.isfinite([o.yaw_deg, o.pitch_deg, o.roll_deg, o.gaze_horizontal]))
    x0, y0, x1, y1 = o.face_box
    assert 0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1


def test_expression_signals_match_the_photo(image):
    o = analyze(image)
    assert o.smile > 0.5            # the subject is smiling
    assert o.blink < 0.2            # eyes open
    assert o.jaw_open < 0.15        # mouth closed


def test_no_face(image):
    assert analyze(np.zeros_like(image)).face_count == 0


def test_two_faces(image):
    assert analyze(np.hstack([image, cv2.flip(image, 1)])).face_count == 2


def test_horizontal_flip_negates_yaw_roll_and_gaze(image):
    a, b = analyze(image), analyze(cv2.flip(image, 1))
    assert b.yaw_deg == pytest.approx(-a.yaw_deg, abs=1.5)
    assert b.roll_deg == pytest.approx(-a.roll_deg, abs=1.5)
    assert b.gaze_horizontal == pytest.approx(-a.gaze_horizontal, abs=0.05)
    assert b.pitch_deg == pytest.approx(a.pitch_deg, abs=1.5)


def test_mirrored_setting_undoes_a_mirrored_device(image):
    straight = analyze(image)
    mirrored_device = analyze(cv2.flip(image, 1), mirrored=True)
    assert mirrored_device.yaw_deg == pytest.approx(straight.yaw_deg, abs=1.5)
    assert mirrored_device.gaze_horizontal == pytest.approx(straight.gaze_horizontal, abs=0.05)


def test_in_plane_rotation_direction_shows_in_roll(image):
    h, w = image.shape[:2]
    ccw = cv2.warpAffine(image, cv2.getRotationMatrix2D((w / 2, h / 2), 15, 1.0), (w, h))
    cw = cv2.warpAffine(image, cv2.getRotationMatrix2D((w / 2, h / 2), -15, 1.0), (w, h))
    base = analyze(image).roll_deg
    assert analyze(ccw).roll_deg - base == pytest.approx(15, abs=4)
    assert analyze(cw).roll_deg - base == pytest.approx(-15, abs=4)


def test_video_mode_rejects_non_increasing_timestamps(image):
    with MediaPipeFaceAnalyzer(MODEL_PATH) as a:
        a.analyze(image, 100)
        with pytest.raises(AnalyzerError):
            a.analyze(image, 100)


def test_bad_input_and_missing_model(tmp_path):
    with pytest.raises(AnalyzerError):
        MediaPipeFaceAnalyzer(tmp_path / "missing.task")
    with MediaPipeFaceAnalyzer(MODEL_PATH) as a:
        with pytest.raises(AnalyzerError):
            a.analyze(np.zeros((10, 10), np.uint8), 1)


# ---------------------------------------------------------------- photo attacks through a real session

def run_photo(policy, frames, seed=3):
    with MediaPipeFaceAnalyzer(MODEL_PATH) as a:
        s = ActiveLivenessSession(policy, Workflow.RESIDENT, analyzer=a, passive_score=0.9,
                                  rng=random.Random(seed))
        events = s.start()
        ts = 0
        i = 0
        while s.status in (SessionStatus.RUNNING, SessionStatus.RETRY_AVAILABLE):
            if s.status is SessionStatus.RETRY_AVAILABLE:
                events += s.retry()
                continue
            ts += FRAME_MS
            events += s.process_frame(frames[i % len(frames)], ts)
            i += 1
        return s, events


def test_static_photo_fails_every_step(policy, image):
    p = replace_policy(policy, max_retries=1)
    s, events = run_photo(p, [image])
    assert s.status is SessionStatus.FAILED
    assert not any(e.passed for e in events if isinstance(e, ChallengeResult))


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_photo_moved_and_rotated_in_front_of_camera_fails(policy, image, seed):
    """Waving a printed photo shifts the estimated pose a little (<~11 deg yaw, <~7 deg pitch
    in this setup) but must not satisfy head-movement challenges, even when retries start at
    the MEDIUM (head movement) tier."""
    moves = [(0, 0, 0), (-300, 0, 0), (300, 0, 0), (0, 150, 0), (0, 0, 10), (0, 0, -10), (250, 120, 8)]
    frames = []
    for dx, dy, ang in moves:
        frames += [photo_in_frame(image, dx, dy, ang)] * 6     # hold each position a moment
    p = replace_policy(policy, max_retries=1)
    s, events = run_photo(p, frames, seed=seed)
    assert s.status is SessionStatus.FAILED
    assert not any(e.passed for e in events if isinstance(e, ChallengeResult))
    assert events[-1].status is DecisionStatus.FAILED
