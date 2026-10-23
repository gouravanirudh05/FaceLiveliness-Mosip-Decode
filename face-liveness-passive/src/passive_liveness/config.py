"""Configuration model and YAML loader.

Every section maps onto a frozen dataclass. Unknown keys are rejected so that a typo
never silently falls back to a default; missing keys take the dataclass default.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping
import os
import sys
import yaml

def _root() -> Path:
    """Directory holding ``config/`` and ``models/``: ``PASSIVE_LIVENESS_HOME``, else the
    PyInstaller bundle, else the source checkout."""
    env = os.environ.get("PASSIVE_LIVENESS_HOME")
    if env:
        return Path(env).resolve()
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle:
        return Path(bundle)
    return Path(__file__).resolve().parents[2]


ROOT = _root()
DEFAULT_CONFIG_PATH = ROOT / "config" / "default.yaml"


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class ModelEntry:
    enabled: bool = True
    file: str = ""
    sha256: str = ""
    weight: float = 0.5


@dataclass(frozen=True)
class ModelsConfig:
    dir: Path = ROOT / "models"
    torch_threads: int = 0
    verify_sha256: bool = False
    unified: ModelEntry = ModelEntry(file="fsfm_unified_4class_vitb16.pth")
    fas: ModelEntry = ModelEntry(file="fsfm_fas_mcio_vitb16.pth")

    def path(self, entry: ModelEntry) -> Path:
        return self.dir / entry.file


@dataclass(frozen=True)
class FaceConfig:
    landmarker_path: Path = ROOT / "models" / "face_landmarker.task"
    max_faces: int = 2
    crop_scale: float = 1.17


@dataclass(frozen=True)
class QualityConfig:
    enforce: bool = True
    min_face_px: int = 96
    min_sharpness: float = 15.0
    min_brightness: float = 40.0
    max_brightness: float = 220.0
    max_abs_yaw_deg: float = 35.0
    max_abs_pitch_deg: float = 30.0
    max_crop_clip: float = 0.20


@dataclass(frozen=True)
class DecisionConfig:
    accept_threshold: float = 0.80
    reject_threshold: float = 0.40


@dataclass(frozen=True)
class StreamConfig:
    frames_required: int = 5
    min_frame_interval_ms: int = 150
    max_duration_ms: int = 10000
    aggregation: str = "mean"


@dataclass(frozen=True)
class CuesConfig:
    enabled: bool = True


@dataclass(frozen=True)
class ExplainConfig:
    gradcam: bool = False


@dataclass(frozen=True)
class ServiceConfig:
    host: str = "127.0.0.1"
    port: int = 50052
    max_workers: int = 4
    max_message_mb: int = 64


@dataclass(frozen=True)
class HybridConfig:
    active_config: Path | None = None
    on_passive_no_response: str = "active"
    monitor_during_active: bool = True
    monitor_interval_ms: int = 1000
    monitor_attack_frames: int = 2


@dataclass(frozen=True)
class PassiveConfig:
    models: ModelsConfig = field(default_factory=ModelsConfig)
    face: FaceConfig = field(default_factory=FaceConfig)
    quality: QualityConfig = field(default_factory=QualityConfig)
    decision: DecisionConfig = field(default_factory=DecisionConfig)
    stream: StreamConfig = field(default_factory=StreamConfig)
    cues: CuesConfig = field(default_factory=CuesConfig)
    explain: ExplainConfig = field(default_factory=ExplainConfig)
    service: ServiceConfig = field(default_factory=ServiceConfig)
    hybrid: HybridConfig = field(default_factory=HybridConfig)


AGGREGATIONS = ("mean", "median", "min")
NO_RESPONSE_POLICIES = ("active", "fail")


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> PassiveConfig:
    path = Path(path)
    try:
        raw = yaml.safe_load(path.read_text())
    except (OSError, yaml.YAMLError) as e:
        raise ConfigError(f"cannot read config {path}: {e}") from e
    return parse_config(raw or {}, base_dir=path.parent)


def parse_config(raw: Any, base_dir: Path) -> PassiveConfig:
    cfg = _section(raw, PassiveConfig(), "config", base_dir)
    _validate(cfg)
    return cfg


def replace(cfg: PassiveConfig, **sections: Mapping[str, Any]) -> PassiveConfig:
    """Copy of ``cfg`` with some fields changed, e.g. ``replace(cfg, stream={"frames_required": 3})``."""
    changed = {}
    for name, values in sections.items():
        current = getattr(cfg, name)
        changed[name] = dataclasses.replace(current, **values)
    out = dataclasses.replace(cfg, **changed)
    _validate(out)
    return out


# ------------------------------------------------------------------ parsing

def _section(raw: Any, defaults: Any, where: str, base_dir: Path):
    """Overlay the keys in ``raw`` on the dataclass instance ``defaults``."""
    if not isinstance(raw, Mapping):
        raise ConfigError(f"{where} must be a mapping")
    cls = type(defaults)
    allowed = {f.name for f in dataclasses.fields(cls)}
    unknown = set(raw) - allowed
    if unknown:
        raise ConfigError(f"{where}: unknown keys {sorted(unknown)}")
    values = {}
    for name, value in raw.items():
        default = getattr(defaults, name)
        values[name] = _coerce(value, default, f"{where}.{name}", base_dir, cls, name)
    return dataclasses.replace(defaults, **values)


def _coerce(value: Any, default: Any, where: str, base_dir: Path, cls: type, name: str):
    if dataclasses.is_dataclass(default):
        return _section(value, default, where, base_dir)
    if isinstance(default, bool):
        if not isinstance(value, bool):
            raise ConfigError(f"{where} must be true or false")
        return value
    if isinstance(default, int):
        if isinstance(value, bool) or not isinstance(value, int):
            raise ConfigError(f"{where} must be an integer")
        return value
    if isinstance(default, float):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ConfigError(f"{where} must be a number")
        return float(value)
    if isinstance(default, Path) or (cls is HybridConfig and name == "active_config"):
        if value is None:
            return None
        if not isinstance(value, str):
            raise ConfigError(f"{where} must be a path")
        p = Path(value)
        return (p if p.is_absolute() else base_dir / p).resolve()
    if isinstance(default, str):
        if not isinstance(value, str):
            raise ConfigError(f"{where} must be a string")
        return value
    raise ConfigError(f"{where}: unsupported value")


def _validate(c: PassiveConfig) -> None:
    def check(ok: bool, msg: str):
        if not ok:
            raise ConfigError(msg)

    m = c.models
    check(m.torch_threads >= 0, "models.torch_threads must be >= 0")
    check(m.unified.enabled or m.fas.enabled, "models: at least one of unified / fas must be enabled")
    for name in ("unified", "fas"):
        e: ModelEntry = getattr(m, name)
        check(bool(e.file), f"models.{name}.file must be set")
        check(e.weight > 0, f"models.{name}.weight must be > 0")
        check(not e.sha256 or len(e.sha256) == 64, f"models.{name}.sha256 must be 64 hex characters")
    check(c.face.max_faces >= 1, "face.max_faces must be >= 1")
    check(c.face.crop_scale > 0.5, "face.crop_scale must be > 0.5")
    q = c.quality
    check(q.min_face_px >= 16, "quality.min_face_px must be >= 16")
    check(q.min_sharpness >= 0, "quality.min_sharpness must be >= 0")
    check(0 <= q.min_brightness < q.max_brightness <= 255, "quality: need 0 <= min_brightness < max_brightness <= 255")
    check(0 < q.max_abs_yaw_deg <= 90 and 0 < q.max_abs_pitch_deg <= 90, "quality: pose limits must be in (0, 90]")
    check(0 <= q.max_crop_clip < 1, "quality.max_crop_clip must be in [0, 1)")
    d = c.decision
    check(0 <= d.reject_threshold <= d.accept_threshold <= 1,
          "decision: need 0 <= reject_threshold <= accept_threshold <= 1")
    s = c.stream
    check(s.frames_required >= 1, "stream.frames_required must be >= 1")
    check(s.min_frame_interval_ms >= 0, "stream.min_frame_interval_ms must be >= 0")
    check(s.max_duration_ms > 0, "stream.max_duration_ms must be > 0")
    check(s.aggregation in AGGREGATIONS, f"stream.aggregation must be one of {AGGREGATIONS}")
    sv = c.service
    check(1 <= sv.port <= 65535 or sv.port == 0, "service.port must be 0..65535")
    check(sv.max_workers >= 1 and sv.max_message_mb >= 1, "service: max_workers and max_message_mb must be >= 1")
    h = c.hybrid
    check(h.on_passive_no_response in NO_RESPONSE_POLICIES,
          f"hybrid.on_passive_no_response must be one of {NO_RESPONSE_POLICIES}")
    check(h.monitor_interval_ms >= 0 and h.monitor_attack_frames >= 1,
          "hybrid: monitor_interval_ms >= 0 and monitor_attack_frames >= 1")
