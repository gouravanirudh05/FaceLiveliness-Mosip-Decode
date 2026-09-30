from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class Workflow(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    WORKFLOW_UNSPECIFIED: _ClassVar[Workflow]
    WORKFLOW_RESIDENT: _ClassVar[Workflow]
    WORKFLOW_OPERATOR: _ClassVar[Workflow]
    WORKFLOW_SUPERVISOR: _ClassVar[Workflow]

class FrameEncoding(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    FRAME_ENCODING_UNSPECIFIED: _ClassVar[FrameEncoding]
    FRAME_ENCODING_JPEG: _ClassVar[FrameEncoding]
    FRAME_ENCODING_PNG: _ClassVar[FrameEncoding]
    FRAME_ENCODING_RAW_RGB: _ClassVar[FrameEncoding]
    FRAME_ENCODING_RAW_BGR: _ClassVar[FrameEncoding]

class Tier(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    TIER_UNSPECIFIED: _ClassVar[Tier]
    TIER_EASY: _ClassVar[Tier]
    TIER_MEDIUM: _ClassVar[Tier]
    TIER_HARD: _ClassVar[Tier]

class Action(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    ACTION_UNSPECIFIED: _ClassVar[Action]
    ACTION_BLINK: _ClassVar[Action]
    ACTION_SMILE: _ClassVar[Action]
    ACTION_OPEN_MOUTH: _ClassVar[Action]
    ACTION_TURN_LEFT: _ClassVar[Action]
    ACTION_TURN_RIGHT: _ClassVar[Action]
    ACTION_LOOK_UP: _ClassVar[Action]
    ACTION_LOOK_DOWN: _ClassVar[Action]
    ACTION_NOD: _ClassVar[Action]
    ACTION_GAZE_LEFT: _ClassVar[Action]
    ACTION_GAZE_RIGHT: _ClassVar[Action]
    ACTION_GAZE_UP: _ClassVar[Action]
    ACTION_GAZE_DOWN: _ClassVar[Action]

class FeedbackCode(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    FEEDBACK_CODE_UNSPECIFIED: _ClassVar[FeedbackCode]
    FEEDBACK_FACE_NOT_DETECTED: _ClassVar[FeedbackCode]
    FEEDBACK_MULTIPLE_FACES: _ClassVar[FeedbackCode]
    FEEDBACK_HOLD_STILL: _ClassVar[FeedbackCode]
    FEEDBACK_KEEP_HEAD_STILL: _ClassVar[FeedbackCode]
    FEEDBACK_PLEASE_CONTINUE: _ClassVar[FeedbackCode]
    FEEDBACK_ACTION_DETECTED: _ClassVar[FeedbackCode]
    FEEDBACK_INVALID_FRAME: _ClassVar[FeedbackCode]

class FailureReason(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    FAILURE_REASON_UNSPECIFIED: _ClassVar[FailureReason]
    FAILURE_CHALLENGE_TIMEOUT: _ClassVar[FailureReason]
    FAILURE_WRONG_ACTION: _ClassVar[FailureReason]
    FAILURE_MAX_RETRIES_EXCEEDED: _ClassVar[FailureReason]
    FAILURE_CANCELLED: _ClassVar[FailureReason]
    FAILURE_ENGINE_ERROR: _ClassVar[FailureReason]
    FAILURE_LIVENESS_DISABLED: _ClassVar[FailureReason]

class DecisionStatus(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    DECISION_STATUS_UNSPECIFIED: _ClassVar[DecisionStatus]
    DECISION_PASSED: _ClassVar[DecisionStatus]
    DECISION_FAILED: _ClassVar[DecisionStatus]
    DECISION_CANCELLED: _ClassVar[DecisionStatus]
    DECISION_DISABLED: _ClassVar[DecisionStatus]

class ErrorCode(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    ERROR_CODE_UNSPECIFIED: _ClassVar[ErrorCode]
    ERROR_INVALID_REQUEST: _ClassVar[ErrorCode]
    ERROR_INVALID_FRAME: _ClassVar[ErrorCode]
WORKFLOW_UNSPECIFIED: Workflow
WORKFLOW_RESIDENT: Workflow
WORKFLOW_OPERATOR: Workflow
WORKFLOW_SUPERVISOR: Workflow
FRAME_ENCODING_UNSPECIFIED: FrameEncoding
FRAME_ENCODING_JPEG: FrameEncoding
FRAME_ENCODING_PNG: FrameEncoding
FRAME_ENCODING_RAW_RGB: FrameEncoding
FRAME_ENCODING_RAW_BGR: FrameEncoding
TIER_UNSPECIFIED: Tier
TIER_EASY: Tier
TIER_MEDIUM: Tier
TIER_HARD: Tier
ACTION_UNSPECIFIED: Action
ACTION_BLINK: Action
ACTION_SMILE: Action
ACTION_OPEN_MOUTH: Action
ACTION_TURN_LEFT: Action
ACTION_TURN_RIGHT: Action
ACTION_LOOK_UP: Action
ACTION_LOOK_DOWN: Action
ACTION_NOD: Action
ACTION_GAZE_LEFT: Action
ACTION_GAZE_RIGHT: Action
ACTION_GAZE_UP: Action
ACTION_GAZE_DOWN: Action
FEEDBACK_CODE_UNSPECIFIED: FeedbackCode
FEEDBACK_FACE_NOT_DETECTED: FeedbackCode
FEEDBACK_MULTIPLE_FACES: FeedbackCode
FEEDBACK_HOLD_STILL: FeedbackCode
FEEDBACK_KEEP_HEAD_STILL: FeedbackCode
FEEDBACK_PLEASE_CONTINUE: FeedbackCode
FEEDBACK_ACTION_DETECTED: FeedbackCode
FEEDBACK_INVALID_FRAME: FeedbackCode
FAILURE_REASON_UNSPECIFIED: FailureReason
FAILURE_CHALLENGE_TIMEOUT: FailureReason
FAILURE_WRONG_ACTION: FailureReason
FAILURE_MAX_RETRIES_EXCEEDED: FailureReason
FAILURE_CANCELLED: FailureReason
FAILURE_ENGINE_ERROR: FailureReason
FAILURE_LIVENESS_DISABLED: FailureReason
DECISION_STATUS_UNSPECIFIED: DecisionStatus
DECISION_PASSED: DecisionStatus
DECISION_FAILED: DecisionStatus
DECISION_CANCELLED: DecisionStatus
DECISION_DISABLED: DecisionStatus
ERROR_CODE_UNSPECIFIED: ErrorCode
ERROR_INVALID_REQUEST: ErrorCode
ERROR_INVALID_FRAME: ErrorCode

class StartSession(_message.Message):
    __slots__ = ("workflow", "passive_score")
    WORKFLOW_FIELD_NUMBER: _ClassVar[int]
    PASSIVE_SCORE_FIELD_NUMBER: _ClassVar[int]
    workflow: Workflow
    passive_score: float
    def __init__(self, workflow: _Optional[_Union[Workflow, str]] = ..., passive_score: _Optional[float] = ...) -> None: ...

class Frame(_message.Message):
    __slots__ = ("data", "encoding", "width", "height", "timestamp_ms")
    DATA_FIELD_NUMBER: _ClassVar[int]
    ENCODING_FIELD_NUMBER: _ClassVar[int]
    WIDTH_FIELD_NUMBER: _ClassVar[int]
    HEIGHT_FIELD_NUMBER: _ClassVar[int]
    TIMESTAMP_MS_FIELD_NUMBER: _ClassVar[int]
    data: bytes
    encoding: FrameEncoding
    width: int
    height: int
    timestamp_ms: int
    def __init__(self, data: _Optional[bytes] = ..., encoding: _Optional[_Union[FrameEncoding, str]] = ..., width: _Optional[int] = ..., height: _Optional[int] = ..., timestamp_ms: _Optional[int] = ...) -> None: ...

class Retry(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class Cancel(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class ClientMessage(_message.Message):
    __slots__ = ("start", "frame", "retry", "cancel")
    START_FIELD_NUMBER: _ClassVar[int]
    FRAME_FIELD_NUMBER: _ClassVar[int]
    RETRY_FIELD_NUMBER: _ClassVar[int]
    CANCEL_FIELD_NUMBER: _ClassVar[int]
    start: StartSession
    frame: Frame
    retry: Retry
    cancel: Cancel
    def __init__(self, start: _Optional[_Union[StartSession, _Mapping]] = ..., frame: _Optional[_Union[Frame, _Mapping]] = ..., retry: _Optional[_Union[Retry, _Mapping]] = ..., cancel: _Optional[_Union[Cancel, _Mapping]] = ...) -> None: ...

class SessionStarted(_message.Message):
    __slots__ = ("session_id", "workflow", "max_attempts")
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    WORKFLOW_FIELD_NUMBER: _ClassVar[int]
    MAX_ATTEMPTS_FIELD_NUMBER: _ClassVar[int]
    session_id: str
    workflow: Workflow
    max_attempts: int
    def __init__(self, session_id: _Optional[str] = ..., workflow: _Optional[_Union[Workflow, str]] = ..., max_attempts: _Optional[int] = ...) -> None: ...

class ChallengePrompt(_message.Message):
    __slots__ = ("attempt", "step_index", "total_steps", "actions", "tier", "prompt", "timeout_ms")
    ATTEMPT_FIELD_NUMBER: _ClassVar[int]
    STEP_INDEX_FIELD_NUMBER: _ClassVar[int]
    TOTAL_STEPS_FIELD_NUMBER: _ClassVar[int]
    ACTIONS_FIELD_NUMBER: _ClassVar[int]
    TIER_FIELD_NUMBER: _ClassVar[int]
    PROMPT_FIELD_NUMBER: _ClassVar[int]
    TIMEOUT_MS_FIELD_NUMBER: _ClassVar[int]
    attempt: int
    step_index: int
    total_steps: int
    actions: _containers.RepeatedScalarFieldContainer[Action]
    tier: Tier
    prompt: str
    timeout_ms: int
    def __init__(self, attempt: _Optional[int] = ..., step_index: _Optional[int] = ..., total_steps: _Optional[int] = ..., actions: _Optional[_Iterable[_Union[Action, str]]] = ..., tier: _Optional[_Union[Tier, str]] = ..., prompt: _Optional[str] = ..., timeout_ms: _Optional[int] = ...) -> None: ...

class Feedback(_message.Message):
    __slots__ = ("code", "message", "progress")
    CODE_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    PROGRESS_FIELD_NUMBER: _ClassVar[int]
    code: FeedbackCode
    message: str
    progress: float
    def __init__(self, code: _Optional[_Union[FeedbackCode, str]] = ..., message: _Optional[str] = ..., progress: _Optional[float] = ...) -> None: ...

class ChallengeResult(_message.Message):
    __slots__ = ("attempt", "step_index", "passed", "margin", "reason")
    ATTEMPT_FIELD_NUMBER: _ClassVar[int]
    STEP_INDEX_FIELD_NUMBER: _ClassVar[int]
    PASSED_FIELD_NUMBER: _ClassVar[int]
    MARGIN_FIELD_NUMBER: _ClassVar[int]
    REASON_FIELD_NUMBER: _ClassVar[int]
    attempt: int
    step_index: int
    passed: bool
    margin: float
    reason: FailureReason
    def __init__(self, attempt: _Optional[int] = ..., step_index: _Optional[int] = ..., passed: _Optional[bool] = ..., margin: _Optional[float] = ..., reason: _Optional[_Union[FailureReason, str]] = ...) -> None: ...

class RetryAvailable(_message.Message):
    __slots__ = ("attempt", "retries_remaining", "reason", "message", "guidance")
    ATTEMPT_FIELD_NUMBER: _ClassVar[int]
    RETRIES_REMAINING_FIELD_NUMBER: _ClassVar[int]
    REASON_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    GUIDANCE_FIELD_NUMBER: _ClassVar[int]
    attempt: int
    retries_remaining: int
    reason: FailureReason
    message: str
    guidance: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, attempt: _Optional[int] = ..., retries_remaining: _Optional[int] = ..., reason: _Optional[_Union[FailureReason, str]] = ..., message: _Optional[str] = ..., guidance: _Optional[_Iterable[str]] = ...) -> None: ...

class Decision(_message.Message):
    __slots__ = ("status", "reason", "message")
    STATUS_FIELD_NUMBER: _ClassVar[int]
    REASON_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    status: DecisionStatus
    reason: FailureReason
    message: str
    def __init__(self, status: _Optional[_Union[DecisionStatus, str]] = ..., reason: _Optional[_Union[FailureReason, str]] = ..., message: _Optional[str] = ...) -> None: ...

class Error(_message.Message):
    __slots__ = ("code", "message")
    CODE_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    code: ErrorCode
    message: str
    def __init__(self, code: _Optional[_Union[ErrorCode, str]] = ..., message: _Optional[str] = ...) -> None: ...

class ServerMessage(_message.Message):
    __slots__ = ("session_started", "challenge_prompt", "feedback", "challenge_result", "retry_available", "decision", "error")
    SESSION_STARTED_FIELD_NUMBER: _ClassVar[int]
    CHALLENGE_PROMPT_FIELD_NUMBER: _ClassVar[int]
    FEEDBACK_FIELD_NUMBER: _ClassVar[int]
    CHALLENGE_RESULT_FIELD_NUMBER: _ClassVar[int]
    RETRY_AVAILABLE_FIELD_NUMBER: _ClassVar[int]
    DECISION_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    session_started: SessionStarted
    challenge_prompt: ChallengePrompt
    feedback: Feedback
    challenge_result: ChallengeResult
    retry_available: RetryAvailable
    decision: Decision
    error: Error
    def __init__(self, session_started: _Optional[_Union[SessionStarted, _Mapping]] = ..., challenge_prompt: _Optional[_Union[ChallengePrompt, _Mapping]] = ..., feedback: _Optional[_Union[Feedback, _Mapping]] = ..., challenge_result: _Optional[_Union[ChallengeResult, _Mapping]] = ..., retry_available: _Optional[_Union[RetryAvailable, _Mapping]] = ..., decision: _Optional[_Union[Decision, _Mapping]] = ..., error: _Optional[_Union[Error, _Mapping]] = ...) -> None: ...
