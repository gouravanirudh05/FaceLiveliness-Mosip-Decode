"""Per-session policy from the caller (the Registration Client's configuration) overrides the YAML.

Each setting is checked by its effect: thresholds change the passive verdict, active settings change
the challenges actually issued, and invalid policies are rejected before any frame is processed.
"""

import json
import random

import grpc
import pytest

from active_liveness.config import apply_overrides, ConfigError
from active_liveness.events import ChallengePrompt, RetryAvailable
from active_liveness.grpc_gen import active_liveness_pb2 as apb
from active_liveness.types import Action, Workflow
from passive_liveness.grpc_gen import passive_liveness_pb2 as pb
from passive_liveness.grpc_gen import passive_liveness_pb2_grpc as pb_grpc
from passive_liveness.hybrid import (
    HybridLivenessSession, HybridReason, HybridStarted, HybridStatus, NextStep, PassiveVerdict, PolicyError,
    SessionPolicy,
)
from sim import StaticSubject
from test_10_hybrid import Runner, ScriptedAnalyzer


@pytest.fixture(scope="module")
def active_config(config):
    from active_liveness.config import load_config
    return load_config(config.hybrid.active_config)


@pytest.fixture
def run(make_engine, active_config, portrait):
    def go(score, policy=None, user=None, workflow=Workflow.RESIDENT):
        engine = make_engine(score)
        analyzer = ScriptedAnalyzer()
        session = HybridLivenessSession(engine, active_config, workflow, active_analyzer_factory=lambda: analyzer,
                                        rng=random.Random(3), policy=policy)
        runner = Runner(session, analyzer, user or __import__("sim").SimulatedUser(), active_config)
        runner.policy = session.policy.active          # scripts must follow the effective step timeouts
        return runner.run(portrait)
    return go


# ---------------------------------------------------------------- passive thresholds

def test_raising_the_accept_threshold_sends_a_good_score_to_challenges(run):
    assert run(0.85).decision.reason is HybridReason.PASSIVE_BONAFIDE                  # YAML: accept 0.80
    r = run(0.85, SessionPolicy(accept_threshold=0.95))
    assert r.of(PassiveVerdict)[0].next_step is NextStep.ACTIVE
    assert r.active(ChallengePrompt), "challenges were issued"


def test_raising_the_reject_threshold_turns_uncertain_into_attack(run):
    assert run(0.5).of(PassiveVerdict)[0].next_step is NextStep.ACTIVE                   # YAML: reject 0.40
    r = run(0.5, SessionPolicy(reject_threshold=0.6, accept_threshold=0.9))
    assert r.decision.reason is HybridReason.ATTACK_DETECTED and not r.active(ChallengePrompt)


def test_active_can_be_disabled_per_session(run):
    r = run(0.6, SessionPolicy(active_enabled=False))
    assert r.decision.status is HybridStatus.FAILED and r.decision.reason is HybridReason.ACTIVE_DISABLED


# ---------------------------------------------------------------- active policy

def test_challenge_pool_count_and_timeouts_are_applied(run):
    policy = SessionPolicy(challenge_pool=("blink", "smile", "turn_left", "nod"), min_challenges=4,
                           compound_challenges=False, step_timeouts_s=(10.0, 7.0))
    r = run(0.6, policy)
    prompts = r.active(ChallengePrompt)
    assert len(prompts) >= 4
    used = {a for p in prompts for a in p.actions}
    assert used <= {Action.BLINK, Action.SMILE, Action.TURN_LEFT, Action.NOD}
    assert all(len(p.actions) == 1 for p in prompts), "no compound challenges"
    assert [p.timeout_ms for p in prompts[:3]] == [10000, 7000, 7000]
    assert r.decision.status is HybridStatus.PASSED


def test_max_retries_is_applied(run):
    r = run(0.6, SessionPolicy(max_retries=1), user=StaticSubject())
    assert len(r.active(RetryAvailable)) == 1
    assert r.decision.reason is HybridReason.ACTIVE_FAILED


def test_fail_on_passive_no_response(make_engine, active_config, portrait):
    import numpy as np
    engine = make_engine(0.9, stream={"max_duration_ms": 800})
    s = HybridLivenessSession(engine, active_config, Workflow.OPERATOR, active_analyzer_factory=ScriptedAnalyzer,
                              policy=SessionPolicy(fail_on_passive_no_response=True))
    r = Runner(s, None, None, active_config).run(np.zeros_like(portrait))
    assert r.decision.reason is HybridReason.PASSIVE_NO_RESPONSE


def test_effective_policy_is_reported_at_start(make_engine, active_config):
    s = HybridLivenessSession(make_engine(0.9), active_config, Workflow.SUPERVISOR,
                              policy=SessionPolicy(accept_threshold=0.9, max_retries=0))
    started = s.start()[0]
    assert isinstance(started, HybridStarted)
    assert started.policy["accept_threshold"] == 0.9 and started.policy["max_retries"] == 0
    assert started.policy["reject_threshold"] == 0.40          # unchanged values come from the YAML
    s.close()


# ---------------------------------------------------------------- validation

@pytest.mark.parametrize("policy", [
    SessionPolicy(accept_threshold=0.3, reject_threshold=0.5),
    SessionPolicy(accept_threshold=1.5),
    SessionPolicy(challenge_pool=("blink", "jump")),
    SessionPolicy(challenge_pool=("blink", "blink")),
    SessionPolicy(min_challenges=0),
    SessionPolicy(step_timeouts_s=(5.0, 0.0)),
])
def test_invalid_policies_are_rejected(make_engine, active_config, policy):
    with pytest.raises(PolicyError):
        HybridLivenessSession(make_engine(0.9), active_config, Workflow.RESIDENT, policy=policy)


def test_apply_overrides_keeps_unset_values(active_config):
    base = active_config.policy_for(Workflow.RESIDENT)
    assert apply_overrides(base) is base
    p = apply_overrides(base, step_timeouts_s=[4.0])
    assert [s.timeout_s for s in p.steps] == [4.0] * len(base.steps)
    assert [s.yaw_deg for s in p.steps] == [s.yaw_deg for s in base.steps]
    with pytest.raises(ConfigError):
        apply_overrides(base, max_retries=-1)


# ---------------------------------------------------------------- over gRPC

def _start(stub, policy):
    def requests():
        yield pb.HybridClientMessage(start=pb.HybridStart(workflow=apb.WORKFLOW_RESIDENT, policy=policy))
    return list(stub.HybridSession(requests()))


@pytest.fixture
def grpc_server(make_engine):
    from passive_liveness.server import PassiveLivenessServicer, build_server
    engine = make_engine(0.9)
    server, port = build_server(engine.config, PassiveLivenessServicer(engine), address="127.0.0.1:0")
    server.start()
    yield f"127.0.0.1:{port}"
    server.stop(None)


def test_grpc_policy_round_trip_and_rejection(grpc_server):
    stub = pb_grpc.PassiveLivenessServiceStub(grpc.insecure_channel(grpc_server))
    out = _start(stub, pb.SessionPolicy(accept_threshold=0.9, challenge_pool=["blink", "smile"], max_retries=2))
    eff = json.loads(out[0].started.policy_json)
    assert eff["accept_threshold"] == pytest.approx(0.9) and eff["challenge_pool"] == ["blink", "smile"]
    assert eff["max_retries"] == 2

    bad = _start(stub, pb.SessionPolicy(challenge_pool=["jump"]))
    assert len(bad) == 1 and bad[0].error.code == pb.ERROR_INVALID_REQUEST
    assert "invalid policy" in bad[0].error.message
