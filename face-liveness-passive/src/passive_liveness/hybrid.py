"""Hybrid liveness: passive PAD first, active challenge-response only when needed.

    passive frames --> StreamResult
        ATTACK        -> FAILED  (attack_detected)        no challenges are shown
        BONAFIDE      -> PASSED  (passive_bonafide)
        UNCERTAIN     -> active session with passive_score = bona fide probability
        NON_RESPONSE  -> active session without a passive score (hybrid.on_passive_no_response
                         = active; the active module then treats the score as weak and adds a
                         hard challenge) or FAILED (= fail)
    active session --> PASSED / FAILED / CANCELLED, mapped onto the hybrid decision.

While challenges run, PAD keeps sampling frames (``hybrid.monitor_*``); consecutive
ATTACK frames end the session as FAILED (attack_detected_during_active).

Messages shown to the user never say that an attack was detected.
"""

from __future__ import annotations

import enum
import json
import logging
import random
import uuid
from dataclasses import dataclass
from typing import Any, Callable

import numpy as np

from .engine import PassiveLivenessEngine, PassiveStream
from .types import Decision, FrameAnalysis, StreamResult

try:
    from active_liveness import ActiveLivenessSession, AppConfig, SessionStatus, Workflow
    from active_liveness.analyzer import FaceAnalyzer, MediaPipeFaceAnalyzer
    from active_liveness.events import (
        MAX_RETRIES_MESSAGE, SUCCESS_MESSAGES, Decision as ActiveDecision, DecisionStatus as ActiveStatus,
        Event as ActiveEventType,
    )
except ImportError as e:  # pragma: no cover - exercised only without the optional dependency
    raise ImportError("the hybrid flow needs the active-liveness package "
                      "(pip install -e ../face-liveness-active)") from e

audit_log = logging.getLogger("passive_liveness.audit")


class HybridStatus(enum.Enum):
    NOT_STARTED = "not_started"
    PASSIVE = "passive"
    ACTIVE = "active"
    PASSED = "passed"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL = {HybridStatus.PASSED, HybridStatus.FAILED, HybridStatus.CANCELLED}


class HybridReason(enum.Enum):
    PASSIVE_BONAFIDE = "passive_bonafide"
    ATTACK_DETECTED = "attack_detected"
    ATTACK_DETECTED_DURING_ACTIVE = "attack_detected_during_active"
    PASSIVE_NO_RESPONSE = "passive_no_response"
    ACTIVE_PASSED = "active_passed"
    ACTIVE_FAILED = "active_failed"
    ACTIVE_DISABLED = "active_disabled"          # passive inconclusive but challenges are switched off
    CANCELLED = "cancelled"


class NextStep(enum.Enum):
    ACCEPT = "accept"
    REJECT = "reject"
    ACTIVE = "active"


@dataclass(frozen=True)
class HybridStarted:
    session_id: str
    workflow: Workflow
    frames_required: int


@dataclass(frozen=True)
class PassiveProgress:
    frames_used: int
    frames_required: int
    frame: FrameAnalysis


@dataclass(frozen=True)
class PassiveVerdict:
    result: StreamResult
    next_step: NextStep


@dataclass(frozen=True)
class ActiveEvent:
    event: ActiveEventType            # an active_liveness event, forwarded unchanged


@dataclass(frozen=True)
class MonitorResult:
    frame: FrameAnalysis
    consecutive_attacks: int


@dataclass(frozen=True)
class HybridDecision:
    status: HybridStatus
    reason: HybridReason
    message: str
    passive_score: float | None
    active_status: str | None


HybridEvent = HybridStarted | PassiveProgress | PassiveVerdict | ActiveEvent | MonitorResult | HybridDecision

FAILED_MESSAGE = MAX_RETRIES_MESSAGE
CANCELLED_MESSAGE = "Face verification was cancelled"


class HybridLivenessSession:
    def __init__(
        self,
        engine: PassiveLivenessEngine,
        active_config: AppConfig,
        workflow: Workflow,
        *,
        active_analyzer_factory: Callable[[], FaceAnalyzer] | None = None,
        rng: random.Random | None = None,
        session_id: str | None = None,
    ):
        self.engine = engine
        self.cfg = engine.config.hybrid
        self.active_config = active_config
        self.workflow = workflow
        self.session_id = session_id or uuid.uuid4().hex
        self._rng = rng
        svc = active_config.service
        self._analyzer_factory = active_analyzer_factory or (lambda: MediaPipeFaceAnalyzer(
            svc.model_path, max_faces=svc.max_faces, mirrored=svc.input_mirrored))
        self.status = HybridStatus.NOT_STARTED
        self.passive_result: StreamResult | None = None
        self.active: ActiveLivenessSession | None = None
        self.decision: HybridDecision | None = None
        self._stream: PassiveStream | None = None
        self._analyzer: FaceAnalyzer | None = None
        self._last_monitor_ts: int | None = None
        self._attack_run = 0

    # ------------------------------------------------------------ public API

    def start(self) -> list[HybridEvent]:
        self._require(HybridStatus.NOT_STARTED)
        self._stream = self.engine.open_stream(include_frames=False)
        self.status = HybridStatus.PASSIVE
        self._audit("hybrid_started")
        return [HybridStarted(self.session_id, self.workflow, self._stream.frames_required)]

    def process_frame(self, rgb: np.ndarray, timestamp_ms: int) -> list[HybridEvent]:
        if self.status is HybridStatus.PASSIVE:
            return self._passive_frame(rgb, timestamp_ms)
        if self.status is HybridStatus.ACTIVE:
            return self._active_frame(rgb, timestamp_ms)
        raise RuntimeError(f"session is not accepting frames ({self.status.value})")

    def retry(self) -> list[HybridEvent]:
        if self.status is not HybridStatus.ACTIVE or self.active.status is not SessionStatus.RETRY_AVAILABLE:
            raise RuntimeError("no retry is available")
        return [ActiveEvent(e) for e in self.active.retry()]

    def cancel(self) -> list[HybridEvent]:
        if self.status in TERMINAL or self.status is HybridStatus.NOT_STARTED:
            raise RuntimeError(f"session cannot be cancelled ({self.status.value})")
        events: list[HybridEvent] = []
        if self.status is HybridStatus.ACTIVE and self.active.status not in (
                SessionStatus.PASSED, SessionStatus.FAILED, SessionStatus.CANCELLED, SessionStatus.DISABLED):
            events += [ActiveEvent(e) for e in self.active.cancel()]
        events.append(self._finish(HybridStatus.CANCELLED, HybridReason.CANCELLED, CANCELLED_MESSAGE))
        return events

    @property
    def retry_available(self) -> bool:
        return (self.status is HybridStatus.ACTIVE and self.active is not None
                and self.active.status is SessionStatus.RETRY_AVAILABLE)

    def close(self) -> None:
        if self._stream is not None:
            self._stream.close()
            self._stream = None
        if self._analyzer is not None:
            self._analyzer.close()
            self._analyzer = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # ------------------------------------------------------------ passive phase

    def _passive_frame(self, rgb, ts) -> list[HybridEvent]:
        events: list[HybridEvent] = []
        fa = self._stream.push(rgb, ts)
        if fa is not None:
            events.append(PassiveProgress(self._stream.frames_used, self._stream.frames_required, fa))
        if not self._stream.done:
            return events
        result = self._stream.result()
        self.passive_result = result
        score = result.bonafide_probability
        if result.decision is Decision.ATTACK:
            events.append(PassiveVerdict(result, NextStep.REJECT))
            events.append(self._finish(HybridStatus.FAILED, HybridReason.ATTACK_DETECTED, FAILED_MESSAGE))
        elif result.decision is Decision.BONAFIDE:
            events.append(PassiveVerdict(result, NextStep.ACCEPT))
            events.append(self._finish(HybridStatus.PASSED, HybridReason.PASSIVE_BONAFIDE,
                                       SUCCESS_MESSAGES[self.workflow]))
        elif result.decision is Decision.NON_RESPONSE and self.cfg.on_passive_no_response == "fail":
            events.append(PassiveVerdict(result, NextStep.REJECT))
            events.append(self._finish(HybridStatus.FAILED, HybridReason.PASSIVE_NO_RESPONSE, FAILED_MESSAGE))
        else:
            events.append(PassiveVerdict(result, NextStep.ACTIVE))
            events += self._start_active(score if result.decision is Decision.UNCERTAIN else None)
        return events

    # ------------------------------------------------------------ active phase

    def _start_active(self, passive_score: float | None) -> list[HybridEvent]:
        policy = self.active_config.policy_for(self.workflow)
        if not policy.enabled:
            return [self._finish(HybridStatus.FAILED, HybridReason.ACTIVE_DISABLED, FAILED_MESSAGE)]
        self._analyzer = self._analyzer_factory()
        self.active = ActiveLivenessSession(policy, self.workflow, analyzer=self._analyzer,
                                            passive_score=passive_score, rng=self._rng,
                                            session_id=self.session_id)
        self.status = HybridStatus.ACTIVE
        self._audit("active_started", passive_score=passive_score)
        return [ActiveEvent(e) for e in self.active.start()]

    def _active_frame(self, rgb, ts) -> list[HybridEvent]:
        events: list[HybridEvent] = []
        if self.cfg.monitor_during_active and (
                self._last_monitor_ts is None or ts - self._last_monitor_ts >= self.cfg.monitor_interval_ms):
            fa = self._stream.probe(rgb, ts)
            if fa is not None:
                self._last_monitor_ts = ts
                self._attack_run = self._attack_run + 1 if fa.decision is Decision.ATTACK else 0
                events.append(MonitorResult(fa, self._attack_run))
                if self._attack_run >= self.cfg.monitor_attack_frames:
                    events.append(self._finish(HybridStatus.FAILED, HybridReason.ATTACK_DETECTED_DURING_ACTIVE,
                                               FAILED_MESSAGE))
                    return events
        if self.active.status is not SessionStatus.RUNNING:
            return events                                  # waiting for retry(); frames are ignored
        for e in self.active.process_frame(rgb, ts):
            events.append(ActiveEvent(e))
            if isinstance(e, ActiveDecision):
                events.append(self._from_active(e))
        return events

    def _from_active(self, d: ActiveDecision) -> HybridDecision:
        if d.status is ActiveStatus.PASSED:
            return self._finish(HybridStatus.PASSED, HybridReason.ACTIVE_PASSED, d.message)
        if d.status is ActiveStatus.CANCELLED:
            return self._finish(HybridStatus.CANCELLED, HybridReason.CANCELLED, d.message)
        if d.status is ActiveStatus.DISABLED:
            return self._finish(HybridStatus.FAILED, HybridReason.ACTIVE_DISABLED, FAILED_MESSAGE)
        return self._finish(HybridStatus.FAILED, HybridReason.ACTIVE_FAILED, d.message)

    # ------------------------------------------------------------ helpers

    def _finish(self, status: HybridStatus, reason: HybridReason, message: str) -> HybridDecision:
        self.status = status
        self.decision = HybridDecision(
            status=status, reason=reason, message=message,
            passive_score=self.passive_result.bonafide_probability if self.passive_result else None,
            active_status=self.active.status.value if self.active else None)
        self._audit("hybrid_decision", status=status.value, reason=reason.value,
                    passive_score=self.decision.passive_score, active_status=self.decision.active_status)
        self.close()
        return self.decision

    def _require(self, status: HybridStatus) -> None:
        if self.status is not status:
            raise RuntimeError(f"expected {status.value}, session is {self.status.value}")

    def _audit(self, event: str, **fields: Any) -> None:
        audit_log.info(json.dumps({"event": event, "session_id": self.session_id,
                                   "workflow": self.workflow.value, **fields}))
