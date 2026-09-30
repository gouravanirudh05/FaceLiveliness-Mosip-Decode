"""Dynamic challenge selection and escalation planning."""

import random

import pytest

from active_liveness.challenges import TIER_OF, Challenge, ChallengePlanner
from active_liveness.types import Action, Tier

from sim import replace_policy

E, M, H = Tier.EASY, Tier.MEDIUM, Tier.HARD
STRONG = 0.9   # a passive score that does not trigger escalation


def planner(policy, **changes):
    return ChallengePlanner(replace_policy(policy, **changes), random.Random(7))


# ---------------------------------------------------------------- tier plan

@pytest.mark.parametrize("n, expected", [(1, [E]), (2, [E, M]), (3, [E, M, H]), (5, [E, M, H, H, H])])
def test_base_sequence_gets_harder(policy, n, expected):
    assert planner(policy, min_challenges=n).tiers_for_attempt(0, STRONG) == expected


@pytest.mark.parametrize("attempt, expected", [(0, [E, M, H]), (1, [M, H, H]), (2, [H, H, H]), (6, [H, H, H])])
def test_each_retry_starts_one_tier_harder(policy, attempt, expected):
    assert planner(policy).tiers_for_attempt(attempt, STRONG) == expected


@pytest.mark.parametrize("score, expected", [
    (0.9, [E, M, H]),
    (0.5, [E, M, H]),         # at the threshold is not weak
    (0.49, [E, M, H, H]),
    (0.0, [E, M, H, H]),
    (None, [E, M, H, H]),     # absent => default_passive_score (0.0) => weak
])
def test_weak_passive_score_adds_a_hard_challenge(policy, score, expected):
    assert planner(policy).tiers_for_attempt(0, score) == expected


def test_passive_escalation_respects_extra_cap(policy):
    p = planner(policy, escalation__max_extra_challenges=0)
    assert p.tiers_for_attempt(0, 0.1) == [E, M, H]


def test_absent_passive_score_uses_configured_default(policy):
    p = planner(policy, escalation__default_passive_score=0.8)
    assert p.tiers_for_attempt(0, None) == [E, M, H]


# ---------------------------------------------------------------- selection

@pytest.mark.parametrize("tier", list(Tier))
def test_pick_returns_requested_tier(policy, tier):
    p = planner(policy)
    for _ in range(50):
        c = p.pick(tier, set())
        assert c.tier is tier
        if len(c.actions) == 1:
            assert TIER_OF[c.actions[0]] is tier


def test_compound_is_two_distinct_easy_or_medium_actions(policy):
    p = planner(policy, challenge_pool=[Action.BLINK, Action.TURN_LEFT, Action.SMILE])
    c = p.pick(H, set())  # no single HARD actions in pool => must be compound
    assert c.tier is H and len(c.actions) == 2 and len(set(c.actions)) == 2
    assert all(TIER_OF[a] in (E, M) for a in c.actions)


def test_compound_can_be_disabled(policy):
    p = planner(policy, compound_challenges=False)
    assert all(len(p.pick(H, set()).actions) == 1 for _ in range(50))


def test_no_action_repeats_within_an_attempt(policy):
    for seed in range(200):
        p = ChallengePlanner(policy, random.Random(seed))
        used: set[Action] = set()
        for tier in p.tiers_for_attempt(0, None):
            c = p.pick(tier, used)
            assert not used & set(c.actions)
            used |= set(c.actions)


def test_missing_tier_falls_back_to_harder_first(policy):
    p = planner(policy, challenge_pool=[Action.TURN_LEFT, Action.NOD], compound_challenges=False)
    assert p.pick(E, set()).tier is M
    p = planner(policy, challenge_pool=[Action.BLINK], compound_challenges=False)
    assert p.pick(H, set()) == Challenge((Action.BLINK,), E)


def test_exhausted_pool_allows_repeats(policy):
    p = planner(policy, challenge_pool=[Action.BLINK], compound_challenges=False)
    assert p.pick(E, {Action.BLINK}).actions == (Action.BLINK,)


def test_sequences_are_unpredictable(policy):
    """With the default (secrets-backed) RNG every action gets used, the first
    challenge is spread evenly over the EASY pool, and sequences vary widely."""
    p = ChallengePlanner(policy)
    seqs, seen = set(), set()
    first = {a: 0 for a in policy.challenge_pool if TIER_OF[a] is E}
    for _ in range(300):
        used: set[Action] = set()
        seq = []
        for tier in p.tiers_for_attempt(0, STRONG):
            c = p.pick(tier, used)
            used |= set(c.actions)
            seq.append(c.actions)
        first[seq[0][0]] += 1
        seen |= used
        seqs.add(tuple(seq))
    assert seen == set(policy.challenge_pool)
    assert all(60 <= n <= 140 for n in first.values()), first   # expected 100 each
    assert len(seqs) > 60


def test_prompt_text():
    assert Challenge((Action.BLINK,), E).prompt == "Please blink"
    assert Challenge((Action.TURN_LEFT,), M).prompt == "Please turn your head to the left"
    assert Challenge((Action.TURN_LEFT, Action.SMILE), H).prompt == \
        "Please turn your head to the left, then smile"
