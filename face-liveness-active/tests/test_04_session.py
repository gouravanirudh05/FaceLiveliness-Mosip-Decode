"""End-to-end session behaviour on synthetic users: escalation, retries, attacks, errors."""

import random

import pytest

from active_liveness.analyzer import AnalyzerError
from active_liveness.events import (
    ChallengePrompt, ChallengeResult, Decision, DecisionStatus, FailureReason, Feedback,
    FeedbackCode, RetryAvailable, SessionStarted,
)
from active_liveness.session import ActiveLivenessSession, SessionStateError, SessionStatus
from active_liveness.types import Action, Tier, Workflow

from sim import Clock, SimulatedUser, StaticSubject, drive, obs, replace_policy, step_results

E, M, H = Tier.EASY, Tier.MEDIUM, Tier.HARD
STRONG = 0.9


def session(policy, passive=STRONG, seed=1, workflow=Workflow.RESIDENT, **kw):
    return ActiveLivenessSession(policy, workflow, passive_score=passive, rng=random.Random(seed), **kw)


# ================================================================ happy path

@pytest.mark.parametrize("seed", range(25))
def test_live_user_passes_and_sequence_gets_harder(policy, seed):
    tr = drive(session(policy, seed=seed), SimulatedUser())
    assert tr.decision.status is DecisionStatus.PASSED
    assert tr.decision.message == "Good, face captured successfully"
    tiers = [p.tier for p in tr.prompts]
    assert tiers == [E, M, H]
    timeouts = [p.timeout_ms for p in tr.prompts]
    assert timeouts == [8000, 6000, 5000]
    assert all(r.passed for r in tr.of(ChallengeResult))


def test_session_started_event_first(policy):
    events = session(policy).start()
    assert isinstance(events[0], SessionStarted) and events[0].max_attempts == 4
    assert isinstance(events[1], ChallengePrompt) and events[1].step_index == 0


@pytest.mark.parametrize("workflow, message", [
    (Workflow.OPERATOR, "Face verified successfully"),
    (Workflow.SUPERVISOR, "Face verified successfully"),
])
def test_authentication_workflows_use_same_mechanism(policy, workflow, message):
    tr = drive(session(policy, workflow=workflow), SimulatedUser())
    assert tr.decision.status is DecisionStatus.PASSED and tr.decision.message == message


def test_workflow_specific_policy(app_config):
    import dataclasses
    sup = dataclasses.replace(app_config.policy_for(Workflow.SUPERVISOR), min_challenges=5)
    tr = drive(session(sup, workflow=Workflow.SUPERVISOR), SimulatedUser())
    assert [p.tier for p in tr.prompts] == [E, M, H, H, H]
    assert tr.decision.status is DecisionStatus.PASSED


# ================================================================ stricter per step

def turn_only(policy):
    """Every step is a head turn, so the per-step angle is what is being tested."""
    return replace_policy(policy, challenge_pool=[Action.TURN_LEFT, Action.TURN_RIGHT],
                          compound_challenges=False, max_retries=0)


@pytest.mark.parametrize("amplitude, steps_passed, status", [
    (18, 1, DecisionStatus.FAILED),    # clears 15 deg, not 20
    (22, 2, DecisionStatus.FAILED),    # clears 20 deg, not 25
    (30, 3, DecisionStatus.PASSED),
])
def test_required_head_turn_grows_each_step(policy, amplitude, steps_passed, status):
    tr = drive(session(turn_only(policy)), SimulatedUser(yaw_deg=amplitude))
    assert sum(r.passed for r in tr.of(ChallengeResult)) == steps_passed
    assert tr.decision.status is status
    if status is DecisionStatus.FAILED:
        assert step_results(tr)[-1].reason is FailureReason.CHALLENGE_TIMEOUT


@pytest.mark.parametrize("delay_s, steps_passed", [
    # each action is detected 0.3-0.55s after the hesitation ends
    (4.0, 3),   # <= 4.55s: fits into 8s, 6s and 5s
    (5.0, 2),   # 5.3-5.55s: too slow for the 5s step
    (6.0, 1),   # 6.3-6.55s: too slow for the 6s step
    (8.0, 0),
])
def test_timeout_shrinks_each_step(policy, delay_s, steps_passed):
    # single actions only, so every step costs the user exactly one hesitation
    p = replace_policy(policy, max_retries=0, compound_challenges=False)
    user = SimulatedUser(extra_delay_frames=int(delay_s * 25))
    tr = drive(session(p), user)
    assert sum(r.passed for r in tr.of(ChallengeResult)) == steps_passed


# ================================================================ escalation on weakness

def test_weak_passive_score_adds_hard_step(policy):
    tr = drive(session(policy, passive=0.3), SimulatedUser())
    assert [p.tier for p in tr.prompts] == [E, M, H, H]
    assert tr.decision.status is DecisionStatus.PASSED


def test_missing_passive_score_is_treated_as_weak(policy):
    tr = drive(session(policy, passive=None), SimulatedUser())
    assert len(tr.prompts) == 4


def test_barely_passing_step_adds_hard_step(policy):
    p = turn_only(replace_policy(policy, max_retries=3))
    # 16 deg vs 15 deg required at step 0 => margin 0.067 < 0.15 => one extra step
    user = SimulatedUser(yaw_deg=16)
    s = session(p)
    tr_events = s.start()
    first = tr_events[-1]
    assert first.total_steps == 3
    tr = drive_from(s, user, tr_events)
    grown = [e.total_steps for e in tr if isinstance(e, ChallengePrompt)]
    assert grown[1] == 4


def test_margin_escalation_is_capped(policy):
    p = turn_only(replace_policy(policy, escalation__max_extra_challenges=2))
    # passive weak (1 extra) + every step barely passes => at most 1 more
    s = session(p, passive=0.1)
    tr = drive(s, SimulatedUser(yaw_deg=26))
    assert max(e.total_steps for e in tr.prompts) == 5


def drive_from(s, user, events):
    """Continue an already-started session with `user` (single attempt)."""
    clock = Clock()
    out = list(events)
    while s.status is SessionStatus.RUNNING:
        prompt = [e for e in out if isinstance(e, ChallengePrompt)][-1]
        frames = user.frames_for(prompt, s.policy.step_params(prompt.step_index))
        for f in frames + [{}] * 400:
            new = s.process_observation(obs(clock.next(), **f))
            out += new
            if any(isinstance(e, (ChallengePrompt, RetryAvailable, Decision)) for e in new):
                break
    return out


# ================================================================ retries

def test_retry_starts_harder_and_eventually_fails(policy):
    tr = drive(session(policy), SimulatedUser(extra_delay_frames=1000))   # never acts in time
    first_tiers = [p.tier for p in tr.prompts if p.step_index == 0]
    assert first_tiers == [E, M, H, H]                 # 4 attempts, each starting harder
    retries = tr.of(RetryAvailable)
    assert [r.retries_remaining for r in retries] == [3, 2, 1]
    assert retries[0].message == "We could not verify face liveness. Please try again."
    assert "Improve lighting." in retries[0].guidance
    assert tr.decision.status is DecisionStatus.FAILED
    assert tr.decision.reason is FailureReason.MAX_RETRIES_EXCEEDED


def test_user_can_succeed_on_retry(policy):
    class FailsFirstAttempt(SimulatedUser):
        def frames_for(self, prompt, step):
            if prompt.attempt == 1:
                return []          # does nothing -> timeout
            return super().frames_for(prompt, step)

    tr = drive(session(policy), FailsFirstAttempt())
    assert tr.decision.status is DecisionStatus.PASSED
    attempt2 = [p.tier for p in tr.prompts if p.attempt == 2]
    assert attempt2 == [M, H, H]


def test_no_retries_configured(policy):
    tr = drive(session(replace_policy(policy, max_retries=0)), SimulatedUser(extra_delay_frames=1000))
    assert not tr.of(RetryAvailable)
    assert tr.decision.reason is FailureReason.MAX_RETRIES_EXCEEDED


# ================================================================ attacks

def test_static_photo_never_passes(policy):
    tr = drive(session(policy), StaticSubject(signals=dict(smile=0.7)))
    assert tr.decision.status is DecisionStatus.FAILED
    assert not any(r.passed for r in tr.of(ChallengeResult))


def test_static_turned_face_never_passes(policy):
    tr = drive(session(turn_only(policy)), StaticSubject(signals=dict(yaw=30)))
    assert not any(r.passed for r in tr.of(ChallengeResult))


def test_blind_replay_doing_the_opposite_fails_immediately(policy):
    p = replace_policy(policy, challenge_pool=[Action.TURN_LEFT], compound_challenges=False, max_retries=0)
    tr = drive(session(p), SimulatedUser(wrong_direction=True))
    assert step_results(tr)[0].reason is FailureReason.WRONG_ACTION
    assert tr.decision.status is DecisionStatus.FAILED


# ================================================================ frame problems & feedback

def test_no_face_and_multiple_faces_feedback(policy):
    s = session(policy)
    s.start()
    c = Clock()
    assert s.process_observation(obs(c.next(), face_count=0))[0].code is FeedbackCode.FACE_NOT_DETECTED
    assert s.process_observation(obs(c.next(), face_count=2))[0].code is FeedbackCode.MULTIPLE_FACES
    assert s.process_observation(obs(c.next()))[0].code is FeedbackCode.HOLD_STILL


def test_losing_the_face_resets_progress(policy):
    p = replace_policy(policy, challenge_pool=[Action.SMILE], compound_challenges=False)
    s = session(p)
    s.start()
    c = Clock()
    for f in [{}] * 3 + [dict(smile=0.8)] * 2:          # armed, 2 of 3 hold frames done
        s.process_observation(obs(c.next(), **f))
    for _ in range(4):                                  # > max_invalid_frames (3)
        s.process_observation(obs(c.next(), face_count=0))
    ev = s.process_observation(obs(c.next(), smile=0.8))
    assert ev and ev[0].code is FeedbackCode.HOLD_STILL   # must re-establish the neutral baseline


def test_brief_face_loss_is_tolerated(policy):
    p = replace_policy(policy, challenge_pool=[Action.SMILE], compound_challenges=False)
    s = session(p)
    s.start()
    c = Clock()
    for f in [{}] * 3 + [dict(smile=0.8)] * 2:
        s.process_observation(obs(c.next(), **f))
    s.process_observation(obs(c.next(), face_count=0))
    ev = s.process_observation(obs(c.next(), smile=0.8))
    assert any(isinstance(e, ChallengeResult) and e.passed for e in ev)


def test_non_increasing_timestamp_is_rejected(policy):
    s = session(policy)
    s.start()
    s.process_observation(obs(1000))
    ev = s.process_observation(obs(1000))
    assert ev[0].code is FeedbackCode.INVALID_FRAME


def test_feedback_is_not_repeated_every_frame(policy):
    s = session(policy)
    s.start()
    c = Clock()
    emitted = [s.process_observation(obs(c.next(), face_count=0)) for _ in range(5)]
    assert sum(len(e) for e in emitted) == 1


def test_analyzer_error_fails_session(policy):
    class Broken:
        def analyze(self, rgb, ts):
            raise AnalyzerError("boom")

        def close(self):
            pass

    import numpy as np
    s = session(policy, analyzer=Broken())
    s.start()
    ev = s.process_frame(np.zeros((4, 4, 3), np.uint8), 40)
    assert ev[-1].status is DecisionStatus.FAILED and ev[-1].reason is FailureReason.ENGINE_ERROR
    assert "boom" not in ev[-1].message   # no engine internals shown to the user


# ================================================================ lifecycle

def test_disabled_policy(policy):
    s = session(replace_policy(policy, enabled=False))
    ev = s.start()
    assert ev[-1].status is DecisionStatus.DISABLED and s.status is SessionStatus.DISABLED


def test_cancel(policy):
    s = session(policy)
    s.start()
    assert s.cancel()[-1].status is DecisionStatus.CANCELLED
    with pytest.raises(SessionStateError):
        s.cancel()


def test_invalid_state_transitions(policy):
    s = session(policy)
    with pytest.raises(SessionStateError):
        s.process_observation(obs(40))
    s.start()
    with pytest.raises(SessionStateError):
        s.retry()
    with pytest.raises(SessionStateError):
        s.start()


def test_passive_score_range_checked(policy):
    with pytest.raises(ValueError):
        session(policy, passive=1.5)


def test_audit_log_has_no_biometric_payload(policy, caplog):
    caplog.set_level("INFO", logger="active_liveness.audit")
    drive(session(policy), SimulatedUser())
    events = [r.getMessage() for r in caplog.records]
    assert any('"event": "decision"' in m and '"passed"' in m for m in events)
    assert all("blendshape" not in m and "yaw" not in m for m in events)
