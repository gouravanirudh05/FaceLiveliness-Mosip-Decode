"""Core value types shared across the active liveness module.

Direction convention used everywhere in this package: LEFT / RIGHT / UP / DOWN are
from the *subject's* point of view ("turn your head to the left" means the person's
own left), assuming an un-mirrored camera frame. Set ``service.input_mirrored`` in
the config when the device delivers selfie-mirrored frames.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, IntEnum
from typing import Mapping


class Workflow(str, Enum):
    RESIDENT = "resident"
    OPERATOR = "operator"
    SUPERVISOR = "supervisor"


class Tier(IntEnum):
    EASY = 1
    MEDIUM = 2
    HARD = 3


class Action(str, Enum):
    BLINK = "blink"
    SMILE = "smile"
    OPEN_MOUTH = "open_mouth"
    TURN_LEFT = "turn_left"
    TURN_RIGHT = "turn_right"
    LOOK_UP = "look_up"          # head pitch up
    LOOK_DOWN = "look_down"      # head pitch down
    NOD = "nod"                  # head pitch down, then back up
    GAZE_LEFT = "gaze_left"      # eyes only, head still
    GAZE_RIGHT = "gaze_right"
    GAZE_UP = "gaze_up"
    GAZE_DOWN = "gaze_down"


@dataclass(frozen=True)
class FaceObservation:
    """Everything the detectors need from one analysed frame.

    Angles are in degrees in the camera frame. ``yaw_deg`` > 0 means the face points
    towards the subject's left, ``pitch_deg`` > 0 means it points up.
    ``gaze_horizontal`` is the iris offset within the eye opening in [-1, 1];
    > 0 means the eyes look towards the subject's left.
    """

    timestamp_ms: int
    face_count: int
    blendshapes: Mapping[str, float] = field(default_factory=dict)
    yaw_deg: float = 0.0
    pitch_deg: float = 0.0
    roll_deg: float = 0.0
    gaze_horizontal: float = 0.0
    # (x_min, y_min, x_max, y_max), normalised to [0, 1]; None when no single face.
    face_box: tuple[float, float, float, float] | None = None

    def _mean(self, *names: str) -> float:
        return sum(self.blendshapes.get(n, 0.0) for n in names) / len(names)

    @property
    def blink(self) -> float:
        return self._mean("eyeBlinkLeft", "eyeBlinkRight")

    @property
    def smile(self) -> float:
        return self._mean("mouthSmileLeft", "mouthSmileRight")

    @property
    def jaw_open(self) -> float:
        return self.blendshapes.get("jawOpen", 0.0)

    @property
    def gaze_up(self) -> float:
        return self._mean("eyeLookUpLeft", "eyeLookUpRight")

    @property
    def gaze_down(self) -> float:
        return self._mean("eyeLookDownLeft", "eyeLookDownRight")
