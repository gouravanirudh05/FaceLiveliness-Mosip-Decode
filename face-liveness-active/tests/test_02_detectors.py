"""Per-action detector behaviour on synthetic signal sequences."""

import pytest

from active_liveness.config import StepParams
from active_liveness.detectors import (
    CompoundDetector, DetectorState, Hint, create_challenge_detector, create_detector,
)
from active_liveness.types import Action

from sim import feed, hold, obs, ramp

STEP = StepParams(timeout_s=8, yaw_deg=15, pitch_deg=10)
S = DetectorState


def final(updates):
    return updates[-1].state


# ---------------------------------------------------------------- correct actions pass

@pytest.mark.parametrize("action, frames", [
    (Action.BLINK, hold(2, blink=0.9) + hold(1)),
    (Action.SMILE, ramp(3, {}, dict(smile=0.8)) + hold(3, smile=0.8)),
    (Action.OPEN_MOUTH, ramp(3, {}, dict(jaw=0.7)) + hold(3, jaw=0.7)),
    (Action.TURN_LEFT, ramp(3, {}, dict(yaw=22)) + hold(3, yaw=22)),
    (Action.TURN_RIGHT, ramp(3, {}, dict(yaw=-22)) + hold(3, yaw=-22)),
    (Action.LOOK_UP, ramp(3, {}, dict(pitch=15)) + hold(3, pitch=15)),
    (Action.LOOK_DOWN, ramp(3, {}, dict(pitch=-15)) + hold(3, pitch=-15)),
    (Action.NOD, ramp(3, {}, dict(pitch=-15)) + ramp(3, dict(pitch=-15), {})),
    (Action.GAZE_LEFT, hold(3, gaze_h=0.3)),
    (Action.GAZE_RIGHT, hold(3, gaze_h=-0.3)),
    (Action.GAZE_UP, hold(3, gaze_up=0.7)),
    (Action.GAZE_DOWN, hold(3, gaze_down=0.7)),
])
def test_action_is_detected_after_neutral_baseline(action, frames, thresholds):
    d = create_detector(action, STEP, thresholds)
    updates = feed(d, hold(3) + frames)
    assert [u.state for u in updates[:2]] == [S.WAITING_NEUTRAL] * 2
    assert final(updates) is S.COMPLETED
    assert 0.0 <= updates[-1].margin <= 1.0


def test_completed_is_sticky(thresholds):
    d = create_detector(Action.SMILE, STEP, thresholds)
    feed(d, hold(3) + hold(3, smile=0.8))
    assert d.update(obs(10_000)).state is S.COMPLETED


# ---------------------------------------------------------------- neutral baseline requirement

@pytest.mark.parametrize("action, start", [
    (Action.SMILE, dict(smile=0.8)),          # photo of a smiling face
    (Action.OPEN_MOUTH, dict(jaw=0.7)),
    (Action.BLINK, dict(blink=0.9)),          # photo with closed eyes
])
def test_action_already_present_never_arms(action, start, thresholds):
    d = create_detector(action, STEP, thresholds)
    assert {u.state for u in feed(d, hold(50, **start))} == {S.WAITING_NEUTRAL}


def test_unsteady_head_delays_arming(thresholds):
    d = create_detector(Action.TURN_LEFT, STEP, thresholds)
    jitter = [dict(yaw=y) for y in (0, 6, 0, 6, 0, 6)]  # spread 6 > stability 3
    updates = feed(d, jitter)
    assert all(u.state is S.WAITING_NEUTRAL and u.hint is Hint.HOLD_STILL for u in updates)


def test_head_turn_is_relative_to_baseline(thresholds):
    """Someone whose resting yaw is already -10 deg still has to move 15 deg."""
    d = create_detector(Action.TURN_LEFT, STEP, thresholds)
    assert final(feed(d, hold(3, yaw=-10) + hold(5, yaw=4))) is S.IN_PROGRESS
    d.reset()
    assert final(feed(d, hold(3, yaw=-10) + hold(3, yaw=6))) is S.COMPLETED


# ---------------------------------------------------------------- insufficient / wrong actions

def test_single_frame_spike_is_not_enough(thresholds):
    d = create_detector(Action.SMILE, STEP, thresholds)
    updates = feed(d, hold(3) + hold(1, smile=0.9) + hold(5))
    assert final(updates) is S.IN_PROGRESS


@pytest.mark.parametrize("action, frames", [
    (Action.SMILE, hold(5, smile=0.45)),                     # below 0.5
    (Action.TURN_LEFT, hold(5, yaw=14)),                     # below 15 deg
    (Action.LOOK_UP, hold(5, pitch=9)),                      # below 10 deg
    (Action.NOD, hold(5, pitch=-15)),                        # went down, never came back
    (Action.BLINK, hold(5, blink=0.9)),                      # closed, never reopened
    (Action.GAZE_LEFT, hold(5, gaze_h=0.1)),                 # below 0.15
])
def test_insufficient_action_does_not_complete(action, frames, thresholds):
    d = create_detector(action, STEP, thresholds)
    assert final(feed(d, hold(3) + frames)) is S.IN_PROGRESS


@pytest.mark.parametrize("action, frames", [
    (Action.TURN_LEFT, hold(2, yaw=-20)),
    (Action.TURN_RIGHT, hold(2, yaw=20)),
    (Action.LOOK_UP, hold(2, pitch=-12)),
    (Action.LOOK_DOWN, hold(2, pitch=12)),
    (Action.GAZE_LEFT, hold(2, gaze_h=-0.3)),
    (Action.GAZE_UP, hold(2, gaze_down=0.7)),
])
def test_opposite_movement_is_wrong_action(action, frames, thresholds):
    d = create_detector(action, STEP, thresholds)
    assert final(feed(d, hold(3) + frames)) is S.WRONG_ACTION


def test_gaze_with_head_movement_does_not_count(thresholds):
    d = create_detector(Action.GAZE_LEFT, STEP, thresholds)
    updates = feed(d, hold(3) + hold(5, gaze_h=0.3, yaw=12))
    assert final(updates) is S.IN_PROGRESS
    assert updates[-1].hint is Hint.KEEP_HEAD_STILL


def test_gaze_down_with_closed_eyes_does_not_count(thresholds):
    d = create_detector(Action.GAZE_DOWN, STEP, thresholds)
    assert final(feed(d, hold(3) + hold(5, gaze_down=0.7, blink=0.8))) is S.IN_PROGRESS


# ---------------------------------------------------------------- stricter parameters

def test_larger_step_angle_requires_larger_turn(thresholds):
    easy = create_detector(Action.TURN_LEFT, StepParams(8, 15, 10), thresholds)
    hard = create_detector(Action.TURN_LEFT, StepParams(5, 25, 15), thresholds)
    frames = hold(3) + hold(4, yaw=20)
    assert final(feed(easy, frames)) is S.COMPLETED
    assert final(feed(hard, frames)) is S.IN_PROGRESS


def test_margin_reflects_how_clearly_the_action_passed(thresholds):
    weak = create_detector(Action.TURN_LEFT, STEP, thresholds)
    strong = create_detector(Action.TURN_LEFT, STEP, thresholds)
    w = feed(weak, hold(3) + hold(3, yaw=16))[-1]
    s = feed(strong, hold(3) + hold(3, yaw=30))[-1]
    assert w.state is s.state is S.COMPLETED
    assert w.margin == pytest.approx(1 / 15)
    assert s.margin == pytest.approx(1.0)


# ---------------------------------------------------------------- compound

def test_compound_requires_the_prompted_order(thresholds):
    d = create_challenge_detector((Action.TURN_LEFT, Action.BLINK), STEP, thresholds)
    assert isinstance(d, CompoundDetector)
    # blink first, then turn: the blink is ignored, so the second part is still pending
    frames = hold(3) + hold(2, blink=0.9) + hold(3) + hold(4, yaw=22)
    assert final(feed(d, frames)) is S.IN_PROGRESS
    d.reset()
    frames = hold(3) + hold(4, yaw=22) + hold(3, yaw=22) + hold(2, yaw=22, blink=0.9) + hold(1, yaw=22)
    updates = feed(d, frames)
    assert final(updates) is S.COMPLETED and updates[-1].progress == 1.0


def test_compound_fails_if_any_part_is_wrong(thresholds):
    d = create_challenge_detector((Action.SMILE, Action.TURN_RIGHT), STEP, thresholds)
    frames = hold(3) + hold(3, smile=0.8) + hold(3) + hold(2, yaw=20)
    assert final(feed(d, frames)) is S.WRONG_ACTION


def test_compound_margin_is_the_weakest_part(thresholds):
    d = create_challenge_detector((Action.SMILE, Action.TURN_LEFT), STEP, thresholds)
    frames = hold(3) + hold(3, smile=1.0) + hold(3) + hold(3, yaw=16)
    u = feed(d, frames)[-1]
    assert u.state is S.COMPLETED and u.margin == pytest.approx(1 / 15)
