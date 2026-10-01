"""Heuristic PAI cues (single frame) and temporal cues (streams).

Bona fide controls are the sample portraits themselves; attacks are the synthetic
renderings in synth.py, which model the physics each cue looks for.
"""

import cv2
import numpy as np
import pytest

import synth
from passive_liveness import cues
from passive_liveness.face import FaceDetector, crop_box, extract_crop
from passive_liveness.temporal import TemporalTracker, static_face_score
from passive_liveness.types import TemporalCues

from conftest import ROOT

LANDMARKER = ROOT / "models" / "face_landmarker.task"


@pytest.fixture(scope="module")
def detector():
    with FaceDetector(LANDMARKER) as d:
        yield d


def analyse(detector, rgb):
    f = detector.detect(rgb)[0]
    box, _ = crop_box(f.box, rgb.shape[1], rgb.shape[0], 1.17)
    return cues.compute(rgb, extract_crop(rgb, box), box, f.box, f.landmarks)


@pytest.fixture(scope="module", params=["portrait", "business"])
def headshot(request, detector, portrait, business):
    img = {"portrait": portrait, "business": business}[request.param]
    return synth.head_shot(img, detector.detect(img)[0].box)


# ---------------------------------------------------------------- single frame

def test_live_captures_have_low_indicators(detector, headshot):
    c = analyse(detector, headshot)
    assert max(c.indicators.values()) < 0.3, c
    assert c.evidence == ()


def test_screen_replay_is_indicated(detector, headshot):
    c = analyse(detector, synth.screen_replay(headshot))
    assert c.indicators["screen_replay"] >= 0.5
    assert c.indicators["screen_replay"] > c.indicators["print"]
    assert any("moire" in e for e in c.evidence)


def test_print_is_indicated(detector, headshot):
    c = analyse(detector, synth.printed_photo(headshot))
    assert c.indicators["print"] >= 0.5
    assert c.indicators["print"] > c.indicators["screen_replay"]
    assert any("tonal range" in e or "colour" in e for e in c.evidence)


def test_moire_measure_reacts_to_a_periodic_grid_not_to_blur(headshot):
    face = cv2.resize(headshot, (256, 256))
    base = cues.moire_peak_ratio(face)
    yy, xx = np.mgrid[0:256, 0:256]
    grid = (1 + 0.15 * np.sin(2 * np.pi * (0.31 * xx + 0.07 * yy)))[..., None]
    gridded = np.clip(face * grid, 0, 255).astype(np.uint8)
    assert cues.moire_peak_ratio(gridded) > base + 0.8
    assert cues.moire_peak_ratio(cv2.GaussianBlur(face, (0, 0), 3)) < base + 0.4


def test_border_sides_finds_a_held_rectangle():
    img = np.full((600, 800, 3), 120, np.uint8)
    face_box = (330, 220, 470, 380)
    assert cues.border_sides(img, face_box)[0] == 0
    cv2.rectangle(img, (230, 110), (570, 500), (240, 240, 240), 6)
    n, which = cues.border_sides(img, face_box)
    assert n == 4 and which == ["bottom", "left", "right", "top"]


def test_glare_and_colour_are_measured_on_skin_only(detector, portrait):
    f = detector.detect(portrait)[0]
    box, _ = crop_box(f.box, portrait.shape[1], portrait.shape[0], 1.17)
    crop = extract_crop(portrait, box).copy()
    before = cues.compute(portrait, crop, box, f.box, f.landmarks).values["glare_fraction"]
    crop[:20, :] = 255                                      # white strip above the head, off the face
    after = cues.compute(portrait, crop, box, f.box, f.landmarks).values["glare_fraction"]
    assert after == pytest.approx(before, abs=1e-4)


# ---------------------------------------------------------------- temporal

def tracker_with(blendshape_frames, centres=None):
    t = TemporalTracker()
    for i, b in enumerate(blendshape_frames):
        c = centres[i] if centres else (100.0, 100.0)
        t.add(np.tile(np.array(c, np.float32), (478, 1)), 200.0, b, 0.9)
    return t


NEUTRAL = {"eyeBlinkLeft": 0.05, "eyeBlinkRight": 0.05, "jawOpen": 0.02, "mouthSmileLeft": 0.1,
           "mouthSmileRight": 0.1, "browInnerUp": 0.0, "mouthPucker": 0.0, "mouthFunnel": 0.0}


def test_static_photo_scores_as_static():
    t = tracker_with([dict(NEUTRAL, jawOpen=0.02 + 0.01 * (i % 2)) for i in range(6)],
                     centres=[(100 + 20 * i, 100) for i in range(6)])         # moved, not changing
    c = t.cues()
    assert c.blink_detected is False and c.expression_range < 0.05
    assert c.head_motion == pytest.approx(0.1, abs=1e-3)
    assert static_face_score(c) == 1.0


def test_blink_or_expression_scores_as_live():
    blink = [NEUTRAL, dict(NEUTRAL, eyeBlinkLeft=0.8, eyeBlinkRight=0.8), NEUTRAL]
    c = tracker_with(blink).cues()
    assert c.blink_detected and static_face_score(c) == 0.0
    smile = [NEUTRAL, dict(NEUTRAL, mouthSmileLeft=0.7, mouthSmileRight=0.7)]
    c = tracker_with(smile).cues()
    assert c.blink_detected is False and static_face_score(c) == 0.0


def test_static_score_is_graded_between_the_bounds():
    mid = tracker_with([NEUTRAL, dict(NEUTRAL, jawOpen=0.295)]).cues()      # range 0.275
    assert static_face_score(mid) == pytest.approx(0.5, abs=0.01)


def test_too_few_frames_gives_no_temporal_verdict():
    assert static_face_score(tracker_with([NEUTRAL]).cues()) is None
    assert static_face_score(TemporalCues()) is None


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_real_photo_moved_by_hand_has_no_expression_change(portrait, seed):
    """A photo moved smoothly in front of the camera (25 fps, ~0.5 Hz sway of +-40 px,
    +-8 deg, +-6 % scale), sampled every 200 ms, must not look like a changing expression."""
    rng = np.random.default_rng(seed)
    ph = rng.uniform(0, 2 * np.pi, 3)
    h, w = portrait.shape[:2]
    t = TemporalTracker()
    with FaceDetector(LANDMARKER, video=True) as d:
        for i in range(30):
            s = i / 25
            m = cv2.getRotationMatrix2D((w / 2 + 40 * np.sin(np.pi * s + ph[0]), h / 2),
                                        8 * np.sin(0.8 * np.pi * s + ph[1]), 1 + 0.06 * np.sin(0.6 * np.pi * s + ph[2]))
            f = d.detect(cv2.warpAffine(portrait, m, (w, h), borderMode=cv2.BORDER_REPLICATE), 40 * (i + 1))[0]
            if i % 5 == 0:
                t.add(f.landmarks, f.size, f.blendshapes, None)
    c = t.cues()
    assert c.expression_range < 0.2 and not c.blink_detected, c
    assert static_face_score(c) == 1.0
