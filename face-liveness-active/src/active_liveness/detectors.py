"""Per-action detectors that turn a stream of FaceObservations into a verdict.

Every detector follows the same life cycle:

1. WAITING_NEUTRAL – it needs ``neutral_frames`` consecutive frames in which the
   subject is *not* already performing the action and the relevant signals are
   stable. Those frames define the baseline. This prevents a static photo of a
   smiling / turned face from passing, because an action must be a *transition*.
2. IN_PROGRESS – the signal is measured relative to the baseline.
3. COMPLETED or WRONG_ACTION – terminal. A clearly opposite movement (e.g. turning
   right when asked to turn left) is WRONG_ACTION, which defeats blind replays.

Only a single detected face may be fed in; the session filters other frames.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import Sequence

from .config import StepParams, Thresholds
from .types import Action, FaceObservation


class DetectorState(Enum):
    WAITING_NEUTRAL = "waiting_neutral"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    WRONG_ACTION = "wrong_action"


class Hint(Enum):
    HOLD_STILL = "hold_still"            # waiting for a steady, neutral face
    KEEP_HEAD_STILL = "keep_head_still"  # gaze challenge, but the head moved


@dataclass(frozen=True)
class DetectorUpdate:
    state: DetectorState
    progress: float = 0.0                # 0..1, for UI progress indication
    margin: float = 0.0                  # how clearly the action passed, 0..1 (COMPLETED only)
    hint: Hint | None = None


_FEATURES = {
    "yaw": lambda o: o.yaw_deg,
    "pitch": lambda o: o.pitch_deg,
    "gaze_h": lambda o: o.gaze_horizontal,
    "gaze_up": lambda o: o.gaze_up,
    "gaze_down": lambda o: o.gaze_down,
}


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def _margin(peak: float, threshold: float) -> float:
    return _clamp01((peak - threshold) / threshold)


class ActionDetector(ABC):
    """Base class handling neutral-baseline capture and terminal states."""

    #: features whose spread must stay within tolerance while capturing the baseline
    stable_features: tuple[str, ...] = ()

    def __init__(self, t: Thresholds):
        self.t = t
        self.reset()

    def reset(self) -> None:
        self._window: deque[FaceObservation] = deque(maxlen=self.t.neutral_frames)
        self.baseline: dict[str, float] | None = None
        self._final: DetectorUpdate | None = None
        self._wrong = 0
        self._reset_tracking()

    def update(self, obs: FaceObservation) -> DetectorUpdate:
        if self._final is not None:
            return self._final
        if self.baseline is None:
            if not self._is_neutral(obs):
                self._window.clear()
                return DetectorUpdate(DetectorState.WAITING_NEUTRAL, hint=Hint.HOLD_STILL)
            self._window.append(obs)
            if len(self._window) < self.t.neutral_frames or not self._window_stable():
                return DetectorUpdate(DetectorState.WAITING_NEUTRAL, hint=Hint.HOLD_STILL)
            self.baseline = {
                name: sum(fn(o) for o in self._window) / len(self._window)
                for name, fn in _FEATURES.items()
            }
            self._after_baseline()
            return DetectorUpdate(DetectorState.IN_PROGRESS, progress=0.0)
        result = self._track(obs)
        if result.state in (DetectorState.COMPLETED, DetectorState.WRONG_ACTION):
            self._final = result
        return result

    def _after_baseline(self) -> None:
        """Hook: derive extra reference values from the baseline window (default: none)."""
        pass

    def _persistent_wrong(self, wrong: bool) -> bool:
        """True once the opposite movement was seen in ``wrong_action_frames`` consecutive frames.

        A single frame of landmark / blendshape jitter must not fail a whole attempt. The detector
        must not fail if the subject is not moving, so the opposite movement must be seen in
        ``wrong_action_frames`` consecutive frames.
        """
        self._wrong = self._wrong + 1 if wrong else 0
        return self._wrong >= self.t.wrong_action_frames

    def _window_stable(self) -> bool:
        for name in self.stable_features:
            values = [_FEATURES[name](o) for o in self._window]
            limit = self.t.stability_deg if name in ("yaw", "pitch") else self.t.stability_gaze
            if max(values) - min(values) > limit:
                return False
        return True

    def _delta(self, obs: FaceObservation, name: str) -> float:
        return _FEATURES[name](obs) - self.baseline[name]

    def _hold_update(self, active: bool, value: float, threshold: float) -> DetectorUpdate:
        """Shared 'must be held for hold_frames' logic."""
        if active:
            self._hold += 1
            self._peak = max(self._peak, value)
            if self._hold >= self.t.hold_frames:
                return DetectorUpdate(DetectorState.COMPLETED, 1.0, _margin(self._peak, threshold))
            return DetectorUpdate(DetectorState.IN_PROGRESS,
                                  0.8 + 0.2 * self._hold / self.t.hold_frames)
        self._hold = 0
        self._peak = 0.0
        return DetectorUpdate(DetectorState.IN_PROGRESS, 0.8 * _clamp01(value / threshold))

    @abstractmethod
    def _reset_tracking(self) -> None: ...

    @abstractmethod
    def _is_neutral(self, obs: FaceObservation) -> bool: ...

    @abstractmethod
    def _track(self, obs: FaceObservation) -> DetectorUpdate: ...


class ExpressionDetector(ActionDetector):
    """Smile / open mouth: blendshape rises from below `neutral` to above `threshold`.
    A resting level below `neutral` is always accepted. People whose resting face sits a
    little higher (e.g. a natural resting smile) are accepted too, up to halfway between
    `neutral` and `threshold`, provided the signal is steady; for them the action must
    rise by the same amount (`threshold - neutral`) above their own resting level.
    A face already at or above that limit (a photo of a smiling face) never arms."""

    def __init__(self, t: Thresholds, signal: str, threshold: float, neutral: float):
        self._signal, self._threshold, self._neutral = signal, threshold, neutral
        self._rise = threshold - neutral
        self._rest_limit = neutral + 0.5 * self._rise
        super().__init__(t)

    def _value(self, obs):
        return getattr(obs, self._signal)

    def _reset_tracking(self):
        self._hold, self._peak = 0, 0.0
        self._target = self._threshold

    def _is_neutral(self, obs):
        return self._value(obs) < self._rest_limit

    def _track(self, obs):
        v = self._value(obs)
        return self._hold_update(v >= self._target, v, self._target)

    def _window_stable(self):
        values = [self._value(o) for o in self._window]
        if max(values) < self._neutral:
            return True                     # clearly neutral: no steadiness requirement
        return max(values) - min(values) <= self.t.stability_gaze

    def _after_baseline(self):
        rest = sum(self._value(o) for o in self._window) / len(self._window)
        self._target = max(self._threshold, rest + self._rise)


class BlinkDetector(ActionDetector):
    """Eyes open -> closed -> open."""

    def _reset_tracking(self):
        self._closed_seen, self._peak = False, 0.0
        self._closed_at = self._closed_last = 0

    def _is_neutral(self, obs):
        return obs.blink < self.t.blink_open

    def _track(self, obs):
        v = obs.blink
        if v >= self.t.blink_closed:
            if not self._closed_seen:
                self._closed_at = obs.timestamp_ms
            self._closed_seen = True
            self._closed_last = obs.timestamp_ms
            self._peak = max(self._peak, v)
            return DetectorUpdate(DetectorState.IN_PROGRESS, 0.6)
        if self._closed_seen and v < self.t.blink_open:
            if self._closed_last - self._closed_at > self.t.blink_max_ms:
                # eyes were shut for a long time: not a blink; wait for a real one
                self._closed_seen, self._peak = False, 0.0
                return DetectorUpdate(DetectorState.IN_PROGRESS, 0.0)
            return DetectorUpdate(DetectorState.COMPLETED, 1.0, _margin(self._peak, self.t.blink_closed))
        if self._closed_seen:
            return DetectorUpdate(DetectorState.IN_PROGRESS, 0.8)
        return DetectorUpdate(DetectorState.IN_PROGRESS, 0.5 * _clamp01(v / self.t.blink_closed))


class HeadTurnDetector(ActionDetector):
    """Head yaw or pitch moves by `angle` in `sign` direction; the opposite is WRONG_ACTION."""

    stable_features = ("yaw", "pitch")

    def __init__(self, t: Thresholds, feature: str, sign: int, angle: float):
        self._feature, self._sign, self._angle = feature, sign, angle
        super().__init__(t)

    def _reset_tracking(self):
        self._hold, self._peak = 0, 0.0

    def _is_neutral(self, obs):
        return True  # neutrality for head movement is defined by stability alone

    def _track(self, obs):
        d = self._delta(obs, self._feature) * self._sign
        opposite = d <= -self._angle
        if self._persistent_wrong(opposite):
            return DetectorUpdate(DetectorState.WRONG_ACTION)
        if opposite:                    # not persistent yet: neither wrong nor progress
            self._hold, self._peak = 0, 0.0
            return DetectorUpdate(DetectorState.IN_PROGRESS, 0.0)
        return self._hold_update(d >= self._angle, d, self._angle)


class NodDetector(ActionDetector):
    """Pitch dips down by `angle`, then comes back up at least `nod_return_ratio` of the dip."""

    stable_features = ("yaw", "pitch")

    def __init__(self, t: Thresholds, angle: float):
        self._angle = angle
        super().__init__(t)

    def _reset_tracking(self):
        self._dip, self._dip_frames = 0.0, 0

    def _is_neutral(self, obs):
        return True

    def _track(self, obs):
        down = -self._delta(obs, "pitch")
        if down >= self._angle:
            self._dip_frames += 1
        if down >= self._angle or self._dip:
            self._dip = max(self._dip, down)
            if down <= self._dip * self.t.nod_return_ratio:
                if self._dip_frames >= self.t.nod_dip_frames:
                    return DetectorUpdate(DetectorState.COMPLETED, 1.0, _margin(self._dip, self._angle))
                self._dip, self._dip_frames = 0.0, 0     # a one-frame spike, not a nod
                return DetectorUpdate(DetectorState.IN_PROGRESS, 0.0)
            return DetectorUpdate(DetectorState.IN_PROGRESS, 0.6)
        return DetectorUpdate(DetectorState.IN_PROGRESS, 0.5 * _clamp01(down / self._angle))


class _GazeDetector(ActionDetector):
    """Eyes move while the head stays within `head_still_deg` of its baseline."""

    def _reset_tracking(self):
        self._hold, self._peak, self._wrong = 0, 0.0, 0

    def _is_neutral(self, obs):
        return obs.blink < self.t.blink_closed

    def _head_moved(self, obs):
        return (abs(self._delta(obs, "yaw")) > self.t.head_still_deg
                or abs(self._delta(obs, "pitch")) > self.t.head_still_deg)

    def _track(self, obs):
        if self._head_moved(obs):
            self._hold, self._peak = 0, 0.0
            return DetectorUpdate(DetectorState.IN_PROGRESS, 0.0, hint=Hint.KEEP_HEAD_STILL)
        toward, away = self._signals(obs)
        thr = self._threshold()
        if self._persistent_wrong(away >= thr):
            return DetectorUpdate(DetectorState.WRONG_ACTION)
        if away >= thr:                 # not persistent yet: neither wrong nor progress
            self._hold, self._peak = 0, 0.0
            return DetectorUpdate(DetectorState.IN_PROGRESS, 0.0)
        return self._hold_update(toward >= thr and self._eyes_ok(obs), toward, thr)

    def _eyes_ok(self, obs):
        return True


class GazeHorizontalDetector(_GazeDetector):
    stable_features = ("yaw", "pitch", "gaze_h")

    def __init__(self, t: Thresholds, sign: int):
        self._sign = sign
        super().__init__(t)

    def _threshold(self):
        return self.t.gaze_horizontal

    def _signals(self, obs):
        d = self._delta(obs, "gaze_h") * self._sign
        return d, -d


class GazeVerticalDetector(_GazeDetector):
    stable_features = ("yaw", "pitch", "gaze_up", "gaze_down")

    def __init__(self, t: Thresholds, up: bool):
        self._up = up
        super().__init__(t)

    def _threshold(self):
        return self.t.gaze_vertical

    def _signals(self, obs):
        up, down = self._delta(obs, "gaze_up"), self._delta(obs, "gaze_down")
        return (up, down) if self._up else (down, up)

    def _eyes_ok(self, obs):
        # Looking down lowers the eyelids; closing the eyes must not count as a gaze.
        return obs.blink < self.t.blink_closed


class CompoundDetector:
    """Runs several detectors strictly in order; fails as soon as any part fails."""

    def __init__(self, parts: Sequence[ActionDetector]):
        self.parts = list(parts)
        self.reset()

    def reset(self) -> None:
        for p in self.parts:
            p.reset()
        self._index = 0
        self._margins: list[float] = []

    def update(self, obs: FaceObservation) -> DetectorUpdate:
        n = len(self.parts)
        if self._index >= n:
            return DetectorUpdate(DetectorState.COMPLETED, 1.0, min(self._margins))
        u = self.parts[self._index].update(obs)
        if u.state is DetectorState.WRONG_ACTION:
            return u
        if u.state is DetectorState.COMPLETED:
            self._margins.append(u.margin)
            self._index += 1
            if self._index == n:
                return DetectorUpdate(DetectorState.COMPLETED, 1.0, min(self._margins))
            return DetectorUpdate(DetectorState.IN_PROGRESS, self._index / n)
        state = DetectorState.WAITING_NEUTRAL if (self._index == 0 and u.state is DetectorState.WAITING_NEUTRAL) \
            else DetectorState.IN_PROGRESS
        return DetectorUpdate(state, (self._index + u.progress) / n, hint=u.hint)


def create_detector(action: Action, step: StepParams, t: Thresholds) -> ActionDetector:
    match action:
        case Action.BLINK:
            return BlinkDetector(t)
        case Action.SMILE:
            return ExpressionDetector(t, "smile", t.smile, t.smile_neutral)
        case Action.OPEN_MOUTH:
            return ExpressionDetector(t, "jaw_open", t.mouth_open, t.mouth_neutral)
        case Action.TURN_LEFT:
            return HeadTurnDetector(t, "yaw", +1, step.yaw_deg)
        case Action.TURN_RIGHT:
            return HeadTurnDetector(t, "yaw", -1, step.yaw_deg)
        case Action.LOOK_UP:
            return HeadTurnDetector(t, "pitch", +1, step.pitch_deg)
        case Action.LOOK_DOWN:
            return HeadTurnDetector(t, "pitch", -1, step.pitch_deg)
        case Action.NOD:
            return NodDetector(t, step.pitch_deg)
        case Action.GAZE_LEFT:
            return GazeHorizontalDetector(t, +1)
        case Action.GAZE_RIGHT:
            return GazeHorizontalDetector(t, -1)
        case Action.GAZE_UP:
            return GazeVerticalDetector(t, up=True)
        case Action.GAZE_DOWN:
            return GazeVerticalDetector(t, up=False)
    raise ValueError(f"unsupported action {action}")


def create_challenge_detector(actions: Sequence[Action], step: StepParams, t: Thresholds):
    if len(actions) == 1:
        return create_detector(actions[0], step, t)
    return CompoundDetector([create_detector(a, step, t) for a in actions])
