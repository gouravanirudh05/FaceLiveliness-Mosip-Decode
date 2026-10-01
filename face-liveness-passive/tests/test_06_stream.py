"""Live streams and videos: sampling, aggregation, non-response and temporal cues.

Builds up from a single frame to whole videos.
"""

import cv2
import numpy as np
import pytest

from conftest import Scores
from passive_liveness.types import Decision as D
from passive_liveness.types import NonResponseReason as R

FRAME_MS = 40   # 25 fps


def frames(img, n, start=FRAME_MS, step=FRAME_MS):
    return [(img, start + i * step) for i in range(n)]


def sway(img, n, amp_px=30, amp_deg=5):
    """A photo swayed smoothly by hand."""
    h, w = img.shape[:2]
    out = []
    for i in range(n):
        s = i / 25
        m = cv2.getRotationMatrix2D((w / 2 + amp_px * np.sin(np.pi * s), h / 2), amp_deg * np.sin(0.8 * np.pi * s), 1)
        out.append((cv2.warpAffine(img, m, (w, h), borderMode=cv2.BORDER_REPLICATE), FRAME_MS * (i + 1)))
    return out


# ---------------------------------------------------------------- level 1: sampling

def test_frames_are_sampled_by_interval(make_engine, portrait):
    e = make_engine(0.9, stream={"min_frame_interval_ms": 150, "frames_required": 100})
    with e.open_stream() as s:
        analysed = [s.push(img, ts) for img, ts in frames(portrait, 20)]
    # 25 fps, 150 ms interval -> every 4th frame (0, 160, 320 ... ms after the first)
    assert [a is not None for a in analysed] == [i % 4 == 0 for i in range(20)]


def test_out_of_order_and_duplicate_timestamps_are_ignored(make_engine, portrait):
    e = make_engine(0.9, stream={"min_frame_interval_ms": 0, "frames_required": 100})
    with e.open_stream() as s:
        assert s.push(portrait, 100) is not None
        assert s.push(portrait, 100) is None
        assert s.push(portrait, 50) is None
        assert s.push(portrait, 101) is not None
        r = s.result(allow_partial=True)
    assert r.frames_received == 4 and r.frames_analysed == 2


# ---------------------------------------------------------------- level 2: a complete stream

def test_stream_completes_after_frames_required(make_engine, portrait):
    e = make_engine(0.9, stream={"frames_required": 3, "min_frame_interval_ms": 0})
    with e.open_stream() as s:
        for img, ts in frames(portrait, 10):
            s.push(img, ts)
            if s.done:
                break
        assert ts == 3 * FRAME_MS
        r = s.result()
    assert r.complete and r.frames_used == 3
    assert r.decision is D.BONAFIDE and r.bonafide_probability == pytest.approx(0.9)
    assert len(r.frames) == 3
    assert r.thresholds == {"accept": 0.8, "reject": 0.4}
    assert set(r.models) == {"unified", "fas"}


def test_frames_after_done_are_not_analysed(make_engine, portrait):
    e = make_engine(0.9, stream={"frames_required": 2, "min_frame_interval_ms": 0})
    with e.open_stream() as s:
        out = [s.push(img, ts) for img, ts in frames(portrait, 5)]
    assert [o is not None for o in out] == [True, True, False, False, False]


@pytest.mark.parametrize("agg, expected", [("mean", 0.6), ("median", 0.7), ("min", 0.2)])
def test_aggregation(make_engine, portrait, agg, expected):
    score = Scores(0.0)
    e = make_engine(score, stream={"frames_required": 3, "min_frame_interval_ms": 0, "aggregation": agg})
    with e.open_stream() as s:
        for value, (img, ts) in zip([0.9, 0.2, 0.7], frames(portrait, 3)):
            score.value = value
            s.push(img, ts)
        r = s.result()
    assert r.bonafide_probability == pytest.approx(expected)
    assert r.temporal.score_std == pytest.approx(np.std([0.9, 0.2, 0.7]), abs=1e-4)


def test_categories_are_averaged_and_decide_the_attack_category(make_engine, portrait):
    e = make_engine(0.1, attack_label="synthetic", stream={"frames_required": 2, "min_frame_interval_ms": 0})
    with e.open_stream() as s:
        for img, ts in frames(portrait, 2):
            s.push(img, ts)
        r = s.result()
    assert r.decision is D.ATTACK and r.attack_detected
    assert r.attack_category.value == "synthetic"
    assert sum(r.categories.values()) == pytest.approx(1.0)


# ---------------------------------------------------------------- level 3: imperfect streams

def test_quality_failures_are_counted_but_not_aggregated(make_engine, portrait):
    dark = (portrait * 0.12).astype(np.uint8)
    e = make_engine(0.9, stream={"frames_required": 2, "min_frame_interval_ms": 0})
    seq = [dark, np.zeros_like(portrait), portrait, dark, portrait]
    with e.open_stream() as s:
        for i, img in enumerate(seq):
            s.push(img, FRAME_MS * (i + 1))
        r = s.result()
    assert r.complete and r.frames_used == 2 and r.frames_analysed == 5
    assert r.non_response_reasons["too_dark"] == 2 and r.non_response_reasons["no_face"] == 1
    assert "insufficient_frames" not in r.non_response_reasons
    assert r.decision is D.BONAFIDE


def test_timeout_without_enough_frames_is_a_non_response(make_engine, portrait):
    e = make_engine(0.9, stream={"frames_required": 3, "min_frame_interval_ms": 0, "max_duration_ms": 1000})
    blank = np.zeros_like(portrait)
    with e.open_stream() as s:
        s.push(portrait, 0)
        ts = 0
        while not s.done:
            ts += FRAME_MS
            s.push(blank, ts)
        assert ts == 1040
        r = s.result()
    assert r.decision is D.NON_RESPONSE and not r.complete
    assert r.bonafide_probability is None
    assert r.non_response_reasons[R.INSUFFICIENT_FRAMES.value] == 1
    assert r.frames_used == 1


def test_partial_result_on_request(make_engine, portrait):
    e = make_engine(0.3, stream={"frames_required": 5, "min_frame_interval_ms": 0})
    with e.open_stream() as s:
        for img, ts in frames(portrait, 2):
            s.push(img, ts)
        assert s.result().decision is D.NON_RESPONSE
        r = s.result(allow_partial=True)
    assert r.decision is D.ATTACK and r.frames_used == 2 and not r.complete


def test_score_changes_mid_stream(make_engine, portrait):
    """A stream that starts bona fide and turns into an attack (e.g. a photo swapped in)."""
    score = Scores(0.95)
    e = make_engine(score, stream={"frames_required": 6, "min_frame_interval_ms": 0, "aggregation": "min"})
    with e.open_stream() as s:
        for i, (img, ts) in enumerate(frames(portrait, 6)):
            score.value = 0.95 if i < 4 else 0.1
            s.push(img, ts)
        r = s.result()
    assert r.decision is D.ATTACK


# ---------------------------------------------------------------- level 4: temporal cues

def test_swayed_photo_is_static_and_raises_the_print_indicator(make_engine, portrait):
    e = make_engine(0.6, stream={"frames_required": 6, "min_frame_interval_ms": 200})
    with e.open_stream() as s:
        for img, ts in sway(portrait, 40):
            s.push(img, ts)
        r = s.result()
    assert r.temporal.frames == 6
    assert r.temporal.static_face == 1.0 and r.temporal.blink_detected is False
    assert r.temporal.head_motion > 0
    single_frame_print = np.mean([f.cues.indicators["print"] for f in r.frames])
    assert r.pai_indicators["print"] == pytest.approx(min(1.0, single_frame_print + 0.4), abs=1e-3)


# ---------------------------------------------------------------- level 5: whole videos

@pytest.fixture
def video_file(tmp_path, portrait):
    path = tmp_path / "clip.mp4"
    h, w = portrait.shape[:2]
    vw = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 25, (w, h))
    for img, _ in sway(portrait, 50):
        vw.write(cv2.cvtColor(img, cv2.COLOR_RGB2BGR))
    vw.release()
    return path


def test_video_file_uses_every_sampled_frame(make_engine, video_file):
    e = make_engine(0.9, stream={"frames_required": 3, "min_frame_interval_ms": 150})
    r = e.analyze_video(video_file)
    assert r.frames_received == 50
    assert r.frames_analysed == r.frames_used == 13          # 2 s at one frame per 160 ms
    assert r.complete and r.decision is D.BONAFIDE
    assert r.duration_ms == pytest.approx(1960, abs=40)


def test_video_can_stop_when_complete(make_engine, video_file):
    e = make_engine(0.9, stream={"frames_required": 3, "min_frame_interval_ms": 150})
    r = e.analyze_video(video_file, stop_when_complete=True, include_frames=False)
    assert r.frames_used == 3 and r.frames == ()


def test_video_from_an_iterable_and_max_frames(make_engine, portrait):
    e = make_engine(0.9, stream={"frames_required": 2, "min_frame_interval_ms": 0})
    r = e.analyze_video((portrait for _ in range(10)), max_frames=4)
    assert r.frames_received == 4 and r.frames_used == 4


def test_unreadable_video(make_engine, tmp_path):
    from passive_liveness.io import InputError
    bad = tmp_path / "bad.mp4"
    bad.write_bytes(b"junk")
    with pytest.raises(InputError):
        make_engine(0.9).analyze_video(bad)
