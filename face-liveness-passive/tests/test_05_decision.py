"""Single-image decisions through the engine: real face detection, fake model scores.

The fake models make the fused bona fide probability exactly the given score, so the
decision rule, category and species logic can be checked precisely.
"""

import json

import cv2
import numpy as np
import pytest

import synth
from passive_liveness.engine import attack_category, decide, suspected_species
from passive_liveness.io import InputError
from passive_liveness.types import AttackCategory as C
from passive_liveness.types import Decision as D
from passive_liveness.types import NonResponseReason as R
from passive_liveness.types import PAISpecies as S

from conftest import PORTRAIT


# ---------------------------------------------------------------- thresholds (accept 0.80, reject 0.40)

@pytest.mark.parametrize("score, expected", [
    (0.99, D.BONAFIDE), (0.80, D.BONAFIDE),          # accept threshold is inclusive
    (0.7999, D.UNCERTAIN), (0.40, D.UNCERTAIN),      # reject threshold: < is an attack
    (0.3999, D.ATTACK), (0.0, D.ATTACK),
])
def test_threshold_boundaries(make_engine, portrait, score, expected):
    r = make_engine(score).analyze_image(portrait)
    assert r.bonafide_probability == pytest.approx(score)
    assert r.decision is expected
    assert r.attack_detected is (expected is D.ATTACK)


def test_custom_thresholds(make_engine, portrait):
    e = make_engine(0.6, decision={"accept_threshold": 0.55, "reject_threshold": 0.2})
    assert e.analyze_image(portrait).decision is D.BONAFIDE


# ---------------------------------------------------------------- categories & species

@pytest.mark.parametrize("attack_label, expected", [
    ("presentation_attack", C.PRESENTATION_ATTACK),
    ("deepfake", C.DEEPFAKE),
    ("synthetic", C.SYNTHETIC),
])
def test_attack_category_follows_the_fused_distribution(make_engine, portrait, attack_label, expected):
    r = make_engine(0.1, attack_label=attack_label).analyze_image(portrait)
    assert r.attack_category is expected
    assert sum(r.categories.values()) == pytest.approx(1.0)
    assert set(r.categories) == {"bonafide", "presentation_attack", "deepfake", "synthetic"}


def test_attack_type_split_comes_from_the_4_class_model(make_engine, portrait):
    r = make_engine(0.2, attack_label="deepfake").analyze_image(portrait)
    # both models: 0.2 bona fide; only the 4-class model can say *which* attack -> all deepfake
    assert r.categories["deepfake"] == pytest.approx(0.8)
    assert r.categories["presentation_attack"] == pytest.approx(0.0)


def test_bonafide_is_never_given_a_species(make_engine, portrait, business):
    hs = synth.head_shot(portrait, make_engine(0.9).analyze_image(portrait).face.box)
    r = make_engine(0.95).analyze_image(synth.screen_replay(hs))
    assert r.decision is D.BONAFIDE
    assert r.cues.indicators["screen_replay"] >= 0.5          # the cue fired ...
    assert r.suspected_pai_species is S.NONE                   # ... but the models say bona fide


@pytest.mark.parametrize("render, species", [(synth.screen_replay, S.SCREEN_REPLAY),
                                             (synth.printed_photo, S.PRINT)])
def test_species_is_suggested_for_attacks_and_uncertain(make_engine, portrait, render, species):
    hs = synth.head_shot(portrait, make_engine(0.9).analyze_image(portrait).face.box)
    for score in (0.1, 0.6):
        r = make_engine(score).analyze_image(render(hs))
        assert r.suspected_pai_species is species
        assert r.cues.evidence


def test_attack_without_cues_is_unspecified(make_engine, portrait):
    r = make_engine(0.1).analyze_image(portrait)
    assert r.suspected_pai_species is S.UNSPECIFIED


def test_decision_helpers():
    assert attack_category({}) is C.NONE
    assert attack_category({"bonafide": 0.5, "presentation_attack": 0.2, "deepfake": 0.3, "synthetic": 0}) is C.NONE
    assert suspected_species(D.NON_RESPONSE, C.PRESENTATION_ATTACK, {"print": 1.0}) is S.NONE
    assert suspected_species(D.ATTACK, C.DEEPFAKE, {"print": 0.2}) is S.NONE
    assert suspected_species(D.ATTACK, C.DEEPFAKE, {"screen_replay": 0.7}) is S.SCREEN_REPLAY


# ---------------------------------------------------------------- non-response

def test_no_face_is_a_non_response_without_model_calls(make_engine, portrait):
    e = make_engine(0.9)
    r = e.analyze_image(np.zeros_like(portrait))
    assert r.decision is D.NON_RESPONSE and r.quality.reasons == (R.NO_FACE,)
    assert r.bonafide_probability is None and r.models == ()
    assert all(c.calls == 0 for c in e.classifiers)


def test_multiple_faces_is_always_a_non_response(make_engine, portrait):
    two = np.hstack([portrait, cv2.flip(portrait, 1)])
    for enforce in (True, False):
        r = make_engine(0.95, quality={"enforce": enforce}).analyze_image(two)
        assert r.decision is D.NON_RESPONSE
        assert R.MULTIPLE_FACES in r.quality.reasons
        assert r.face.count == 2 and len(r.face.all_boxes) == 2
        assert r.bonafide_probability == pytest.approx(0.95)       # scores are still reported


def test_quality_failure_is_a_non_response_only_when_enforced(make_engine, portrait):
    dark = (portrait * 0.12).astype(np.uint8)
    r = make_engine(0.95).analyze_image(dark)
    assert r.decision is D.NON_RESPONSE and R.TOO_DARK in r.quality.reasons
    r = make_engine(0.95, quality={"enforce": False}).analyze_image(dark)
    assert r.decision is D.BONAFIDE and not r.quality.passed


# ---------------------------------------------------------------- inputs & outputs

def test_accepts_path_bytes_and_arrays(make_engine, portrait):
    e = make_engine(0.9)
    by_path = e.analyze_image(PORTRAIT)
    by_bytes = e.analyze_image(PORTRAIT.read_bytes())
    by_array = e.analyze_image(portrait)
    assert by_path.face.box == by_bytes.face.box == by_array.face.box
    rgba = np.dstack([portrait, np.full(portrait.shape[:2], 255, np.uint8)])
    assert e.analyze_image(rgba).face.box == by_array.face.box
    with pytest.raises(InputError):
        e.analyze_image(b"not an image")
    with pytest.raises(InputError):
        e.analyze_image(portrait.astype(np.float32))


def test_result_is_json_serialisable_with_all_fields(make_engine, portrait):
    r = make_engine(0.9).analyze_image(portrait, explain=True)
    d = json.loads(json.dumps(r.to_dict()))
    for key in ["decision", "bonafide_probability", "attack_detected", "categories", "attack_category",
                "suspected_pai_species", "face", "quality", "models", "cues", "timings_ms"]:
        assert key in d
    assert "heatmap_png" not in d                       # binary stays out of JSON
    assert r.heatmap_png[:8] == b"\x89PNG\r\n\x1a\n"
    assert {m["name"] for m in d["models"]} == {"unified", "fas"}
    assert set(d["cues"]["values"]) == {"moire_peak_ratio", "border_sides", "glare_fraction",
                                        "dynamic_range", "saturation_mean"}


def test_cues_can_be_disabled(make_engine, portrait):
    r = make_engine(0.1, cues={"enabled": False}).analyze_image(portrait)
    assert r.cues.indicators == {} and r.suspected_pai_species is S.UNSPECIFIED


def test_decide_function_directly(config):
    assert decide(None, (), config) is D.NON_RESPONSE
    assert decide(0.9, (R.MULTIPLE_FACES,), config) is D.NON_RESPONSE
    assert decide(0.9, (R.TOO_BLURRY,), config) is D.NON_RESPONSE
