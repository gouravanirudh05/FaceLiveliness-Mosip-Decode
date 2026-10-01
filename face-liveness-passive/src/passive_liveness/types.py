"""Result types. Every result serialises to plain JSON via ``to_dict()``.

Terminology follows ISO/IEC 30107-1/-3: a *bona fide presentation* is a live subject;
a *presentation attack* (PA) uses a *presentation attack instrument* (PAI) such as a
printed photo or a screen; PAI *species* are classes of instrument (print, replay, ...).
"""

from __future__ import annotations

import dataclasses
import enum
from dataclasses import dataclass, field
from typing import Any


class Decision(enum.Enum):
    BONAFIDE = "bonafide"            # fused bona fide probability >= accept_threshold
    ATTACK = "attack"                # fused bona fide probability <  reject_threshold
    UNCERTAIN = "uncertain"          # in between: needs another factor (e.g. active liveness)
    NON_RESPONSE = "non_response"    # could not be evaluated (no face, poor quality, timeout ...)


class AttackCategory(enum.Enum):
    """Most likely class of attack, from the fused model probabilities."""
    NONE = "none"                                    # bona fide is the most likely class
    PRESENTATION_ATTACK = "presentation_attack"      # physical PAI in front of the camera
    DEEPFAKE = "deepfake"                            # face-swap / reenactment (digital)
    SYNTHETIC = "synthetic"                          # diffusion / GAN generated face (digital)


class PAISpecies(enum.Enum):
    """Suspected PAI species. Only derived from heuristic cues, never from the models."""
    NONE = "none"
    PRINT = "print"                  # printed photo / paper
    SCREEN_REPLAY = "screen_replay"  # phone / tablet / monitor showing a photo or video
    UNSPECIFIED = "unspecified"      # attack suspected but cues do not indicate a species


class NonResponseReason(enum.Enum):
    NO_FACE = "no_face"
    MULTIPLE_FACES = "multiple_faces"
    FACE_TOO_SMALL = "face_too_small"
    TOO_BLURRY = "too_blurry"
    TOO_DARK = "too_dark"
    TOO_BRIGHT = "too_bright"
    POSE_OUT_OF_RANGE = "pose_out_of_range"
    FACE_CUT_OFF = "face_cut_off"
    INSUFFICIENT_FRAMES = "insufficient_frames"     # stream ended / timed out before enough valid frames
    DECODE_ERROR = "decode_error"


# Fused class order, shared by every component and serialisation.
CATEGORY_LABELS = ("bonafide", "presentation_attack", "deepfake", "synthetic")


def _plain(v: Any) -> Any:
    if isinstance(v, enum.Enum):
        return v.value
    if dataclasses.is_dataclass(v):
        return {f.name: _plain(getattr(v, f.name)) for f in dataclasses.fields(v)
                if not f.metadata.get("skip_json")}
    if isinstance(v, dict):
        return {str(k): _plain(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_plain(x) for x in v]
    if hasattr(v, "item"):          # numpy scalar
        return v.item()
    return v


class _Serializable:
    def to_dict(self) -> dict[str, Any]:
        return _plain(self)


@dataclass(frozen=True)
class FaceInfo(_Serializable):
    count: int                                        # faces detected in the frame
    box: tuple[int, int, int, int] | None = None      # landmark extent (x0, y0, x1, y1), px, analysed face
    crop_box: tuple[int, int, int, int] | None = None  # square crop fed to the models, px
    crop_clip: float = 0.0                            # fraction of the ideal crop outside the frame
    yaw_deg: float | None = None                      # + = subject's left (un-mirrored)
    pitch_deg: float | None = None                    # + = up
    roll_deg: float | None = None
    eye_blink: float | None = None                    # mean eyeBlink blendshape (0 open .. 1 closed)
    all_boxes: tuple[tuple[int, int, int, int], ...] = ()


@dataclass(frozen=True)
class Quality(_Serializable):
    passed: bool
    reasons: tuple[NonResponseReason, ...] = ()
    face_px: float = 0.0
    sharpness: float = 0.0          # variance of Laplacian on the 224 px crop
    brightness: float = 0.0         # mean grey level of the crop
    contrast: float = 0.0           # std of grey level of the crop


@dataclass(frozen=True)
class ModelOutput(_Serializable):
    name: str
    labels: tuple[str, ...]
    probabilities: tuple[float, ...]
    logits: tuple[float, ...]
    bonafide_probability: float
    inference_ms: float

    @property
    def as_map(self) -> dict[str, float]:
        return dict(zip(self.labels, self.probabilities))


@dataclass(frozen=True)
class Cues(_Serializable):
    """Hand-crafted image measurements and the PAI indicators derived from them.

    Heuristic and uncalibrated; reported for transparency and to suggest a PAI species.
    """
    values: dict[str, float] = field(default_factory=dict)
    indicators: dict[str, float] = field(default_factory=dict)   # e.g. {"print": 0.2, "screen_replay": 0.7}
    evidence: tuple[str, ...] = ()


@dataclass(frozen=True)
class FrameAnalysis(_Serializable):
    """Everything known about one analysed frame (or still image)."""
    timestamp_ms: int
    decision: Decision
    bonafide_probability: float | None          # fused liveness score in [0, 1]; None without a face
    attack_detected: bool
    categories: dict[str, float]                # fused distribution over CATEGORY_LABELS
    attack_category: AttackCategory
    suspected_pai_species: PAISpecies
    face: FaceInfo
    quality: Quality
    models: tuple[ModelOutput, ...] = ()
    cues: Cues = field(default_factory=Cues)
    timings_ms: dict[str, float] = field(default_factory=dict)
    heatmap_png: bytes | None = field(default=None, metadata={"skip_json": True})

    @property
    def analysed(self) -> bool:
        return self.bonafide_probability is not None


@dataclass(frozen=True)
class TemporalCues(_Serializable):
    frames: int = 0
    head_motion: float | None = None        # mean face-centre movement between frames, / face size
    expression_range: float | None = None   # largest change of any expression blendshape
    blink_detected: bool | None = None
    static_face: float | None = None        # 1 = expression never changed (photo-like), 0 = live-like
    score_std: float | None = None          # std of per-frame bona fide probability


@dataclass(frozen=True)
class StreamResult(_Serializable):
    """Aggregate over the frames of a video / live stream."""
    decision: Decision
    bonafide_probability: float | None
    attack_detected: bool
    categories: dict[str, float]
    attack_category: AttackCategory
    suspected_pai_species: PAISpecies
    pai_indicators: dict[str, float]
    frames_received: int
    frames_analysed: int
    frames_used: int                       # quality-passing frames aggregated into the score
    complete: bool                         # frames_used reached stream.frames_required
    duration_ms: int
    non_response_reasons: dict[str, int]   # reason -> frame count
    temporal: TemporalCues
    thresholds: dict[str, float]
    models: dict[str, Any]
    frames: tuple[FrameAnalysis, ...] = ()  # per-frame detail, if requested
