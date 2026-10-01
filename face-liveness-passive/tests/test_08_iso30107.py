"""ISO/IEC 30107-3 metrics against hand-computed values."""

import pytest

from passive_liveness import iso30107 as iso
from passive_liveness.iso30107 import Presentation as P
from passive_liveness.iso30107 import Rate

# Hand-worked example (attack if score < threshold):
#   bona fide : 0.95 0.90 0.85 0.70 0.30 + 1 non-response
#   print     : 0.10 0.20 0.50 0.90      + 1 non-response
#   replay    : 0.05 0.10 0.15 0.45
DATA = ([P("bonafide", s) for s in (0.95, 0.9, 0.85, 0.7, 0.3, None)]
        + [P("print", s, "A") for s in (0.1, 0.2, 0.5, 0.9, None)]
        + [P("replay", s, "B") for s in (0.05, 0.1, 0.15, 0.45)])


@pytest.fixture(scope="module")
def m():
    return iso.evaluate(DATA, {"t040": 0.4, "t080": 0.8})


def test_counts_and_non_response(m):
    assert m["counts"] == {"bonafide": 6, "attack": 9, "per_species": {"print": 5, "replay": 4}}
    assert m["non_response"]["bpnrr"]["value"] == pytest.approx(1 / 6)
    assert m["non_response"]["apnrr"]["value"] == pytest.approx(1 / 9)
    assert m["non_response"]["apnrr_per_species"]["print"]["value"] == pytest.approx(1 / 5)
    assert m["non_response"]["apnrr_per_species"]["replay"]["value"] == 0


def test_operating_point_040(m):
    op = m["operating_points"]["t040"]
    assert op["bpcer"]["value"] == pytest.approx(1 / 5)                 # 0.30 rejected; non-response excluded
    assert op["apcer_per_species"]["print"]["value"] == pytest.approx(2 / 4)    # 0.5, 0.9 accepted
    assert op["apcer_per_species"]["replay"]["value"] == pytest.approx(1 / 4)   # 0.45 accepted
    assert op["apcer_max"]["species"] == "print" and op["apcer_max"]["value"] == pytest.approx(0.5)
    assert op["apcer_pooled"]["value"] == pytest.approx(3 / 8)
    assert op["acer_informative"] == pytest.approx((0.5 + 0.2) / 2)
    assert op["apcer_per_attack_potential"] == {
        "A": {"species": "print", **Rate(2, 4).to_dict()},
        "B": {"species": "replay", **Rate(1, 4).to_dict()},
    }


def test_operating_point_080(m):
    op = m["operating_points"]["t080"]
    assert op["bpcer"]["value"] == pytest.approx(2 / 5)
    assert op["apcer_per_species"]["print"]["value"] == pytest.approx(1 / 4)
    assert op["apcer_per_species"]["replay"]["value"] == 0
    assert op["apcer_per_species"]["replay"]["rule_of_3_upper"] == pytest.approx(0.75)


def test_threshold_free_summaries(m):
    # APCER_max <= 1 % needs a threshold above 0.90 -> bona fide 0.90/0.85/0.70/0.30 rejected
    for k in ("BPCER10", "BPCER20", "BPCER100"):
        assert m["bpcer_at_apcer"][k]["bpcer"] == pytest.approx(0.8)
        assert m["bpcer_at_apcer"][k]["threshold"] == pytest.approx(0.925)
    assert m["eer"]["eer"] == pytest.approx((0.25 + 0.2) / 2)
    assert m["eer"]["threshold"] == pytest.approx(0.475)
    assert m["auc"] == pytest.approx(34.5 / 40)


def test_small_sample_notes(m):
    assert any("print" in n for n in m["notes"])
    assert any("bona fide" in n for n in m["notes"])


@pytest.mark.parametrize("errors, total, lo, hi", [
    (0, 10, 0.0, 0.2775),
    (5, 10, 0.2366, 0.7634),
    (1, 100, 0.0018, 0.0545),
])
def test_wilson_interval(errors, total, lo, hi):
    a, b = Rate(errors, total).wilson()
    assert a == pytest.approx(lo, abs=1e-4) and b == pytest.approx(hi, abs=1e-4)


def test_empty_rates():
    r = Rate(0, 0)
    assert r.value is None and r.wilson() is None
    assert r.to_dict()["ci95"] is None


def test_perfect_and_inverted_detectors():
    perfect = [P("bonafide", 0.9), P("bonafide", 0.8), P("print", 0.1), P("print", 0.2)]
    m = iso.evaluate(perfect, {"t": 0.5})
    assert m["auc"] == 1.0 and m["eer"]["eer"] == 0.0
    assert m["bpcer_at_apcer"]["BPCER100"]["bpcer"] == 0.0
    inverted = [P("bonafide", 0.1), P("print", 0.9)]
    assert iso.auc(inverted) == 0.0
    assert iso.auc([P("bonafide", 0.5), P("print", 0.5)]) == 0.5


def test_no_attacks_or_no_scores():
    m = iso.evaluate([P("bonafide", 0.9)], {"t": 0.5})
    assert m["auc"] is None and "no attack presentations" in " ".join(m["notes"])
    m = iso.evaluate([P("bonafide", None), P("print", None)], {"t": 0.5})
    assert m["non_response"]["apnrr"]["value"] == 1.0
    assert m["operating_points"]["t"]["apcer_max"]["value"] is None


def test_label_aliases_and_csv_rows():
    assert iso.normalise_label("Live") == iso.normalise_label("REAL") == "bonafide"
    assert iso.normalise_label("Print") == "print"
    rows = [{"label": "real", "score": "0.9"}, {"label": "mask", "score": "", "attack_potential": "high"}]
    ps = iso.presentations_from_rows(rows)
    assert ps[0] == P("bonafide", 0.9) and ps[1].score is None and ps[1].attack_potential == "high"
