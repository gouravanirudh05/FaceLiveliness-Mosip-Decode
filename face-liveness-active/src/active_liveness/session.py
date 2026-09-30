"""Active liveness session: challenge sequencing, timeouts, retries and escalation.

A session is driven entirely by the frames pushed into it; all timing uses the
frames' own timestamps, so behaviour is deterministic and testable.

    session = ActiveLivenessSession(policy, Workflow.RESIDENT, analyzer=analyzer,
                                    passive_score=0.42)
    events = session.start()
    for frame, ts in stream:
        events = session.process_frame(frame, ts)
        ...
        if session.status is SessionStatus.RETRY_AVAILABLE:
            events = session.retry()
"""

from __future__ import annotations

import json
import logging
import random
import uuid
from enum import Enum

import numpy as np

from .analyzer import AnalyzerError, FaceAnalyzer
from .challenges import Challenge, ChallengePlanner
from .config import LivenessPolicy
from .detectors import DetectorState, Hint, create_challenge_detector
from .events import (
    ENGINE_ERROR_MESSAGE, FEEDBACK_MESSAGES, MAX_RETRIES_MESSAGE, SUCCESS_MESSAGES,
    ChallengePrompt, ChallengeResult, Decision, DecisionStatus, Event, FailureReason,
    Feedback, FeedbackCode, RetryAvailable, SessionStarted,
)
from .types import Action, FaceObservation, Tier, Workflow

audit_log = logging.getLogger("active_liveness.audit")


class SessionStatus(Enum):
    NOT_STARTED = "not_started"
    RUNNING = "running"
    RETRY_AVAILABLE = "retry_available"
    PASSED = "passed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    DISABLED = "disabled"


TERMINAL = {SessionStatus.PASSED, SessionStatus.FAILED, SessionStatus.CANCELLED, SessionStatus.DISABLED}


class SessionStateError(RuntimeError):
    pass


class ActiveLivenessSession:
    def __init__(
        self,
        policy: LivenessPolicy,
        workflow: Workflow,
        *,
        analyzer: FaceAnalyzer | None = None,
        passive_score: float | None = None,
        rng: random.Random | None = None,
        session_id: str | None = None,
    ):
        if passive_score is not None and not 0.0 <= passive_score <= 1.0:
            raise ValueError("passive_score must be within [0, 1]")
        self.policy = policy
        self.workflow = workflow
        self.analyzer = analyzer
        self.passive_score = passive_score
        self.session_id = session_id or uuid.uuid4().hex
        self.planner = ChallengePlanner(policy, rng)
        self.status = SessionStatus.NOT_STARTED
        self.attempt_index = -1
        self.history: list[Challenge] = []   # every challenge issued, across attempts
        self._last_ts: int | None = None

    # ------------------------------------------------------------ public API

    def start(self) -> list[Event]:
        self._require(SessionStatus.NOT_STARTED)
        self._audit("session_started", passive_score=self.passive_score)
        started = SessionStarted(self.session_id, self.workflow, self.policy.max_attempts)
        if not self.policy.enabled:
            return [started, self._finish(SessionStatus.DISABLED, DecisionStatus.DISABLED,
                                          "Liveness verification is disabled", FailureReason.LIVENESS_DISABLED)]
        return [started, *self._begin_attempt(0)]

    def process_frame(self, rgb: np.ndarray, timestamp_ms: int) -> list[Event]:
        """Analyse an RGB frame with the configured analyzer and advance the session."""
        self._require(SessionStatus.RUNNING)
        if self.analyzer is None:
            raise SessionStateError("session has no analyzer; use process_observation")
        if not self._timestamp_ok(timestamp_ms):
            return [self._invalid_frame()]
        try:
            obs = self.analyzer.analyze(rgb, timestamp_ms)
        except AnalyzerError as e:
            self._audit("engine_error", error=str(e))
            return [self._finish(SessionStatus.FAILED, DecisionStatus.FAILED,
                                 ENGINE_ERROR_MESSAGE, FailureReason.ENGINE_ERROR)]
        return self.process_observation(obs)

    def process_observation(self, obs: FaceObservation) -> list[Event]:
        self._require(SessionStatus.RUNNING)
        if not self._timestamp_ok(obs.timestamp_ms):
            return [self._invalid_frame()]
        self._last_ts = obs.timestamp_ms

        if self._step_start_ms is None:
            self._step_start_ms = obs.timestamp_ms
        if obs.timestamp_ms - self._step_start_ms > self._timeout_ms:
            return self._fail_step(FailureReason.CHALLENGE_TIMEOUT)

        if obs.face_count != 1:
            self._invalid_run += 1
            if self._invalid_run > self.policy.thresholds.max_invalid_frames:
                self._detector.reset()
            code = FeedbackCode.FACE_NOT_DETECTED if obs.face_count == 0 else FeedbackCode.MULTIPLE_FACES
            return self._feedback(code, 0.0)
        self._invalid_run = 0

        u = self._detector.update(obs)
        if u.state is DetectorState.WRONG_ACTION:
            return self._fail_step(FailureReason.WRONG_ACTION)
        if u.state is DetectorState.COMPLETED:
            return self._complete_step(u.margin)
        if u.hint is Hint.HOLD_STILL:
            return self._feedback(FeedbackCode.HOLD_STILL, u.progress)
        if u.hint is Hint.KEEP_HEAD_STILL:
            return self._feedback(FeedbackCode.KEEP_HEAD_STILL, u.progress)
        return self._feedback(FeedbackCode.PLEASE_CONTINUE, u.progress)

    def retry(self) -> list[Event]:
        self._require(SessionStatus.RETRY_AVAILABLE)
        return self._begin_attempt(self.attempt_index + 1)

    def cancel(self) -> list[Event]:
        if self.status in TERMINAL:
            raise SessionStateError(f"session already finished ({self.status.value})")
        return [self._finish(SessionStatus.CANCELLED, DecisionStatus.CANCELLED,
                             "Face verification was cancelled", FailureReason.CANCELLED)]

    @property
    def current_challenge(self) -> Challenge | None:
        return self._challenge if self.status is SessionStatus.RUNNING else None

    @property
    def planned_tiers(self):
        return list(self._tiers)

    # ------------------------------------------------------------ internals

    def _begin_attempt(self, index: int) -> list[Event]:
        self.attempt_index = index
        self.status = SessionStatus.RUNNING
        self._tiers = self.planner.tiers_for_attempt(index, self.passive_score)
        self._extras = len(self._tiers) - self.policy.min_challenges
        self._used: set[Action] = set()
        self._step = 0
        self._audit("attempt_started", attempt=index + 1, tiers=[t.name for t in self._tiers])
        return [self._begin_step()]

    def _begin_step(self) -> ChallengePrompt:
        self._challenge = self.planner.pick(self._tiers[self._step], self._used)
        self._used.update(self._challenge.actions)
        self.history.append(self._challenge)
        params = self.policy.step_params(self._step)
        self._timeout_ms = int(params.timeout_s * 1000)
        self._detector = create_challenge_detector(self._challenge.actions, params, self.policy.thresholds)
        self._step_start_ms: int | None = None
        self._invalid_run = 0
        self._last_feedback: tuple | None = None
        prompt = ChallengePrompt(
            attempt=self.attempt_index + 1, step_index=self._step, total_steps=len(self._tiers),
            actions=self._challenge.actions, tier=self._challenge.tier,
            prompt=self._challenge.prompt, timeout_ms=self._timeout_ms,
        )
        self._audit("challenge_prompted", attempt=prompt.attempt, step=self._step,
                    actions=[a.value for a in prompt.actions], tier=prompt.tier.name,
                    timeout_ms=self._timeout_ms)
        return prompt

    def _complete_step(self, margin: float) -> list[Event]:
        result = ChallengeResult(self.attempt_index + 1, self._step, True, margin)
        self._audit("challenge_passed", attempt=result.attempt, step=self._step, margin=round(margin, 3))
        events: list[Event] = [
            Feedback(FeedbackCode.ACTION_DETECTED, FEEDBACK_MESSAGES[FeedbackCode.ACTION_DETECTED], 1.0),
            result,
        ]
        esc = self.policy.escalation
        if margin < esc.weak_margin and self._extras < esc.max_extra_challenges:
            self._tiers.append(Tier.HARD)
            self._extras += 1
            self._audit("escalated_weak_margin", attempt=result.attempt, step=self._step)
        self._step += 1
        if self._step < len(self._tiers):
            events.append(self._begin_step())
        else:
            events.append(self._finish(SessionStatus.PASSED, DecisionStatus.PASSED,
                                       SUCCESS_MESSAGES[self.workflow]))
        return events

    def _fail_step(self, reason: FailureReason) -> list[Event]:
        attempt = self.attempt_index + 1
        self._audit("challenge_failed", attempt=attempt, step=self._step, reason=reason.value)
        events: list[Event] = [ChallengeResult(attempt, self._step, False, reason=reason)]
        remaining = self.policy.max_attempts - attempt
        if remaining > 0:
            self.status = SessionStatus.RETRY_AVAILABLE
            events.append(RetryAvailable(attempt, remaining, reason))
        else:
            events.append(self._finish(SessionStatus.FAILED, DecisionStatus.FAILED,
                                       MAX_RETRIES_MESSAGE, FailureReason.MAX_RETRIES_EXCEEDED))
        return events

    def _finish(self, status: SessionStatus, decision: DecisionStatus, message: str,
                reason: FailureReason | None = None) -> Decision:
        self.status = status
        self._audit("decision", status=decision.value, reason=reason.value if reason else None,
                    attempts=self.attempt_index + 1)
        return Decision(decision, message, reason)

    def _feedback(self, code: FeedbackCode, progress: float) -> list[Event]:
        key = (code, round(progress, 1))
        if key == self._last_feedback:
            return []
        self._last_feedback = key
        return [Feedback(code, FEEDBACK_MESSAGES[code], progress)]

    def _invalid_frame(self) -> Feedback:
        return Feedback(FeedbackCode.INVALID_FRAME,
                        "Frame timestamps must be strictly increasing", 0.0)

    def _timestamp_ok(self, ts: int) -> bool:
        return self._last_ts is None or ts > self._last_ts

    def _require(self, status: SessionStatus) -> None:
        if self.status is not status:
            raise SessionStateError(f"expected session state {status.value}, got {self.status.value}")

    def _audit(self, event: str, **fields) -> None:
        audit_log.info(json.dumps({"event": event, "session_id": self.session_id,
                                   "workflow": self.workflow.value, **fields}))
