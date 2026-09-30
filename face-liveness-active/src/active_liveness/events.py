"""Events emitted by a session. The gRPC layer maps these 1:1 onto proto messages."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .types import Action, Tier, Workflow


class FeedbackCode(Enum):
    FACE_NOT_DETECTED = "face_not_detected"
    MULTIPLE_FACES = "multiple_faces"
    HOLD_STILL = "hold_still"
    KEEP_HEAD_STILL = "keep_head_still"
    PLEASE_CONTINUE = "please_continue"
    ACTION_DETECTED = "action_detected"
    INVALID_FRAME = "invalid_frame"


class FailureReason(Enum):
    CHALLENGE_TIMEOUT = "challenge_timeout"
    WRONG_ACTION = "wrong_action"
    MAX_RETRIES_EXCEEDED = "max_retries_exceeded"
    CANCELLED = "cancelled"
    ENGINE_ERROR = "engine_error"
    LIVENESS_DISABLED = "liveness_disabled"


class DecisionStatus(Enum):
    PASSED = "passed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    DISABLED = "disabled"      # liveness is switched off for this workflow by configuration


FEEDBACK_MESSAGES = {
    FeedbackCode.FACE_NOT_DETECTED: "Keep your face within the capture area",
    FeedbackCode.MULTIPLE_FACES: "Only one person should be in front of the camera",
    FeedbackCode.HOLD_STILL: "Hold still and look at the camera",
    FeedbackCode.KEEP_HEAD_STILL: "Keep your head still",
    FeedbackCode.PLEASE_CONTINUE: "Please continue",
    FeedbackCode.ACTION_DETECTED: "Action detected",
    FeedbackCode.INVALID_FRAME: "Invalid frame received",
}

RETRY_MESSAGE = "We could not verify face liveness. Please try again."
RETRY_GUIDANCE = (
    "Look directly at the camera.",
    "Ensure your face is clearly visible.",
    "Improve lighting.",
    "Keep your face within the capture area.",
    "Follow the prompted action.",
)
MAX_RETRIES_MESSAGE = ("Face verification could not be completed. "
                       "Please follow the applicable recovery process.")
ENGINE_ERROR_MESSAGE = "Face verification could not be completed. Please try again."
SUCCESS_MESSAGES = {
    Workflow.RESIDENT: "Good, face captured successfully",
    Workflow.OPERATOR: "Face verified successfully",
    Workflow.SUPERVISOR: "Face verified successfully",
}


@dataclass(frozen=True)
class SessionStarted:
    session_id: str
    workflow: Workflow
    max_attempts: int


@dataclass(frozen=True)
class ChallengePrompt:
    attempt: int                # 1-based
    step_index: int             # 0-based
    total_steps: int            # may grow if escalation adds a step
    actions: tuple[Action, ...]
    tier: Tier
    prompt: str
    timeout_ms: int


@dataclass(frozen=True)
class Feedback:
    code: FeedbackCode
    message: str
    progress: float


@dataclass(frozen=True)
class ChallengeResult:
    attempt: int
    step_index: int
    passed: bool
    margin: float = 0.0
    reason: FailureReason | None = None


@dataclass(frozen=True)
class RetryAvailable:
    attempt: int                # the attempt that just failed, 1-based
    retries_remaining: int
    reason: FailureReason
    message: str = RETRY_MESSAGE
    guidance: tuple[str, ...] = RETRY_GUIDANCE


@dataclass(frozen=True)
class Decision:
    status: DecisionStatus
    message: str
    reason: FailureReason | None = None


Event = SessionStarted | ChallengePrompt | Feedback | ChallengeResult | RetryAvailable | Decision
