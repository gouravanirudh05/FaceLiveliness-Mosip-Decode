import copy
from pathlib import Path

import pytest
import yaml

from active_liveness.config import ConfigError, StepParams, parse_config
from active_liveness.types import Action, Workflow

from conftest import ROOT

RAW = yaml.safe_load((ROOT / "config" / "default.yaml").read_text())


def parse(mutate=None):
    raw = copy.deepcopy(RAW)
    if mutate:
        mutate(raw)
    return parse_config(raw, base_dir=ROOT / "config")


def test_default_config_values(app_config):
    p = app_config.policy_for(Workflow.RESIDENT)
    assert p.enabled and p.min_challenges == 3 and p.max_retries == 3 and p.max_attempts == 4
    assert p.steps == (StepParams(8, 15, 10), StepParams(6, 20, 12), StepParams(5, 25, 15))
    assert set(p.challenge_pool) == set(Action)
    assert p.escalation.passive_weak_threshold == 0.5
    assert app_config.service.host == "127.0.0.1" and app_config.service.port == 50051
    assert app_config.service.model_path.is_file()


def test_all_workflows_get_a_policy(app_config):
    assert set(app_config.policies) == set(Workflow)


def test_later_steps_reuse_last_step_params(policy):
    assert policy.step_params(2) == policy.step_params(7) == StepParams(5, 25, 15)


def test_workflow_override_is_deep_merged():
    def m(raw):
        raw["workflows"]["supervisor"] = {"min_challenges": 4, "escalation": {"weak_margin": 0.3}}
    cfg = parse(m)
    sup, res = cfg.policy_for(Workflow.SUPERVISOR), cfg.policy_for(Workflow.RESIDENT)
    assert sup.min_challenges == 4 and res.min_challenges == 3
    assert sup.escalation.weak_margin == 0.3
    assert sup.escalation.passive_weak_threshold == res.escalation.passive_weak_threshold  # untouched sibling


def test_relative_model_path_resolves_against_config_dir():
    cfg = parse()
    assert cfg.service.model_path == (ROOT / "models" / "face_landmarker.task").resolve()


@pytest.mark.parametrize("mutate, message", [
    (lambda r: r["policy"].update(unknown_key=1), "unknown keys"),
    (lambda r: r["policy"]["thresholds"].update(blnk_closed=0.5), "unknown keys"),
    (lambda r: r["policy"].update(challenge_pool=["blink", "wink"]), "challenge_pool"),
    (lambda r: r["policy"].update(challenge_pool=[]), "non-empty"),
    (lambda r: r["policy"].update(challenge_pool=["blink", "blink"]), "duplicates"),
    (lambda r: r["policy"].update(min_challenges=0), "min_challenges"),
    (lambda r: r["policy"].update(max_retries=-1), "max_retries"),
    (lambda r: r["policy"].update(enabled="yes"), "enabled"),
    (lambda r: r["policy"].update(steps=[]), "steps"),
    (lambda r: r["policy"]["steps"][0].update(timeout_s=0), "timeout_s"),
    (lambda r: r["policy"]["thresholds"].update(blink_open=0.6), "blink_open"),
    (lambda r: r["policy"]["escalation"].update(passive_weak_threshold=1.5), "passive_weak_threshold"),
    (lambda r: r["service"].update(port=70000), "port"),
    (lambda r: r["service"].pop("host"), "missing keys"),
    (lambda r: r["workflows"].update(auditor={}), "unknown keys"),
])
def test_invalid_config_is_rejected(mutate, message):
    with pytest.raises(ConfigError, match=message):
        parse(mutate)


def test_load_missing_file_raises_config_error(tmp_path: Path):
    from active_liveness.config import load_config
    with pytest.raises(ConfigError):
        load_config(tmp_path / "nope.yaml")
