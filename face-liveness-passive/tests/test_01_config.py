"""Configuration loading and validation."""

from pathlib import Path

import pytest
import yaml

from passive_liveness.config import ConfigError, PassiveConfig, load_config, parse_config, replace

from conftest import ROOT


def test_default_config_loads_and_resolves_paths(config):
    assert config.models.dir == (ROOT / "models").resolve()
    assert config.face.landmarker_path == (ROOT / "models" / "face_landmarker.task").resolve()
    assert config.face.landmarker_path.is_file()
    assert config.hybrid.active_config == (ROOT.parent / "face-liveness-active" / "config" / "default.yaml").resolve()
    assert config.decision.reject_threshold < config.decision.accept_threshold
    assert config.models.unified.enabled and config.models.fas.enabled


def test_empty_file_gives_defaults(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("")
    assert load_config(p) == PassiveConfig()


def test_missing_file(tmp_path):
    with pytest.raises(ConfigError, match="cannot read"):
        load_config(tmp_path / "nope.yaml")


def test_relative_paths_resolve_against_the_config_file(tmp_path):
    cfg = parse_config({"models": {"dir": "weights"}}, base_dir=tmp_path)
    assert cfg.models.dir == (tmp_path / "weights").resolve()


@pytest.mark.parametrize("raw, match", [
    ({"modles": {}}, "unknown keys"),
    ({"stream": {"frames_requried": 3}}, "unknown keys"),
    ({"stream": {"frames_required": "5"}}, "must be an integer"),
    ({"stream": {"frames_required": 0}}, "frames_required"),
    ({"quality": {"enforce": "yes"}}, "true or false"),
    ({"decision": {"accept_threshold": 0.3, "reject_threshold": 0.5}}, "reject_threshold <= accept_threshold"),
    ({"decision": {"accept_threshold": 1.5}}, "accept_threshold <= 1"),
    ({"stream": {"aggregation": "max"}}, "aggregation"),
    ({"hybrid": {"on_passive_no_response": "ignore"}}, "on_passive_no_response"),
    ({"models": {"unified": {"enabled": False}, "fas": {"enabled": False}}}, "at least one"),
    ({"models": {"fas": {"weight": 0}}}, "weight"),
    ({"models": {"fas": {"sha256": "abc"}}}, "64 hex"),
    ({"quality": {"min_brightness": 200, "max_brightness": 100}}, "min_brightness"),
    ({"stream": 5}, "must be a mapping"),
])
def test_invalid_values_are_rejected(raw, match):
    with pytest.raises(ConfigError, match=match):
        parse_config(raw, base_dir=Path("."))


def test_replace_validates(config):
    assert replace(config, stream={"frames_required": 2}).stream.frames_required == 2
    with pytest.raises(ConfigError):
        replace(config, decision={"accept_threshold": 0.1})


def test_default_yaml_has_no_unused_sections():
    raw = yaml.safe_load((ROOT / "config" / "default.yaml").read_text())
    assert set(raw) == {f for f in PassiveConfig.__dataclass_fields__}


def test_partial_model_override_keeps_the_other_fields(tmp_path):
    cfg = parse_config({"models": {"fas": {"weight": 2.0}}}, base_dir=tmp_path)
    assert cfg.models.fas.weight == 2.0
    assert cfg.models.fas.file == "fsfm_fas_mcio_vitb16.pth"
