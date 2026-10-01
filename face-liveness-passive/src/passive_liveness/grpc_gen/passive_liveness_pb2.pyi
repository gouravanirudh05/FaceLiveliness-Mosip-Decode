from active_liveness.grpc_gen import active_liveness_pb2 as _active_liveness_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class Decision(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    DECISION_UNSPECIFIED: _ClassVar[Decision]
    DECISION_BONAFIDE: _ClassVar[Decision]
    DECISION_ATTACK: _ClassVar[Decision]
    DECISION_UNCERTAIN: _ClassVar[Decision]
    DECISION_NON_RESPONSE: _ClassVar[Decision]

class AttackCategory(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    ATTACK_CATEGORY_UNSPECIFIED: _ClassVar[AttackCategory]
    ATTACK_CATEGORY_NONE: _ClassVar[AttackCategory]
    ATTACK_CATEGORY_PRESENTATION_ATTACK: _ClassVar[AttackCategory]
    ATTACK_CATEGORY_DEEPFAKE: _ClassVar[AttackCategory]
    ATTACK_CATEGORY_SYNTHETIC: _ClassVar[AttackCategory]

class PAISpecies(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    PAI_SPECIES_UNSPECIFIED: _ClassVar[PAISpecies]
    PAI_SPECIES_NONE: _ClassVar[PAISpecies]
    PAI_SPECIES_PRINT: _ClassVar[PAISpecies]
    PAI_SPECIES_SCREEN_REPLAY: _ClassVar[PAISpecies]
    PAI_SPECIES_UNKNOWN: _ClassVar[PAISpecies]

class NonResponseReason(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    NON_RESPONSE_REASON_UNSPECIFIED: _ClassVar[NonResponseReason]
    NON_RESPONSE_NO_FACE: _ClassVar[NonResponseReason]
    NON_RESPONSE_MULTIPLE_FACES: _ClassVar[NonResponseReason]
    NON_RESPONSE_FACE_TOO_SMALL: _ClassVar[NonResponseReason]
    NON_RESPONSE_TOO_BLURRY: _ClassVar[NonResponseReason]
    NON_RESPONSE_TOO_DARK: _ClassVar[NonResponseReason]
    NON_RESPONSE_TOO_BRIGHT: _ClassVar[NonResponseReason]
    NON_RESPONSE_POSE_OUT_OF_RANGE: _ClassVar[NonResponseReason]
    NON_RESPONSE_FACE_CUT_OFF: _ClassVar[NonResponseReason]
    NON_RESPONSE_INSUFFICIENT_FRAMES: _ClassVar[NonResponseReason]
    NON_RESPONSE_DECODE_ERROR: _ClassVar[NonResponseReason]

class ErrorCode(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    ERROR_CODE_UNSPECIFIED: _ClassVar[ErrorCode]
    ERROR_INVALID_REQUEST: _ClassVar[ErrorCode]
    ERROR_INVALID_FRAME: _ClassVar[ErrorCode]
    ERROR_INTERNAL: _ClassVar[ErrorCode]

class HybridStatus(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    HYBRID_STATUS_UNSPECIFIED: _ClassVar[HybridStatus]
    HYBRID_PASSED: _ClassVar[HybridStatus]
    HYBRID_FAILED: _ClassVar[HybridStatus]
    HYBRID_CANCELLED: _ClassVar[HybridStatus]

class HybridReason(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    HYBRID_REASON_UNSPECIFIED: _ClassVar[HybridReason]
    HYBRID_REASON_PASSIVE_BONAFIDE: _ClassVar[HybridReason]
    HYBRID_REASON_ATTACK_DETECTED: _ClassVar[HybridReason]
    HYBRID_REASON_ATTACK_DETECTED_DURING_ACTIVE: _ClassVar[HybridReason]
    HYBRID_REASON_PASSIVE_NO_RESPONSE: _ClassVar[HybridReason]
    HYBRID_REASON_ACTIVE_PASSED: _ClassVar[HybridReason]
    HYBRID_REASON_ACTIVE_FAILED: _ClassVar[HybridReason]
    HYBRID_REASON_ACTIVE_DISABLED: _ClassVar[HybridReason]
    HYBRID_REASON_CANCELLED: _ClassVar[HybridReason]

class NextStep(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    NEXT_STEP_UNSPECIFIED: _ClassVar[NextStep]
    NEXT_STEP_ACCEPT: _ClassVar[NextStep]
    NEXT_STEP_REJECT: _ClassVar[NextStep]
    NEXT_STEP_ACTIVE: _ClassVar[NextStep]
DECISION_UNSPECIFIED: Decision
DECISION_BONAFIDE: Decision
DECISION_ATTACK: Decision
DECISION_UNCERTAIN: Decision
DECISION_NON_RESPONSE: Decision
ATTACK_CATEGORY_UNSPECIFIED: AttackCategory
ATTACK_CATEGORY_NONE: AttackCategory
ATTACK_CATEGORY_PRESENTATION_ATTACK: AttackCategory
ATTACK_CATEGORY_DEEPFAKE: AttackCategory
ATTACK_CATEGORY_SYNTHETIC: AttackCategory
PAI_SPECIES_UNSPECIFIED: PAISpecies
PAI_SPECIES_NONE: PAISpecies
PAI_SPECIES_PRINT: PAISpecies
PAI_SPECIES_SCREEN_REPLAY: PAISpecies
PAI_SPECIES_UNKNOWN: PAISpecies
NON_RESPONSE_REASON_UNSPECIFIED: NonResponseReason
NON_RESPONSE_NO_FACE: NonResponseReason
NON_RESPONSE_MULTIPLE_FACES: NonResponseReason
NON_RESPONSE_FACE_TOO_SMALL: NonResponseReason
NON_RESPONSE_TOO_BLURRY: NonResponseReason
NON_RESPONSE_TOO_DARK: NonResponseReason
NON_RESPONSE_TOO_BRIGHT: NonResponseReason
NON_RESPONSE_POSE_OUT_OF_RANGE: NonResponseReason
NON_RESPONSE_FACE_CUT_OFF: NonResponseReason
NON_RESPONSE_INSUFFICIENT_FRAMES: NonResponseReason
NON_RESPONSE_DECODE_ERROR: NonResponseReason
ERROR_CODE_UNSPECIFIED: ErrorCode
ERROR_INVALID_REQUEST: ErrorCode
ERROR_INVALID_FRAME: ErrorCode
ERROR_INTERNAL: ErrorCode
HYBRID_STATUS_UNSPECIFIED: HybridStatus
HYBRID_PASSED: HybridStatus
HYBRID_FAILED: HybridStatus
HYBRID_CANCELLED: HybridStatus
HYBRID_REASON_UNSPECIFIED: HybridReason
HYBRID_REASON_PASSIVE_BONAFIDE: HybridReason
HYBRID_REASON_ATTACK_DETECTED: HybridReason
HYBRID_REASON_ATTACK_DETECTED_DURING_ACTIVE: HybridReason
HYBRID_REASON_PASSIVE_NO_RESPONSE: HybridReason
HYBRID_REASON_ACTIVE_PASSED: HybridReason
HYBRID_REASON_ACTIVE_FAILED: HybridReason
HYBRID_REASON_ACTIVE_DISABLED: HybridReason
HYBRID_REASON_CANCELLED: HybridReason
NEXT_STEP_UNSPECIFIED: NextStep
NEXT_STEP_ACCEPT: NextStep
NEXT_STEP_REJECT: NextStep
NEXT_STEP_ACTIVE: NextStep

class Box(_message.Message):
    __slots__ = ("x0", "y0", "x1", "y1")
    X0_FIELD_NUMBER: _ClassVar[int]
    Y0_FIELD_NUMBER: _ClassVar[int]
    X1_FIELD_NUMBER: _ClassVar[int]
    Y1_FIELD_NUMBER: _ClassVar[int]
    x0: int
    y0: int
    x1: int
    y1: int
    def __init__(self, x0: _Optional[int] = ..., y0: _Optional[int] = ..., x1: _Optional[int] = ..., y1: _Optional[int] = ...) -> None: ...

class FaceInfo(_message.Message):
    __slots__ = ("count", "box", "crop_box", "crop_clip", "yaw_deg", "pitch_deg", "roll_deg", "eye_blink", "all_boxes")
    COUNT_FIELD_NUMBER: _ClassVar[int]
    BOX_FIELD_NUMBER: _ClassVar[int]
    CROP_BOX_FIELD_NUMBER: _ClassVar[int]
    CROP_CLIP_FIELD_NUMBER: _ClassVar[int]
    YAW_DEG_FIELD_NUMBER: _ClassVar[int]
    PITCH_DEG_FIELD_NUMBER: _ClassVar[int]
    ROLL_DEG_FIELD_NUMBER: _ClassVar[int]
    EYE_BLINK_FIELD_NUMBER: _ClassVar[int]
    ALL_BOXES_FIELD_NUMBER: _ClassVar[int]
    count: int
    box: Box
    crop_box: Box
    crop_clip: float
    yaw_deg: float
    pitch_deg: float
    roll_deg: float
    eye_blink: float
    all_boxes: _containers.RepeatedCompositeFieldContainer[Box]
    def __init__(self, count: _Optional[int] = ..., box: _Optional[_Union[Box, _Mapping]] = ..., crop_box: _Optional[_Union[Box, _Mapping]] = ..., crop_clip: _Optional[float] = ..., yaw_deg: _Optional[float] = ..., pitch_deg: _Optional[float] = ..., roll_deg: _Optional[float] = ..., eye_blink: _Optional[float] = ..., all_boxes: _Optional[_Iterable[_Union[Box, _Mapping]]] = ...) -> None: ...

class Quality(_message.Message):
    __slots__ = ("passed", "reasons", "face_px", "sharpness", "brightness", "contrast")
    PASSED_FIELD_NUMBER: _ClassVar[int]
    REASONS_FIELD_NUMBER: _ClassVar[int]
    FACE_PX_FIELD_NUMBER: _ClassVar[int]
    SHARPNESS_FIELD_NUMBER: _ClassVar[int]
    BRIGHTNESS_FIELD_NUMBER: _ClassVar[int]
    CONTRAST_FIELD_NUMBER: _ClassVar[int]
    passed: bool
    reasons: _containers.RepeatedScalarFieldContainer[NonResponseReason]
    face_px: float
    sharpness: float
    brightness: float
    contrast: float
    def __init__(self, passed: _Optional[bool] = ..., reasons: _Optional[_Iterable[_Union[NonResponseReason, str]]] = ..., face_px: _Optional[float] = ..., sharpness: _Optional[float] = ..., brightness: _Optional[float] = ..., contrast: _Optional[float] = ...) -> None: ...

class ModelOutput(_message.Message):
    __slots__ = ("name", "probabilities", "logits", "labels", "bonafide_probability", "inference_ms")
    class ProbabilitiesEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: float
        def __init__(self, key: _Optional[str] = ..., value: _Optional[float] = ...) -> None: ...
    NAME_FIELD_NUMBER: _ClassVar[int]
    PROBABILITIES_FIELD_NUMBER: _ClassVar[int]
    LOGITS_FIELD_NUMBER: _ClassVar[int]
    LABELS_FIELD_NUMBER: _ClassVar[int]
    BONAFIDE_PROBABILITY_FIELD_NUMBER: _ClassVar[int]
    INFERENCE_MS_FIELD_NUMBER: _ClassVar[int]
    name: str
    probabilities: _containers.ScalarMap[str, float]
    logits: _containers.RepeatedScalarFieldContainer[float]
    labels: _containers.RepeatedScalarFieldContainer[str]
    bonafide_probability: float
    inference_ms: float
    def __init__(self, name: _Optional[str] = ..., probabilities: _Optional[_Mapping[str, float]] = ..., logits: _Optional[_Iterable[float]] = ..., labels: _Optional[_Iterable[str]] = ..., bonafide_probability: _Optional[float] = ..., inference_ms: _Optional[float] = ...) -> None: ...

class Cues(_message.Message):
    __slots__ = ("values", "indicators", "evidence")
    class ValuesEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: float
        def __init__(self, key: _Optional[str] = ..., value: _Optional[float] = ...) -> None: ...
    class IndicatorsEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: float
        def __init__(self, key: _Optional[str] = ..., value: _Optional[float] = ...) -> None: ...
    VALUES_FIELD_NUMBER: _ClassVar[int]
    INDICATORS_FIELD_NUMBER: _ClassVar[int]
    EVIDENCE_FIELD_NUMBER: _ClassVar[int]
    values: _containers.ScalarMap[str, float]
    indicators: _containers.ScalarMap[str, float]
    evidence: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, values: _Optional[_Mapping[str, float]] = ..., indicators: _Optional[_Mapping[str, float]] = ..., evidence: _Optional[_Iterable[str]] = ...) -> None: ...

class FrameAnalysis(_message.Message):
    __slots__ = ("timestamp_ms", "decision", "bonafide_probability", "attack_detected", "categories", "attack_category", "suspected_pai_species", "face", "quality", "models", "cues", "timings_ms", "heatmap_png", "json")
    class CategoriesEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: float
        def __init__(self, key: _Optional[str] = ..., value: _Optional[float] = ...) -> None: ...
    class TimingsMsEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: float
        def __init__(self, key: _Optional[str] = ..., value: _Optional[float] = ...) -> None: ...
    TIMESTAMP_MS_FIELD_NUMBER: _ClassVar[int]
    DECISION_FIELD_NUMBER: _ClassVar[int]
    BONAFIDE_PROBABILITY_FIELD_NUMBER: _ClassVar[int]
    ATTACK_DETECTED_FIELD_NUMBER: _ClassVar[int]
    CATEGORIES_FIELD_NUMBER: _ClassVar[int]
    ATTACK_CATEGORY_FIELD_NUMBER: _ClassVar[int]
    SUSPECTED_PAI_SPECIES_FIELD_NUMBER: _ClassVar[int]
    FACE_FIELD_NUMBER: _ClassVar[int]
    QUALITY_FIELD_NUMBER: _ClassVar[int]
    MODELS_FIELD_NUMBER: _ClassVar[int]
    CUES_FIELD_NUMBER: _ClassVar[int]
    TIMINGS_MS_FIELD_NUMBER: _ClassVar[int]
    HEATMAP_PNG_FIELD_NUMBER: _ClassVar[int]
    JSON_FIELD_NUMBER: _ClassVar[int]
    timestamp_ms: int
    decision: Decision
    bonafide_probability: float
    attack_detected: bool
    categories: _containers.ScalarMap[str, float]
    attack_category: AttackCategory
    suspected_pai_species: PAISpecies
    face: FaceInfo
    quality: Quality
    models: _containers.RepeatedCompositeFieldContainer[ModelOutput]
    cues: Cues
    timings_ms: _containers.ScalarMap[str, float]
    heatmap_png: bytes
    json: str
    def __init__(self, timestamp_ms: _Optional[int] = ..., decision: _Optional[_Union[Decision, str]] = ..., bonafide_probability: _Optional[float] = ..., attack_detected: _Optional[bool] = ..., categories: _Optional[_Mapping[str, float]] = ..., attack_category: _Optional[_Union[AttackCategory, str]] = ..., suspected_pai_species: _Optional[_Union[PAISpecies, str]] = ..., face: _Optional[_Union[FaceInfo, _Mapping]] = ..., quality: _Optional[_Union[Quality, _Mapping]] = ..., models: _Optional[_Iterable[_Union[ModelOutput, _Mapping]]] = ..., cues: _Optional[_Union[Cues, _Mapping]] = ..., timings_ms: _Optional[_Mapping[str, float]] = ..., heatmap_png: _Optional[bytes] = ..., json: _Optional[str] = ...) -> None: ...

class TemporalCues(_message.Message):
    __slots__ = ("frames", "head_motion", "expression_range", "blink_detected", "static_face", "score_std")
    FRAMES_FIELD_NUMBER: _ClassVar[int]
    HEAD_MOTION_FIELD_NUMBER: _ClassVar[int]
    EXPRESSION_RANGE_FIELD_NUMBER: _ClassVar[int]
    BLINK_DETECTED_FIELD_NUMBER: _ClassVar[int]
    STATIC_FACE_FIELD_NUMBER: _ClassVar[int]
    SCORE_STD_FIELD_NUMBER: _ClassVar[int]
    frames: int
    head_motion: float
    expression_range: float
    blink_detected: bool
    static_face: float
    score_std: float
    def __init__(self, frames: _Optional[int] = ..., head_motion: _Optional[float] = ..., expression_range: _Optional[float] = ..., blink_detected: _Optional[bool] = ..., static_face: _Optional[float] = ..., score_std: _Optional[float] = ...) -> None: ...

class StreamResult(_message.Message):
    __slots__ = ("decision", "bonafide_probability", "attack_detected", "categories", "attack_category", "suspected_pai_species", "pai_indicators", "frames_received", "frames_analysed", "frames_used", "complete", "duration_ms", "non_response_reasons", "temporal", "thresholds", "frames", "json")
    class CategoriesEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: float
        def __init__(self, key: _Optional[str] = ..., value: _Optional[float] = ...) -> None: ...
    class PaiIndicatorsEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: float
        def __init__(self, key: _Optional[str] = ..., value: _Optional[float] = ...) -> None: ...
    class NonResponseReasonsEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: int
        def __init__(self, key: _Optional[str] = ..., value: _Optional[int] = ...) -> None: ...
    class ThresholdsEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: float
        def __init__(self, key: _Optional[str] = ..., value: _Optional[float] = ...) -> None: ...
    DECISION_FIELD_NUMBER: _ClassVar[int]
    BONAFIDE_PROBABILITY_FIELD_NUMBER: _ClassVar[int]
    ATTACK_DETECTED_FIELD_NUMBER: _ClassVar[int]
    CATEGORIES_FIELD_NUMBER: _ClassVar[int]
    ATTACK_CATEGORY_FIELD_NUMBER: _ClassVar[int]
    SUSPECTED_PAI_SPECIES_FIELD_NUMBER: _ClassVar[int]
    PAI_INDICATORS_FIELD_NUMBER: _ClassVar[int]
    FRAMES_RECEIVED_FIELD_NUMBER: _ClassVar[int]
    FRAMES_ANALYSED_FIELD_NUMBER: _ClassVar[int]
    FRAMES_USED_FIELD_NUMBER: _ClassVar[int]
    COMPLETE_FIELD_NUMBER: _ClassVar[int]
    DURATION_MS_FIELD_NUMBER: _ClassVar[int]
    NON_RESPONSE_REASONS_FIELD_NUMBER: _ClassVar[int]
    TEMPORAL_FIELD_NUMBER: _ClassVar[int]
    THRESHOLDS_FIELD_NUMBER: _ClassVar[int]
    FRAMES_FIELD_NUMBER: _ClassVar[int]
    JSON_FIELD_NUMBER: _ClassVar[int]
    decision: Decision
    bonafide_probability: float
    attack_detected: bool
    categories: _containers.ScalarMap[str, float]
    attack_category: AttackCategory
    suspected_pai_species: PAISpecies
    pai_indicators: _containers.ScalarMap[str, float]
    frames_received: int
    frames_analysed: int
    frames_used: int
    complete: bool
    duration_ms: int
    non_response_reasons: _containers.ScalarMap[str, int]
    temporal: TemporalCues
    thresholds: _containers.ScalarMap[str, float]
    frames: _containers.RepeatedCompositeFieldContainer[FrameAnalysis]
    json: str
    def __init__(self, decision: _Optional[_Union[Decision, str]] = ..., bonafide_probability: _Optional[float] = ..., attack_detected: _Optional[bool] = ..., categories: _Optional[_Mapping[str, float]] = ..., attack_category: _Optional[_Union[AttackCategory, str]] = ..., suspected_pai_species: _Optional[_Union[PAISpecies, str]] = ..., pai_indicators: _Optional[_Mapping[str, float]] = ..., frames_received: _Optional[int] = ..., frames_analysed: _Optional[int] = ..., frames_used: _Optional[int] = ..., complete: _Optional[bool] = ..., duration_ms: _Optional[int] = ..., non_response_reasons: _Optional[_Mapping[str, int]] = ..., temporal: _Optional[_Union[TemporalCues, _Mapping]] = ..., thresholds: _Optional[_Mapping[str, float]] = ..., frames: _Optional[_Iterable[_Union[FrameAnalysis, _Mapping]]] = ..., json: _Optional[str] = ...) -> None: ...

class Error(_message.Message):
    __slots__ = ("code", "message")
    CODE_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    code: ErrorCode
    message: str
    def __init__(self, code: _Optional[_Union[ErrorCode, str]] = ..., message: _Optional[str] = ...) -> None: ...

class AnalyzeImageRequest(_message.Message):
    __slots__ = ("data", "encoding", "width", "height", "explain")
    DATA_FIELD_NUMBER: _ClassVar[int]
    ENCODING_FIELD_NUMBER: _ClassVar[int]
    WIDTH_FIELD_NUMBER: _ClassVar[int]
    HEIGHT_FIELD_NUMBER: _ClassVar[int]
    EXPLAIN_FIELD_NUMBER: _ClassVar[int]
    data: bytes
    encoding: _active_liveness_pb2.FrameEncoding
    width: int
    height: int
    explain: bool
    def __init__(self, data: _Optional[bytes] = ..., encoding: _Optional[_Union[_active_liveness_pb2.FrameEncoding, str]] = ..., width: _Optional[int] = ..., height: _Optional[int] = ..., explain: _Optional[bool] = ...) -> None: ...

class AnalyzeVideoRequest(_message.Message):
    __slots__ = ("data", "filename_hint", "max_frames", "include_frames", "stop_when_complete")
    DATA_FIELD_NUMBER: _ClassVar[int]
    FILENAME_HINT_FIELD_NUMBER: _ClassVar[int]
    MAX_FRAMES_FIELD_NUMBER: _ClassVar[int]
    INCLUDE_FRAMES_FIELD_NUMBER: _ClassVar[int]
    STOP_WHEN_COMPLETE_FIELD_NUMBER: _ClassVar[int]
    data: bytes
    filename_hint: str
    max_frames: int
    include_frames: bool
    stop_when_complete: bool
    def __init__(self, data: _Optional[bytes] = ..., filename_hint: _Optional[str] = ..., max_frames: _Optional[int] = ..., include_frames: _Optional[bool] = ..., stop_when_complete: _Optional[bool] = ...) -> None: ...

class StartStream(_message.Message):
    __slots__ = ("frames_required", "include_frames", "explain", "allow_partial")
    FRAMES_REQUIRED_FIELD_NUMBER: _ClassVar[int]
    INCLUDE_FRAMES_FIELD_NUMBER: _ClassVar[int]
    EXPLAIN_FIELD_NUMBER: _ClassVar[int]
    ALLOW_PARTIAL_FIELD_NUMBER: _ClassVar[int]
    frames_required: int
    include_frames: bool
    explain: bool
    allow_partial: bool
    def __init__(self, frames_required: _Optional[int] = ..., include_frames: _Optional[bool] = ..., explain: _Optional[bool] = ..., allow_partial: _Optional[bool] = ...) -> None: ...

class EndStream(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class StreamRequest(_message.Message):
    __slots__ = ("start", "frame", "end")
    START_FIELD_NUMBER: _ClassVar[int]
    FRAME_FIELD_NUMBER: _ClassVar[int]
    END_FIELD_NUMBER: _ClassVar[int]
    start: StartStream
    frame: _active_liveness_pb2.Frame
    end: EndStream
    def __init__(self, start: _Optional[_Union[StartStream, _Mapping]] = ..., frame: _Optional[_Union[_active_liveness_pb2.Frame, _Mapping]] = ..., end: _Optional[_Union[EndStream, _Mapping]] = ...) -> None: ...

class StreamResponse(_message.Message):
    __slots__ = ("frame", "result", "error")
    FRAME_FIELD_NUMBER: _ClassVar[int]
    RESULT_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    frame: FrameAnalysis
    result: StreamResult
    error: Error
    def __init__(self, frame: _Optional[_Union[FrameAnalysis, _Mapping]] = ..., result: _Optional[_Union[StreamResult, _Mapping]] = ..., error: _Optional[_Union[Error, _Mapping]] = ...) -> None: ...

class HybridStart(_message.Message):
    __slots__ = ("workflow",)
    WORKFLOW_FIELD_NUMBER: _ClassVar[int]
    workflow: _active_liveness_pb2.Workflow
    def __init__(self, workflow: _Optional[_Union[_active_liveness_pb2.Workflow, str]] = ...) -> None: ...

class HybridClientMessage(_message.Message):
    __slots__ = ("start", "frame", "retry", "cancel")
    START_FIELD_NUMBER: _ClassVar[int]
    FRAME_FIELD_NUMBER: _ClassVar[int]
    RETRY_FIELD_NUMBER: _ClassVar[int]
    CANCEL_FIELD_NUMBER: _ClassVar[int]
    start: HybridStart
    frame: _active_liveness_pb2.Frame
    retry: _active_liveness_pb2.Retry
    cancel: _active_liveness_pb2.Cancel
    def __init__(self, start: _Optional[_Union[HybridStart, _Mapping]] = ..., frame: _Optional[_Union[_active_liveness_pb2.Frame, _Mapping]] = ..., retry: _Optional[_Union[_active_liveness_pb2.Retry, _Mapping]] = ..., cancel: _Optional[_Union[_active_liveness_pb2.Cancel, _Mapping]] = ...) -> None: ...

class HybridStarted(_message.Message):
    __slots__ = ("session_id", "workflow", "frames_required")
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    WORKFLOW_FIELD_NUMBER: _ClassVar[int]
    FRAMES_REQUIRED_FIELD_NUMBER: _ClassVar[int]
    session_id: str
    workflow: _active_liveness_pb2.Workflow
    frames_required: int
    def __init__(self, session_id: _Optional[str] = ..., workflow: _Optional[_Union[_active_liveness_pb2.Workflow, str]] = ..., frames_required: _Optional[int] = ...) -> None: ...

class PassiveProgress(_message.Message):
    __slots__ = ("frames_used", "frames_required", "quality")
    FRAMES_USED_FIELD_NUMBER: _ClassVar[int]
    FRAMES_REQUIRED_FIELD_NUMBER: _ClassVar[int]
    QUALITY_FIELD_NUMBER: _ClassVar[int]
    frames_used: int
    frames_required: int
    quality: Quality
    def __init__(self, frames_used: _Optional[int] = ..., frames_required: _Optional[int] = ..., quality: _Optional[_Union[Quality, _Mapping]] = ...) -> None: ...

class PassiveVerdict(_message.Message):
    __slots__ = ("result", "next_step")
    RESULT_FIELD_NUMBER: _ClassVar[int]
    NEXT_STEP_FIELD_NUMBER: _ClassVar[int]
    result: StreamResult
    next_step: NextStep
    def __init__(self, result: _Optional[_Union[StreamResult, _Mapping]] = ..., next_step: _Optional[_Union[NextStep, str]] = ...) -> None: ...

class MonitorResult(_message.Message):
    __slots__ = ("frame", "consecutive_attacks")
    FRAME_FIELD_NUMBER: _ClassVar[int]
    CONSECUTIVE_ATTACKS_FIELD_NUMBER: _ClassVar[int]
    frame: FrameAnalysis
    consecutive_attacks: int
    def __init__(self, frame: _Optional[_Union[FrameAnalysis, _Mapping]] = ..., consecutive_attacks: _Optional[int] = ...) -> None: ...

class HybridDecision(_message.Message):
    __slots__ = ("status", "reason", "message", "passive_score", "active_status")
    STATUS_FIELD_NUMBER: _ClassVar[int]
    REASON_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    PASSIVE_SCORE_FIELD_NUMBER: _ClassVar[int]
    ACTIVE_STATUS_FIELD_NUMBER: _ClassVar[int]
    status: HybridStatus
    reason: HybridReason
    message: str
    passive_score: float
    active_status: str
    def __init__(self, status: _Optional[_Union[HybridStatus, str]] = ..., reason: _Optional[_Union[HybridReason, str]] = ..., message: _Optional[str] = ..., passive_score: _Optional[float] = ..., active_status: _Optional[str] = ...) -> None: ...

class HybridServerMessage(_message.Message):
    __slots__ = ("started", "passive_progress", "passive_verdict", "active", "monitor", "decision", "error")
    STARTED_FIELD_NUMBER: _ClassVar[int]
    PASSIVE_PROGRESS_FIELD_NUMBER: _ClassVar[int]
    PASSIVE_VERDICT_FIELD_NUMBER: _ClassVar[int]
    ACTIVE_FIELD_NUMBER: _ClassVar[int]
    MONITOR_FIELD_NUMBER: _ClassVar[int]
    DECISION_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    started: HybridStarted
    passive_progress: PassiveProgress
    passive_verdict: PassiveVerdict
    active: _active_liveness_pb2.ServerMessage
    monitor: MonitorResult
    decision: HybridDecision
    error: Error
    def __init__(self, started: _Optional[_Union[HybridStarted, _Mapping]] = ..., passive_progress: _Optional[_Union[PassiveProgress, _Mapping]] = ..., passive_verdict: _Optional[_Union[PassiveVerdict, _Mapping]] = ..., active: _Optional[_Union[_active_liveness_pb2.ServerMessage, _Mapping]] = ..., monitor: _Optional[_Union[MonitorResult, _Mapping]] = ..., decision: _Optional[_Union[HybridDecision, _Mapping]] = ..., error: _Optional[_Union[Error, _Mapping]] = ...) -> None: ...

class GetInfoRequest(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class ServiceInfo(_message.Message):
    __slots__ = ("json",)
    JSON_FIELD_NUMBER: _ClassVar[int]
    json: str
    def __init__(self, json: _Optional[str] = ...) -> None: ...
