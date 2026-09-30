"""Challenge catalogue, dynamic selection and escalation planning.

Escalation rules (all four apply together):

* Difficulty tiers   – the base sequence is EASY -> MEDIUM -> HARD (padded with HARD
                       when ``min_challenges`` > 3).
* Stricter per step  – step N uses ``policy.steps[N]`` (shorter timeout, larger angle).
* Weakness           – a passive score below ``passive_weak_threshold`` adds a HARD
                       step up front; a step passed with a small margin adds one later
                       (the session does that), both capped by ``max_extra_challenges``.
* Retry              – attempt k (0-based) shifts every tier up by k, capped at HARD.

Selection uses ``secrets.SystemRandom`` so the sequence is unpredictable.
"""

from __future__ import annotations

import random
import secrets
from dataclasses import dataclass

from .config import LivenessPolicy
from .types import Action, Tier

TIER_OF: dict[Action, Tier] = {
    Action.BLINK: Tier.EASY,
    Action.SMILE: Tier.EASY,
    Action.OPEN_MOUTH: Tier.EASY,
    Action.TURN_LEFT: Tier.MEDIUM,
    Action.TURN_RIGHT: Tier.MEDIUM,
    Action.LOOK_UP: Tier.MEDIUM,
    Action.LOOK_DOWN: Tier.MEDIUM,
    Action.NOD: Tier.HARD,
    Action.GAZE_LEFT: Tier.HARD,
    Action.GAZE_RIGHT: Tier.HARD,
    Action.GAZE_UP: Tier.HARD,
    Action.GAZE_DOWN: Tier.HARD,
}

_PHRASES: dict[Action, str] = {
    Action.BLINK: "blink",
    Action.SMILE: "smile",
    Action.OPEN_MOUTH: "open your mouth",
    Action.TURN_LEFT: "turn your head to the left",
    Action.TURN_RIGHT: "turn your head to the right",
    Action.LOOK_UP: "tilt your head up",
    Action.LOOK_DOWN: "tilt your head down",
    Action.NOD: "nod your head",
    Action.GAZE_LEFT: "keep your head still and look to the left with your eyes",
    Action.GAZE_RIGHT: "keep your head still and look to the right with your eyes",
    Action.GAZE_UP: "keep your head still and look up with your eyes",
    Action.GAZE_DOWN: "keep your head still and look down with your eyes",
}

COMPOUND_LENGTH = 2


@dataclass(frozen=True)
class Challenge:
    actions: tuple[Action, ...]
    tier: Tier

    @property
    def prompt(self) -> str:
        return "Please " + ", then ".join(_PHRASES[a] for a in self.actions)


class ChallengePlanner:
    def __init__(self, policy: LivenessPolicy, rng: random.Random | None = None):
        self.policy = policy
        self.rng = rng or secrets.SystemRandom()

    # ------------------------------------------------------------ planning

    def tiers_for_attempt(self, attempt_index: int, passive_score: float | None) -> list[Tier]:
        n = self.policy.min_challenges
        base = [Tier.EASY, Tier.MEDIUM, Tier.HARD][:n] + [Tier.HARD] * max(0, n - 3)
        tiers = [Tier(min(t + attempt_index, Tier.HARD)) for t in base]
        if self.passive_is_weak(passive_score) and self.policy.escalation.max_extra_challenges > 0:
            tiers.append(Tier.HARD)
        return tiers

    def passive_is_weak(self, passive_score: float | None) -> bool:
        esc = self.policy.escalation
        score = esc.default_passive_score if passive_score is None else passive_score
        return score < esc.passive_weak_threshold

    # ------------------------------------------------------------ selection

    def pick(self, tier: Tier, used: set[Action]) -> Challenge:
        """Pick a challenge of `tier`, avoiding actions already used in this attempt.

        Falls back to the nearest tier (harder first) if the pool has nothing left
        for the requested one, and allows repeats only when everything is used.
        """
        for t in self._tier_preference(tier):
            options = self._options(t, used)
            if options:
                return self._materialise(self.rng.choice(options), t, used)
        return self.pick(tier, set()) if used else self._fail()

    def _tier_preference(self, tier: Tier) -> list[Tier]:
        harder = [Tier(t) for t in range(tier, Tier.HARD + 1)]
        easier = [Tier(t) for t in range(tier - 1, Tier.EASY - 1, -1)]
        return harder + easier

    def _options(self, tier: Tier, used: set[Action]) -> list:
        singles = [a for a in self.policy.challenge_pool if TIER_OF[a] is tier and a not in used]
        options: list = list(singles)
        if tier is Tier.HARD and self.policy.compound_challenges \
                and len(self._compound_parts(used)) >= COMPOUND_LENGTH:
            options.append("compound")
        return options

    def _compound_parts(self, used: set[Action]) -> list[Action]:
        return [a for a in self.policy.challenge_pool
                if TIER_OF[a] in (Tier.EASY, Tier.MEDIUM) and a not in used]

    def _materialise(self, option, tier: Tier, used: set[Action]) -> Challenge:
        if option == "compound":
            actions = tuple(self.rng.sample(self._compound_parts(used), COMPOUND_LENGTH))
            return Challenge(actions, Tier.HARD)
        return Challenge((option,), tier)

    def _fail(self):
        raise ValueError("challenge pool is empty")
