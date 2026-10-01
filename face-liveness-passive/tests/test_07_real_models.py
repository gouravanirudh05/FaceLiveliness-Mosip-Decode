"""The real FSFM checkpoints (skipped when they have not been downloaded).

The only bona fide material available here is two public sample photos, and the attacks
are synthetic renderings, so these tests check loading, conventions and *relative*
behaviour - not PAD accuracy. Accuracy is measured with passive-liveness-eval on a
real dataset (see README).
"""

import cv2
import numpy as np
import pytest

import synth
from passive_liveness.models import FAS, UNIFIED, FSFMClassifier, sha256_of
from passive_liveness.types import Decision as D
from passive_liveness.types import PAISpecies as S

from conftest import CHECKPOINTS, HAVE_CHECKPOINTS

pytestmark = [pytest.mark.models,
              pytest.mark.skipif(not HAVE_CHECKPOINTS, reason="run scripts/download_models.py")]


def test_checkpoints_match_the_pinned_sha256(config):
    for entry in (config.models.unified, config.models.fas):
        assert sha256_of(config.models.path(entry)) == entry.sha256


def test_both_models_load_strictly(real_engine):
    names = {c.spec.name for c in real_engine.classifiers}
    assert names == {"unified", "fas"}
    for c in real_engine.classifiers:
        assert isinstance(c, FSFMClassifier)
        assert c.model.head.out_features == len(c.spec.labels)


@pytest.mark.parametrize("name", ["portrait", "business"])
def test_sample_photos_are_bona_fide_for_both_models(real_engine, request, name):
    img = request.getfixturevalue(name)
    r = real_engine.analyze_image(img)
    assert r.decision is D.BONAFIDE, r.categories
    for m in r.models:
        assert m.bonafide_probability > 0.85, (m.name, m.probabilities)
        assert np.argmax(m.probabilities) == (UNIFIED if m.name == "unified" else FAS).bonafide_index
    assert r.attack_category.value == "none" and r.suspected_pai_species is S.NONE


def test_inference_is_deterministic(real_engine, portrait):
    a = real_engine.analyze_image(portrait)
    b = real_engine.analyze_image(portrait)
    assert a.bonafide_probability == b.bonafide_probability
    assert [m.logits for m in a.models] == [m.logits for m in b.models]


def test_flipped_face_scores_alike(real_engine, portrait):
    a = real_engine.analyze_image(portrait).bonafide_probability
    b = real_engine.analyze_image(cv2.flip(portrait, 1)).bonafide_probability
    assert abs(a - b) < 0.1


@pytest.mark.parametrize("render", [synth.screen_replay, synth.printed_photo])
@pytest.mark.parametrize("name", ["portrait", "business"])
def test_synthetic_recaptures_lower_the_bona_fide_probability(real_engine, request, render, name):
    img = request.getfixturevalue(name)
    original = real_engine.analyze_image(img)
    hs = synth.head_shot(img, original.face.box)
    attack = real_engine.analyze_image(render(hs))
    assert attack.bonafide_probability < original.bonafide_probability - 0.1
    assert attack.decision is not D.BONAFIDE
    assert attack.suspected_pai_species is (S.SCREEN_REPLAY if render is synth.screen_replay else S.PRINT)


def test_gradcam_overlay(real_engine, portrait):
    r = real_engine.analyze_image(portrait, explain=True)
    heat = cv2.imdecode(np.frombuffer(r.heatmap_png, np.uint8), cv2.IMREAD_COLOR)
    assert heat.shape == (224, 224, 3)
    assert "gradcam" in r.timings_ms


def test_video_through_real_models(real_engine, portrait):
    r = real_engine.analyze_video([portrait] * 30, include_frames=True)     # 1.2 s at 25 fps
    assert r.decision is D.BONAFIDE and r.complete
    assert all(f.models and f.timings_ms["models"] > 0 for f in r.frames)
