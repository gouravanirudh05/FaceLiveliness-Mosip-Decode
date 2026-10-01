"""Hybrid passive -> active flow, plus the adapter for the active module's protocol.

Passive scores are set through fake models; the active phase is the real
ActiveLivenessSession, answered by the active module's SimulatedUser (its observations
are injected through a scripted analyzer, since challenge signals cannot be synthesised
from a still photo).
"""

import dataclasses
import random

import numpy as np
import pytest

from active_liveness.config import load_config as load_active_config
from active_liveness.events import ChallengePrompt, Decision as ActiveDecision, RetryAvailable
from active_liveness.passive import PassiveLivenessEngine as ActivePassiveProtocol
from active_liveness.types import Tier, Workflow
from conftest import Scores
from passive_liveness.adapter import ActivePassiveAdapter
from passive_liveness.hybrid import (
    ActiveEvent, HybridDecision, HybridLivenessSession, HybridReason, HybridStarted, HybridStatus,
    MonitorResult, NextStep, PassiveProgress, PassiveVerdict,
)
from sim import SimulatedUser, StaticSubject, obs

FRAME_MS = 40


class ScriptedAnalyzer:
    """Active-module analyzer that replays the SimulatedUser's signals for each prompt."""

    def __init__(self):
        self.pending: list[dict] = []
        self.idle: dict = {}
        self.closed = False

    def analyze(self, rgb, ts):
        return obs(ts, **(self.pending.pop(0) if self.pending else self.idle))

    def close(self):
        self.closed = True


@pytest.fixture(scope="module")
def active_config(config):
    return load_active_config(config.hybrid.active_config)


@pytest.fixture
def hybrid(make_engine, active_config):
    """hybrid(score, user=..., active_config=..., **passive config sections) -> runner"""

    def build(score, user=None, cfg=None, **sections):
        engine = make_engine(score, **sections)
        analyzer = ScriptedAnalyzer()
        session = HybridLivenessSession(engine, cfg or active_config, Workflow.RESIDENT,
                                        active_analyzer_factory=lambda: analyzer, rng=random.Random(7))
        return Runner(session, analyzer, user or SimulatedUser(), cfg or active_config)

    return build


class Runner:
    def __init__(self, session, analyzer, user, active_config):
        self.session, self.analyzer, self.user = session, analyzer, user
        self.policy = active_config.policy_for(Workflow.RESIDENT)
        self.events = []
        self.ts = 0

    def run(self, image, *, max_frames=5000, on_frame=None):
        s = self.session
        self.events += s.start()
        n = 0
        while s.status in (HybridStatus.PASSIVE, HybridStatus.ACTIVE):
            if s.retry_available:
                self.events += s.retry()
                self._scripts(self.events[-3:])
                continue
            self.ts += FRAME_MS
            img = image(n) if callable(image) else image
            new = s.process_frame(img, self.ts)
            self.events += new
            self._scripts(new)
            if on_frame:
                on_frame(self, n)
            n += 1
            assert n < max_frames, "session did not finish"
        return self

    def _scripts(self, new):
        for e in new:
            if isinstance(e, ActiveEvent) and isinstance(e.event, ChallengePrompt):
                self.analyzer.pending = list(self.user.frames_for(e.event, self.policy.step_params(e.event.step_index)))
                if isinstance(self.user, StaticSubject):
                    self.analyzer.idle = self.user.idle()

    def of(self, cls):
        return [e for e in self.events if isinstance(e, cls)]

    def active(self, cls):
        return [e.event for e in self.of(ActiveEvent) if isinstance(e.event, cls)]

    @property
    def decision(self) -> HybridDecision:
        return self.of(HybridDecision)[-1]


# ---------------------------------------------------------------- level 1: passive decides alone

def test_bona_fide_passes_without_challenges(hybrid, portrait):
    r = hybrid(0.95).run(portrait)
    kinds = [type(e).__name__ for e in r.events]
    assert kinds == ["HybridStarted"] + ["PassiveProgress"] * 5 + ["PassiveVerdict", "HybridDecision"]
    assert r.of(PassiveVerdict)[0].next_step is NextStep.ACCEPT
    d = r.decision
    assert d.status is HybridStatus.PASSED and d.reason is HybridReason.PASSIVE_BONAFIDE
    assert d.message == "Good, face captured successfully" and d.passive_score == pytest.approx(0.95)
    assert d.active_status is None


def test_attack_fails_without_challenges_or_revealing_why(hybrid, portrait):
    r = hybrid(0.1).run(portrait)
    assert not r.of(ActiveEvent)
    d = r.decision
    assert d.status is HybridStatus.FAILED and d.reason is HybridReason.ATTACK_DETECTED
    assert r.of(PassiveVerdict)[0].next_step is NextStep.REJECT
    for word in ("attack", "spoof", "fake", "photo"):
        assert word not in d.message.lower()


# ---------------------------------------------------------------- level 2: inconclusive -> active

def test_uncertain_passive_hands_over_to_active_and_passes(hybrid, portrait):
    r = hybrid(0.6).run(portrait)
    assert r.of(PassiveVerdict)[0].next_step is NextStep.ACTIVE
    assert r.session.active.passive_score == pytest.approx(0.6)
    prompts = r.active(ChallengePrompt)
    assert [p.tier for p in prompts] == [Tier.EASY, Tier.MEDIUM, Tier.HARD]       # 0.6 is not weak
    d = r.decision
    assert d.status is HybridStatus.PASSED and d.reason is HybridReason.ACTIVE_PASSED
    assert d.active_status == "passed" and d.passive_score == pytest.approx(0.6)
    assert r.analyzer.closed


def test_weak_passive_score_makes_the_challenges_harder(hybrid, portrait):
    r = hybrid(0.45).run(portrait)
    assert [p.tier for p in r.active(ChallengePrompt)] == [Tier.EASY, Tier.MEDIUM, Tier.HARD, Tier.HARD]
    assert r.decision.status is HybridStatus.PASSED


def test_failing_the_challenges_retries_harder_then_fails(hybrid, portrait, active_config):
    r = hybrid(0.6, user=StaticSubject()).run(portrait)
    retries = r.active(RetryAvailable)
    assert len(retries) == r.policy.max_retries
    first_tiers = {}
    for p in r.active(ChallengePrompt):
        first_tiers.setdefault(p.attempt, p.tier)
    assert first_tiers[1] is Tier.EASY and first_tiers[2] is Tier.MEDIUM and first_tiers[3] is Tier.HARD
    d = r.decision
    assert d.status is HybridStatus.FAILED and d.reason is HybridReason.ACTIVE_FAILED
    assert r.active(ActiveDecision)[-1].message == d.message


# ---------------------------------------------------------------- level 3: passive cannot decide

def test_no_usable_frames_goes_to_active_without_a_score(hybrid, portrait):
    blank = np.zeros_like(portrait)
    r = hybrid(0.9, stream={"max_duration_ms": 800}).run(blank)
    v = r.of(PassiveVerdict)[0]
    assert v.result.decision.value == "non_response" and v.next_step is NextStep.ACTIVE
    assert r.session.active.passive_score is None
    # no score -> active module's default (weak) -> one extra HARD challenge
    assert [p.tier for p in r.active(ChallengePrompt)][:4] == [Tier.EASY, Tier.MEDIUM, Tier.HARD, Tier.HARD]
    assert r.decision.status is HybridStatus.PASSED and r.decision.passive_score is None


def test_no_usable_frames_can_be_configured_to_fail(hybrid, portrait):
    r = hybrid(0.9, stream={"max_duration_ms": 800}, hybrid={"on_passive_no_response": "fail"}).run(
        np.zeros_like(portrait))
    assert not r.of(ActiveEvent)
    assert r.decision.reason is HybridReason.PASSIVE_NO_RESPONSE


def test_inconclusive_with_challenges_disabled_fails(hybrid, portrait, active_config):
    policies = dict(active_config.policies)
    policies[Workflow.RESIDENT] = dataclasses.replace(policies[Workflow.RESIDENT], enabled=False)
    cfg = dataclasses.replace(active_config, policies=policies)
    r = hybrid(0.6, cfg=cfg).run(portrait)
    assert r.decision.reason is HybridReason.ACTIVE_DISABLED and r.decision.status is HybridStatus.FAILED
    # a bona fide passive result still passes on its own
    assert hybrid(0.95, cfg=cfg).run(portrait).decision.status is HybridStatus.PASSED


# ---------------------------------------------------------------- level 4: monitoring during challenges

def test_attack_appearing_during_challenges_ends_the_session(hybrid, portrait):
    score = Scores(0.6)

    def swap_in_attack(runner, n):
        if runner.session.status is HybridStatus.ACTIVE:
            score.value = 0.1

    r = hybrid(score, user=StaticSubject()).run(portrait, on_frame=swap_in_attack)
    monitors = r.of(MonitorResult)
    assert [m.consecutive_attacks for m in monitors][-2:] == [1, 2]
    gap = monitors[-1].frame.timestamp_ms - monitors[-2].frame.timestamp_ms
    assert gap >= 1000                                                     # monitor_interval_ms
    d = r.decision
    assert d.status is HybridStatus.FAILED and d.reason is HybridReason.ATTACK_DETECTED_DURING_ACTIVE


def test_monitoring_can_be_switched_off(hybrid, portrait):
    r = hybrid(0.6, hybrid={"monitor_during_active": False}).run(portrait)
    assert not r.of(MonitorResult) and r.decision.status is HybridStatus.PASSED


def test_live_user_is_monitored_without_interference(hybrid, portrait):
    r = hybrid(0.6).run(portrait)
    assert r.of(MonitorResult) and all(m.consecutive_attacks == 0 for m in r.of(MonitorResult))


# ---------------------------------------------------------------- level 5: control

def test_cancel_during_challenges(hybrid, portrait):
    def cancel_on_second_prompt(runner, n):
        if len(runner.active(ChallengePrompt)) == 2 and runner.session.status is HybridStatus.ACTIVE:
            runner.events += runner.session.cancel()

    r = hybrid(0.6).run(portrait, on_frame=cancel_on_second_prompt)
    assert r.decision.status is HybridStatus.CANCELLED
    assert r.active(ActiveDecision)[-1].status.value == "cancelled"


def test_state_errors(hybrid, portrait):
    r = hybrid(0.6)
    with pytest.raises(RuntimeError):
        r.session.process_frame(portrait, 40)
    r.session.start()
    with pytest.raises(RuntimeError):
        r.session.retry()
    with pytest.raises(RuntimeError):
        r.session.start()
    r.session.cancel()
    with pytest.raises(RuntimeError):
        r.session.cancel()


# ---------------------------------------------------------------- adapter for the active module

def test_adapter_implements_the_active_protocol(make_engine, portrait):
    adapter = ActivePassiveAdapter(make_engine(0.62, stream={"frames_required": 3, "min_frame_interval_ms": 0}))
    assert isinstance(adapter, ActivePassiveProtocol)
    adapter.start()
    results = [adapter.process_frame(portrait, FRAME_MS * (i + 1)) for i in range(3)]
    assert results[:2] == [None, None]
    r = results[2]
    assert r.score == pytest.approx(0.62) and r.attack_detected is False
    assert r.details["decision"] == "uncertain"


def test_adapter_attack_and_non_response(make_engine, portrait):
    adapter = ActivePassiveAdapter(make_engine(0.1, stream={"frames_required": 1}))
    adapter.start()
    assert adapter.process_frame(portrait, 40).attack_detected is True
    adapter = ActivePassiveAdapter(make_engine(0.9, stream={"frames_required": 2, "max_duration_ms": 100}))
    adapter.start()
    blank = np.zeros_like(portrait)
    r = None
    for i in range(10):
        r = adapter.process_frame(blank, FRAME_MS * (i + 1)) or r
        if r:
            break
    assert r.score == 0.0 and r.attack_detected is False and r.details["decision"] == "non_response"
    with pytest.raises(RuntimeError):
        adapter.process_frame(blank, 9999)
