"""Configuration model and YAML loader.

The YAML has three sections:

* ``service``   – gRPC binding and MediaPipe settings.
* ``policy``    – the default liveness policy applied to every workflow.
* ``workflows`` – optional per-workflow overrides (resident / operator / supervisor),
                  deep-merged on top of ``policy``.

Unknown keys are rejected so that typos never silently fall back to defaults.
"""

from __future__ import annotations

import copy
import dataclasses
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any, Mapping

import yaml

from .types import Action, Workflow


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class StepParams:
    """Strictness of one step in the challenge sequence."""

    timeout_s: float
    yaw_deg: float
    pitch_deg: float


@dataclass(frozen=True)
class Thresholds:
    blink_closed: float = 0.5        # eyeBlink score counted as "eyes closed"
    blink_open: float = 0.2          # eyeBlink score counted as "eyes open"
    smile: float = 0.5
    smile_neutral: float = 0.3
    mouth_open: float = 0.4          # jawOpen
    mouth_neutral: float = 0.15
    gaze_horizontal: float = 0.15    # iris offset change from baseline
    gaze_vertical: float = 0.3       # eyeLookUp/Down change from baseline
    head_still_deg: float = 8.0      # max head movement allowed during gaze challenges
    stability_deg: float = 3.0       # max angle spread while capturing the neutral baseline
    stability_gaze: float = 0.05     # max gaze spread while capturing the neutral baseline
    nod_return_ratio: float = 0.5    # nod completes once pitch is back within this fraction of the dip
    hold_frames: int = 3             # consecutive frames an action must be held
    neutral_frames: int = 3          # consecutive neutral frames before a challenge arms
    max_invalid_frames: int = 3      # consecutive no-face / multi-face frames before progress resets


@dataclass(frozen=True)
class Escalation:
    passive_weak_threshold: float = 0.5   # passive score below this adds a HARD challenge
    default_passive_score: float = 0.0    # used when the caller supplies no passive score
    weak_margin: float = 0.15             # a step passed with a smaller margin adds a HARD challenge
    max_extra_challenges: int = 2         # cap on challenges added by escalation per attempt


@dataclass(frozen=True)
class LivenessPolicy:
    enabled: bool
    min_challenges: int
    challenge_pool: tuple[Action, ...]
    compound_challenges: bool
    max_retries: int                      # retries allowed after the first attempt
    steps: tuple[StepParams, ...]
    escalation: Escalation
    thresholds: Thresholds

    @property
    def max_attempts(self) -> int:
        return 1 + self.max_retries

    def step_params(self, step_index: int) -> StepParams:
        return self.steps[min(step_index, len(self.steps) - 1)]


@dataclass(frozen=True)
class ServiceConfig:
    host: str
    port: int
    max_workers: int
    model_path: Path
    input_mirrored: bool
    max_faces: int


@dataclass(frozen=True)
class AppConfig:
    service: ServiceConfig
    policies: Mapping[Workflow, LivenessPolicy]

    def policy_for(self, workflow: Workflow) -> LivenessPolicy:
        return self.policies[workflow]


DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "default.yaml"


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> AppConfig:
    path = Path(path)
    try:
        raw = yaml.safe_load(path.read_text())
    except (OSError, yaml.YAMLError) as e:
        raise ConfigError(f"cannot read config {path}: {e}") from e
    return parse_config(raw, base_dir=path.parent)


def parse_config(raw: Any, base_dir: Path) -> AppConfig:
    raw = _mapping(raw, "config")
    _check_keys(raw, {"service", "policy", "workflows"}, "config")
    service = _parse_service(_mapping(raw.get("service"), "service"), base_dir)
    base_policy = _mapping(raw.get("policy"), "policy")
    overrides = _mapping(raw.get("workflows") or {}, "workflows")
    _check_keys(overrides, {w.value for w in Workflow}, "workflows")

    policies = {}
    for wf in Workflow:
        merged = _deep_merge(base_policy, _mapping(overrides.get(wf.value) or {}, f"workflows.{wf.value}"))
        policies[wf] = _parse_policy(merged, f"workflows.{wf.value}")
    return AppConfig(service=service, policies=policies)


def _parse_service(raw: Mapping[str, Any], base_dir: Path) -> ServiceConfig:
    keys = {"host", "port", "max_workers", "model_path", "input_mirrored", "max_faces"}
    _check_keys(raw, keys, "service", required=keys)
    model_path = Path(raw["model_path"])
    if not model_path.is_absolute():
        model_path = (base_dir / model_path).resolve()
    port = _int(raw["port"], "service.port", 1)
    if port > 65535:
        raise ConfigError("service.port must be <= 65535")
    max_faces = _int(raw["max_faces"], "service.max_faces", 2)
    return ServiceConfig(
        host=str(raw["host"]),
        port=port,
        max_workers=_int(raw["max_workers"], "service.max_workers", 1),
        model_path=model_path,
        input_mirrored=_bool(raw["input_mirrored"], "service.input_mirrored"),
        max_faces=max_faces,
    )


def _parse_policy(raw: Mapping[str, Any], where: str) -> LivenessPolicy:
    keys = {"enabled", "min_challenges", "challenge_pool", "compound_challenges",
            "max_retries", "steps", "escalation", "thresholds"}
    _check_keys(raw, keys, where, required=keys)

    pool_raw = raw["challenge_pool"]
    if not isinstance(pool_raw, list) or not pool_raw:
        raise ConfigError(f"{where}.challenge_pool must be a non-empty list")
    try:
        pool = tuple(Action(a) for a in pool_raw)
    except ValueError as e:
        raise ConfigError(f"{where}.challenge_pool: {e}; valid: {[a.value for a in Action]}") from e
    if len(set(pool)) != len(pool):
        raise ConfigError(f"{where}.challenge_pool contains duplicates")

    steps_raw = raw["steps"]
    if not isinstance(steps_raw, list) or not steps_raw:
        raise ConfigError(f"{where}.steps must be a non-empty list")
    steps = []
    for i, s in enumerate(steps_raw):
        s = _mapping(s, f"{where}.steps[{i}]")
        _check_keys(s, {"timeout_s", "yaw_deg", "pitch_deg"}, f"{where}.steps[{i}]",
                    required={"timeout_s", "yaw_deg", "pitch_deg"})
        steps.append(StepParams(**{k: _positive(s[k], f"{where}.steps[{i}].{k}") for k in s}))

    escalation = _dataclass_from(Escalation, _mapping(raw["escalation"], f"{where}.escalation"),
                                 f"{where}.escalation")
    for name in ("passive_weak_threshold", "default_passive_score"):
        if not 0.0 <= getattr(escalation, name) <= 1.0:
            raise ConfigError(f"{where}.escalation.{name} must be within [0, 1]")
    if escalation.max_extra_challenges < 0:
        raise ConfigError(f"{where}.escalation.max_extra_challenges must be >= 0")

    thresholds = _dataclass_from(Thresholds, _mapping(raw["thresholds"], f"{where}.thresholds"),
                                 f"{where}.thresholds")
    if thresholds.blink_open >= thresholds.blink_closed:
        raise ConfigError(f"{where}.thresholds.blink_open must be < blink_closed")
    if thresholds.smile_neutral >= thresholds.smile:
        raise ConfigError(f"{where}.thresholds.smile_neutral must be < smile")
    if thresholds.mouth_neutral >= thresholds.mouth_open:
        raise ConfigError(f"{where}.thresholds.mouth_neutral must be < mouth_open")

    return LivenessPolicy(
        enabled=_bool(raw["enabled"], f"{where}.enabled"),
        min_challenges=_int(raw["min_challenges"], f"{where}.min_challenges", 1),
        challenge_pool=pool,
        compound_challenges=_bool(raw["compound_challenges"], f"{where}.compound_challenges"),
        max_retries=_int(raw["max_retries"], f"{where}.max_retries", 0),
        steps=tuple(steps),
        escalation=escalation,
        thresholds=thresholds,
    )


def apply_overrides(
    policy: LivenessPolicy,
    *,
    enabled: bool | None = None,
    min_challenges: int | None = None,
    challenge_pool: list[str] | tuple[str, ...] | None = None,
    compound_challenges: bool | None = None,
    max_retries: int | None = None,
    step_timeouts_s: list[float] | tuple[float, ...] | None = None,
) -> LivenessPolicy:
    """A copy of ``policy`` with caller-supplied settings (e.g. from the Registration Client's
    configuration) applied. ``None`` / empty keeps the configured value. Validated like the YAML.

    ``step_timeouts_s[i]`` is the timeout of step position ``i``; later positions reuse the last
    entry, and yaw/pitch strictness of each position is kept (extra positions reuse the last step's).
    """
    where = "session policy"
    changes: dict[str, Any] = {}
    if enabled is not None:
        changes["enabled"] = _bool(enabled, f"{where}.enabled")
    if min_challenges is not None:
        changes["min_challenges"] = _int(min_challenges, f"{where}.min_challenges", 1)
    if challenge_pool:
        try:
            pool = tuple(Action(a) for a in challenge_pool)
        except ValueError as e:
            raise ConfigError(f"{where}.challenge_pool: {e}; valid: {[a.value for a in Action]}") from e
        if len(set(pool)) != len(pool):
            raise ConfigError(f"{where}.challenge_pool contains duplicates")
        changes["challenge_pool"] = pool
    if compound_challenges is not None:
        changes["compound_challenges"] = _bool(compound_challenges, f"{where}.compound_challenges")
    if max_retries is not None:
        changes["max_retries"] = _int(max_retries, f"{where}.max_retries", 0)
    if step_timeouts_s:
        timeouts = [_positive(t, f"{where}.step_timeouts_s[{i}]") for i, t in enumerate(step_timeouts_s)]
        n = max(len(timeouts), len(policy.steps))
        changes["steps"] = tuple(
            StepParams(timeout_s=timeouts[min(i, len(timeouts) - 1)],
                       yaw_deg=policy.step_params(i).yaw_deg,
                       pitch_deg=policy.step_params(i).pitch_deg)
            for i in range(n))
    return dataclasses.replace(policy, **changes) if changes else policy


# ---------------------------------------------------------------- helpers

def _dataclass_from(cls, raw: Mapping[str, Any], where: str):
    """Build a dataclass whose fields all have defaults; every key must be known."""
    types = {f.name: f.type for f in fields(cls)}
    _check_keys(raw, set(types), where)
    values = {}
    for k, v in raw.items():
        if types[k] in ("int", int):
            values[k] = _int(v, f"{where}.{k}", 0)
        else:
            values[k] = _positive(v, f"{where}.{k}", allow_zero=True)
    return cls(**values)


def _deep_merge(base: Mapping[str, Any], override: Mapping[str, Any]) -> dict:
    out = copy.deepcopy(dict(base))
    for k, v in override.items():
        if isinstance(v, Mapping) and isinstance(out.get(k), Mapping):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def _mapping(v: Any, where: str) -> Mapping[str, Any]:
    if not isinstance(v, Mapping):
        raise ConfigError(f"{where} must be a mapping")
    return v


def _check_keys(raw: Mapping[str, Any], allowed: set[str], where: str, required: set[str] = frozenset()):
    unknown = set(raw) - allowed
    if unknown:
        raise ConfigError(f"{where}: unknown keys {sorted(unknown)}")
    missing = required - set(raw)
    if missing:
        raise ConfigError(f"{where}: missing keys {sorted(missing)}")


def _bool(v: Any, where: str) -> bool:
    if not isinstance(v, bool):
        raise ConfigError(f"{where} must be true or false")
    return v


def _int(v: Any, where: str, minimum: int) -> int:
    if isinstance(v, bool) or not isinstance(v, int) or v < minimum:
        raise ConfigError(f"{where} must be an integer >= {minimum}")
    return v


def _positive(v: Any, where: str, allow_zero: bool = False) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ConfigError(f"{where} must be a number")
    if v < 0 or (v == 0 and not allow_zero):
        raise ConfigError(f"{where} must be {'>= 0' if allow_zero else '> 0'}")
    return float(v)
