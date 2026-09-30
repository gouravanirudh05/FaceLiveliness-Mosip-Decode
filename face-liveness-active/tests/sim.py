"""Synthetic face signals for deterministic tests.

`SimulatedUser` reads each ChallengePrompt and produces the per-frame signals a
person performing those actions would produce (in the FaceObservation space the
MediaPipe analyzer outputs). Its knobs model weak, slow, wrong or absent responses.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field

from active_liveness.config import StepParams
from active_liveness.events import ChallengePrompt, ChallengeResult, Decision, RetryAvailable
from active_liveness.session import ActiveLivenessSession, SessionStatus
from active_liveness.types import Action, FaceObservation

FRAME_MS = 40  # 25 fps

NEUTRAL = dict(yaw=0.0, pitch=0.0, gaze_h=0.0, blink=0.05, smile=0.05, jaw=0.02, gaze_up=0.05, gaze_down=0.05)


def obs(ts: int, face_count: int = 1, **f) -> FaceObservation:
    """Build an observation from simple named signals (missing ones are neutral)."""
    s = {**NEUTRAL, **f}
    return FaceObservation(
        timestamp_ms=ts,
        face_count=face_count,
        blendshapes={
            "eyeBlinkLeft": s["blink"], "eyeBlinkRight": s["blink"],
            "mouthSmileLeft": s["smile"], "mouthSmileRight": s["smile"],
            "jawOpen": s["jaw"],
            "eyeLookUpLeft": s["gaze_up"], "eyeLookUpRight": s["gaze_up"],
            "eyeLookDownLeft": s["gaze_down"], "eyeLookDownRight": s["gaze_down"],
        } if face_count == 1 else {},
        yaw_deg=s["yaw"] if face_count == 1 else 0.0,
        pitch_deg=s["pitch"] if face_count == 1 else 0.0,
        gaze_horizontal=s["gaze_h"] if face_count == 1 else 0.0,
    )


class Clock:
    def __init__(self, start_ms: int = 0):
        self.t = start_ms

    def next(self) -> int:
        self.t += FRAME_MS
        return self.t


def feed(detector, frames: list[dict], clock: Clock | None = None):
    """Feed signal dicts to a detector; return the list of updates."""
    clock = clock or Clock()
    return [detector.update(obs(clock.next(), **f)) for f in frames]


def hold(n: int, **f) -> list[dict]:
    return [dict(f) for _ in range(n)]


def ramp(n: int, start: dict, end: dict) -> list[dict]:
    out = []
    for i in range(1, n + 1):
        k = i / n
        out.append({key: start.get(key, NEUTRAL[key]) + (end.get(key, NEUTRAL[key]) - start.get(key, NEUTRAL[key])) * k
                    for key in set(start) | set(end)})
    return out


@dataclass
class SimulatedUser:
    """A cooperative live person, parameterised to be weaker/slower/wrong as needed."""

    reaction_frames: int = 6          # neutral frames before starting each action
    ramp_frames: int = 3
    hold_frames: int = 5
    yaw_deg: float | None = None      # absolute head-turn amplitude; None => 1.5 x required
    pitch_deg: float | None = None
    expression: float = 0.85          # smile / jaw / blink peak
    gaze_h: float = 0.35
    gaze_v: float = 0.7
    wrong_direction: bool = False
    extra_delay_frames: int = 0       # hesitation before every action (a slow user)

    def frames_for(self, prompt: ChallengePrompt, step: StepParams) -> list[dict]:
        frames: list[dict] = []
        for action in prompt.actions:
            frames += hold(self.reaction_frames + self.extra_delay_frames)
            frames += self._perform(action, step)
        return frames + hold(3)

    def _perform(self, a: Action, step: StepParams) -> list[dict]:
        yaw = self.yaw_deg if self.yaw_deg is not None else step.yaw_deg * 1.5
        pitch = self.pitch_deg if self.pitch_deg is not None else step.pitch_deg * 1.5
        sign = -1 if self.wrong_direction else 1
        target = {
            Action.SMILE: dict(smile=self.expression),
            Action.OPEN_MOUTH: dict(jaw=self.expression),
            Action.TURN_LEFT: dict(yaw=sign * yaw),
            Action.TURN_RIGHT: dict(yaw=-sign * yaw),
            Action.LOOK_UP: dict(pitch=sign * pitch),
            Action.LOOK_DOWN: dict(pitch=-sign * pitch),
            Action.GAZE_LEFT: dict(gaze_h=sign * self.gaze_h),
            Action.GAZE_RIGHT: dict(gaze_h=-sign * self.gaze_h),
            Action.GAZE_UP: dict(gaze_up=self.gaze_v) if sign > 0 else dict(gaze_down=self.gaze_v),
            Action.GAZE_DOWN: dict(gaze_down=self.gaze_v) if sign > 0 else dict(gaze_up=self.gaze_v),
        }
        if a is Action.BLINK:
            return hold(2, blink=self.expression)
        if a is Action.NOD:
            down = dict(pitch=-pitch)
            return ramp(self.ramp_frames, {}, down) + hold(2, **down) + ramp(self.ramp_frames, down, {})
        t = target[a]
        return ramp(self.ramp_frames, {}, t) + hold(self.hold_frames, **t) + ramp(self.ramp_frames, t, {})


@dataclass
class StaticSubject(SimulatedUser):
    """A printed photo / frozen screen: the same signals every frame, whatever is asked."""

    signals: dict = field(default_factory=lambda: dict(smile=0.7))

    def frames_for(self, prompt, step):
        return hold(10, **self.signals)

    def idle(self):
        return dict(self.signals)


@dataclass
class Transcript:
    events: list = field(default_factory=list)
    client: list = field(default_factory=list)     # ("frame", FaceObservation) | ("retry",)

    def of(self, cls):
        return [e for e in self.events if isinstance(e, cls)]

    @property
    def prompts(self) -> list[ChallengePrompt]:
        return self.of(ChallengePrompt)

    @property
    def decision(self) -> Decision | None:
        d = self.of(Decision)
        return d[-1] if d else None


def drive(session: ActiveLivenessSession, user: SimulatedUser, *, retry: bool = True,
          clock: Clock | None = None, max_frames: int = 20_000) -> Transcript:
    """Run a whole session: answer every prompt with `user`, retry when allowed."""
    clock = clock or Clock()
    tr = Transcript()
    tr.events += session.start()
    frames_sent = 0
    while session.status is SessionStatus.RUNNING:
        prompt = tr.prompts[-1]
        step = session.policy.step_params(prompt.step_index)
        pending = list(user.frames_for(prompt, step))
        idle = user.idle() if isinstance(user, StaticSubject) else {}
        while session.status is SessionStatus.RUNNING:
            f = pending.pop(0) if pending else idle
            o = obs(clock.next(), **f)
            tr.client.append(("frame", o))
            new = session.process_observation(o)
            tr.events += new
            frames_sent += 1
            if frames_sent > max_frames:
                raise AssertionError("session did not finish")
            if any(isinstance(e, (ChallengePrompt, RetryAvailable, Decision)) for e in new):
                break
        if session.status is SessionStatus.RETRY_AVAILABLE and retry:
            tr.client.append(("retry",))
            tr.events += session.retry()
    return tr


def step_results(tr: Transcript, attempt: int | None = None) -> list[ChallengeResult]:
    return [r for r in tr.of(ChallengeResult) if attempt is None or r.attempt == attempt]


def replace_policy(policy, **changes):
    """dataclasses.replace that also accepts escalation__x / thresholds__x keys."""
    nested: dict[str, dict] = {}
    flat = {}
    for k, v in changes.items():
        if "__" in k:
            outer, inner = k.split("__", 1)
            nested.setdefault(outer, {})[inner] = v
        else:
            flat[k] = v
    for outer, vals in nested.items():
        flat[outer] = dataclasses.replace(getattr(policy, outer), **vals)
    return dataclasses.replace(policy, **flat)
