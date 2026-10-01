"""Presentation attack detection metrics in the sense of ISO/IEC 30107-3.

Input: one record per presentation - its ground-truth label (``bonafide`` or a PAI
species name) and the PAD output (a bona fide score in [0, 1], higher = more bona fide,
or ``None`` when the subsystem produced no decision).

A presentation is *classified as an attack* when ``score < threshold``.

* APCER(species) - attack presentations of that species classified as bona fide,
  over the attack presentations of that species that got a decision.
* APCER_max      - worst species (ISO/IEC 30107-3 reports the maximum over the PAI
  species of an attack-potential level; with ``attack_potential`` given, per level too).
* BPCER          - bona fide presentations classified as attacks, over bona fide
  presentations that got a decision.
* APNRR / BPNRR  - attack / bona fide presentations that got no decision (non-response).
* BPCER@APCER=x  - lowest BPCER at a threshold where APCER_max <= x (BPCER10/20/100).
* EER, AUC       - threshold-free summaries over all attacks pooled (informative).
* ACER           - (APCER_max + BPCER) / 2; a common academic summary, NOT an
  ISO/IEC 30107-3 metric - reported only for comparison with published benchmarks.

Every rate carries a 95 % Wilson score interval; zero-error rates also get the
"rule of 3" upper bound 3/N.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

import numpy as np

BONAFIDE = "bonafide"
BONAFIDE_ALIASES = {"bonafide", "bona_fide", "bona-fide", "live", "real", "genuine"}
Z95 = 1.959963984540054


def normalise_label(label: str) -> str:
    label = label.strip().lower()
    return BONAFIDE if label in BONAFIDE_ALIASES else label


@dataclass(frozen=True)
class Presentation:
    label: str                       # "bonafide" or PAI species
    score: float | None              # None = non-response
    attack_potential: str | None = None
    source: str = ""

    @property
    def is_attack(self) -> bool:
        return self.label != BONAFIDE


@dataclass(frozen=True)
class Rate:
    errors: int
    total: int

    @property
    def value(self) -> float | None:
        return self.errors / self.total if self.total else None

    def wilson(self, z: float = Z95) -> tuple[float, float] | None:
        n = self.total
        if not n:
            return None
        p = self.errors / n
        denom = 1 + z * z / n
        centre = (p + z * z / (2 * n)) / denom
        half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
        return max(0.0, centre - half), min(1.0, centre + half)

    def to_dict(self) -> dict:
        ci = self.wilson()
        d = {"value": self.value, "errors": self.errors, "total": self.total,
             "ci95": list(ci) if ci else None}
        if self.total and self.errors == 0:
            d["rule_of_3_upper"] = min(1.0, 3 / self.total)
        return d


def _split(ps: Sequence[Presentation]):
    bona = [p for p in ps if not p.is_attack]
    attacks = [p for p in ps if p.is_attack]
    return bona, attacks


def apcer(attacks: Sequence[Presentation], threshold: float) -> Rate:
    decided = [p for p in attacks if p.score is not None]
    return Rate(sum(p.score >= threshold for p in decided), len(decided))


def bpcer(bona: Sequence[Presentation], threshold: float) -> Rate:
    decided = [p for p in bona if p.score is not None]
    return Rate(sum(p.score < threshold for p in decided), len(decided))


def nrr(ps: Sequence[Presentation]) -> Rate:
    return Rate(sum(p.score is None for p in ps), len(ps))


def by_species(attacks: Sequence[Presentation]) -> dict[str, list[Presentation]]:
    out: dict[str, list[Presentation]] = {}
    for p in attacks:
        out.setdefault(p.label, []).append(p)
    return dict(sorted(out.items()))


def operating_point(ps: Sequence[Presentation], threshold: float) -> dict:
    bona, attacks = _split(ps)
    species = by_species(attacks)
    per_species = {s: apcer(v, threshold) for s, v in species.items()}
    decided_species = {s: r for s, r in per_species.items() if r.total}
    worst = max(decided_species, key=lambda s: decided_species[s].value) if decided_species else None
    b = bpcer(bona, threshold)
    out = {
        "threshold": threshold,
        "apcer_per_species": {s: r.to_dict() for s, r in per_species.items()},
        "apcer_max": {"species": worst, **(per_species[worst].to_dict() if worst else Rate(0, 0).to_dict())},
        "apcer_pooled": apcer(attacks, threshold).to_dict(),
        "bpcer": b.to_dict(),
    }
    levels: dict[str, list[str]] = {}
    for p in attacks:
        if p.attack_potential:
            levels.setdefault(p.attack_potential, [])
            if p.label not in levels[p.attack_potential]:
                levels[p.attack_potential].append(p.label)
    if levels:
        out["apcer_per_attack_potential"] = {}
        for level, names in sorted(levels.items()):
            rates = {s: per_species[s] for s in names if per_species[s].total}
            w = max(rates, key=lambda s: rates[s].value) if rates else None
            out["apcer_per_attack_potential"][level] = {"species": w, **(rates[w].to_dict() if w else {})}
    if worst and b.total:
        out["acer_informative"] = (per_species[worst].value + b.value) / 2
    return out


def _thresholds(ps: Sequence[Presentation]) -> np.ndarray:
    scores = sorted({p.score for p in ps if p.score is not None})
    if not scores:
        return np.array([0.5])
    mids = [(a + b) / 2 for a, b in zip(scores, scores[1:])]
    return np.array([0.0] + scores + mids + [1.0 + 1e-9])


def sweep(ps: Sequence[Presentation]) -> list[dict]:
    """APCER_max / APCER_pooled / BPCER at every distinct threshold (DET curve data)."""
    bona, attacks = _split(ps)
    species = by_species(attacks)
    rows = []
    for t in sorted(_thresholds(ps)):
        per = [apcer(v, t).value for v in species.values()]
        per = [x for x in per if x is not None]
        rows.append({
            "threshold": float(t),
            "apcer_max": max(per) if per else None,
            "apcer_pooled": apcer(attacks, t).value,
            "bpcer": bpcer(bona, t).value,
        })
    return rows


def bpcer_at_apcer(rows: Sequence[dict], target: float) -> dict | None:
    ok = [r for r in rows if r["apcer_max"] is not None and r["bpcer"] is not None and r["apcer_max"] <= target]
    if not ok:
        return None
    # BPCER never decreases as the threshold rises, so the lowest threshold meeting the
    # APCER target gives the lowest BPCER.
    best = min(ok, key=lambda r: r["threshold"])
    return {"bpcer": best["bpcer"], "threshold": best["threshold"], "apcer_max": best["apcer_max"]}


def eer(rows: Sequence[dict]) -> dict | None:
    pts = [r for r in rows if r["apcer_pooled"] is not None and r["bpcer"] is not None]
    if not pts:
        return None
    best = min(pts, key=lambda r: abs(r["apcer_pooled"] - r["bpcer"]))
    return {"eer": (best["apcer_pooled"] + best["bpcer"]) / 2, "threshold": best["threshold"]}


def auc(ps: Sequence[Presentation]) -> float | None:
    """P(score of a random bona fide > score of a random attack), ties count 1/2."""
    b = np.array([p.score for p in ps if not p.is_attack and p.score is not None])
    a = np.array([p.score for p in ps if p.is_attack and p.score is not None])
    if not len(a) or not len(b):
        return None
    greater = (b[:, None] > a[None, :]).sum()
    ties = (b[:, None] == a[None, :]).sum()
    return float((greater + 0.5 * ties) / (len(a) * len(b)))


def evaluate(ps: Sequence[Presentation], thresholds: Mapping[str, float]) -> dict:
    """Full ISO/IEC 30107-3 style metric set at the named operating thresholds."""
    ps = list(ps)
    bona, attacks = _split(ps)
    rows = sweep(ps)
    species = by_species(attacks)
    notes = []
    for s, v in species.items():
        if len(v) < 30:
            notes.append(f"PAI species '{s}' has only {len(v)} presentations; its APCER confidence interval is wide "
                         "(ISO/IEC 19795-1 'rule of 30' needs >= 30 errors for +/-30 % at 90 % confidence).")
    if len(bona) < 30:
        notes.append(f"only {len(bona)} bona fide presentations; BPCER is poorly estimated.")
    if not attacks:
        notes.append("no attack presentations: APCER cannot be measured.")
    return {
        "counts": {"bonafide": len(bona), "attack": len(attacks),
                   "per_species": {s: len(v) for s, v in species.items()}},
        "non_response": {"apnrr": nrr(attacks).to_dict(), "bpnrr": nrr(bona).to_dict(),
                         "apnrr_per_species": {s: nrr(v).to_dict() for s, v in species.items()}},
        "operating_points": {name: operating_point(ps, t) for name, t in thresholds.items()},
        "bpcer_at_apcer": {"BPCER10": bpcer_at_apcer(rows, 0.10), "BPCER20": bpcer_at_apcer(rows, 0.05),
                           "BPCER100": bpcer_at_apcer(rows, 0.01)},
        "eer": eer(rows),
        "auc": auc(ps),
        "notes": notes,
    }


def presentations_from_rows(rows: Iterable[Mapping[str, str]]) -> list[Presentation]:
    """CSV rows with columns label, score (empty = non-response), [attack_potential], [source]."""
    out = []
    for r in rows:
        score = r.get("score", "")
        out.append(Presentation(
            label=normalise_label(r["label"]),
            score=None if score in ("", None, "None", "nan") else float(score),
            attack_potential=r.get("attack_potential") or None,
            source=r.get("source", "")))
    return out
