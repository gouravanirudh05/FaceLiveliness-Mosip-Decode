"""ViT re-implementation, preprocessing, strict checkpoint loading, Grad-CAM and fusion
(no real checkpoints needed - tiny random models)."""

import numpy as np
import pytest
import torch

from passive_liveness import vit
from passive_liveness.models import (
    FAS, FSFM_MEAN, FSFM_STD, SPECS, UNIFIED, FSFMClassifier, ModelError, fuse, preprocess,
)
from passive_liveness.types import CATEGORY_LABELS, ModelOutput

TINY = vit.ViTArch(embed_dim=32, depth=2, num_heads=2)


@pytest.fixture
def tiny_arch(monkeypatch):
    monkeypatch.setitem(vit.ARCHS, "vit_base_patch16", TINY)


def save_checkpoint(path, num_classes, **mutate):
    torch.manual_seed(0)
    model = vit.build_vit("vit_base_patch16", num_classes)
    state = model.state_dict()
    for k, v in mutate.items():
        if v is None:
            state.pop(k)
        else:
            state[k] = v
    torch.save({"model": state, "epoch": 1}, path)


# ---------------------------------------------------------------- architecture

def test_vit_b16_parameter_count_matches_the_fsfm_checkpoints():
    # FSFM fine-tuning logs report n_parameters = 85800194 for the 2-class ViT-B/16.
    n = sum(p.numel() for p in vit.build_vit("vit_base_patch16", 2).parameters())
    assert n == 85_800_194


def test_vit_state_dict_names_match_upstream_timm_layout():
    keys = set(vit.build_vit("vit_base_patch16", 4).state_dict())
    for k in ["cls_token", "pos_embed", "patch_embed.proj.weight", "fc_norm.weight", "head.weight",
              "blocks.11.attn.qkv.weight", "blocks.11.mlp.fc2.bias", "blocks.0.norm1.bias"]:
        assert k in keys
    assert "norm.weight" not in keys          # global pooling replaces the final norm with fc_norm
    assert len(keys) == 152


def test_unknown_architecture():
    with pytest.raises(ValueError, match="unknown architecture"):
        vit.build_vit("vit_tiny", 2)


def test_forward_shapes(tiny_arch):
    m = vit.build_vit("vit_base_patch16", 4).eval()
    x = torch.zeros(2, 3, 224, 224)
    assert m(x).shape == (2, 4)
    assert m.forward_features(x).shape == (2, TINY.embed_dim)


# ---------------------------------------------------------------- preprocessing

def test_preprocess_normalises_with_fsfm_statistics():
    colour = np.array([140, 108, 93], np.uint8)            # ~ the FSFM mean colour
    crop = np.broadcast_to(colour, (300, 300, 3)).copy()
    t = preprocess([crop, crop])
    assert t.shape == (2, 3, 224, 224) and t.dtype == torch.float32
    expected = (colour / 255.0 - np.array(FSFM_MEAN)) / np.array(FSFM_STD)
    assert np.allclose(t[0, :, 100, 100].numpy(), expected, atol=1e-3)


def test_preprocess_resizes_to_256_then_centre_crops_224():
    crop = np.zeros((512, 512, 3), np.uint8)
    crop[:, :32] = 255          # left 1/16 of the crop: removed by the 256 -> 224 centre crop
    t = preprocess([crop])[0]
    white = (1.0 - FSFM_MEAN[0]) / FSFM_STD[0]
    assert t[0, :, 0].max() < white - 0.5


# ---------------------------------------------------------------- loading

def test_strict_loading_and_prediction(tiny_arch, tmp_path):
    p = tmp_path / "m.pth"
    save_checkpoint(p, 2)
    clf = FSFMClassifier(FAS, p)
    out = clf.predict([np.full((200, 200, 3), 120, np.uint8), np.zeros((64, 64, 3), np.uint8)])
    assert len(out) == 2
    for o in out:
        assert o.name == "fas" and o.labels == FAS.labels
        assert sum(o.probabilities) == pytest.approx(1.0, abs=1e-5)
        assert o.bonafide_probability == o.probabilities[FAS.bonafide_index]
        assert len(o.logits) == 2 and o.inference_ms >= 0


def test_predictions_are_deterministic(tiny_arch, tmp_path):
    p = tmp_path / "m.pth"
    save_checkpoint(p, 4)
    clf = FSFMClassifier(UNIFIED, p)
    crop = np.random.default_rng(0).integers(0, 255, (180, 180, 3), dtype=np.uint8)
    assert clf.predict([crop])[0].probabilities == clf.predict([crop])[0].probabilities


@pytest.mark.parametrize("mutate, match", [
    ({"fc_norm.weight": None}, "Missing key"),                      # would be silently random with strict=False
    ({"extra.weight": torch.zeros(1)}, "Unexpected key"),
    ({"head.weight": torch.zeros(3, TINY.embed_dim)}, "size mismatch"),
])
def test_mismatched_checkpoints_are_rejected(tiny_arch, tmp_path, mutate, match):
    p = tmp_path / "m.pth"
    save_checkpoint(p, 2, **mutate)
    with pytest.raises(ModelError, match=match):
        FSFMClassifier(FAS, p)


def test_missing_checkpoint_and_sha_mismatch(tiny_arch, tmp_path):
    with pytest.raises(ModelError, match="download_models"):
        FSFMClassifier(FAS, tmp_path / "none.pth")
    p = tmp_path / "m.pth"
    save_checkpoint(p, 2)
    with pytest.raises(ModelError, match="sha256 mismatch"):
        FSFMClassifier(FAS, p, expected_sha256="0" * 64)


def test_gradcam_is_a_normalised_14x14_map(tiny_arch, tmp_path):
    p = tmp_path / "m.pth"
    save_checkpoint(p, 2)
    clf = FSFMClassifier(FAS, p)
    crop = np.random.default_rng(1).integers(0, 255, (224, 224, 3), dtype=np.uint8)
    cam = clf.gradcam(crop, 1)
    assert cam.shape == (14, 14)
    assert cam.min() >= 0 and cam.max() <= 1.0 + 1e-6
    assert all(p.grad is None for p in clf.model.parameters())     # no gradient state left behind


# ---------------------------------------------------------------- fusion

def out(spec, probs):
    return ModelOutput(spec.name, spec.labels, tuple(probs), (0.0,) * len(probs),
                       probs[spec.bonafide_index], 0.0)


def test_label_mappings_are_consistent():
    for spec in SPECS.values():
        assert spec.labels[spec.bonafide_index] == "bonafide"
        for cat, idx in zip(CATEGORY_LABELS, spec.category_index):
            if idx is not None:
                assert spec.labels[idx] == cat


def test_bonafide_is_the_weighted_mean_and_attack_types_come_from_the_4_class_model():
    u = out(UNIFIED, [0.6, 0.1, 0.1, 0.2])       # bonafide, deepfake, synthetic, PA
    f = out(FAS, [0.3, 0.7])                     # PA, bonafide
    fused = fuse([u, f], {"unified": 0.5, "fas": 0.5})
    # bona fide = (0.6 + 0.7) / 2 = 0.65; attack mass 0.35 split 0.2 : 0.1 : 0.1 (PA : DF : SYN)
    assert fused == pytest.approx({"bonafide": 0.65, "presentation_attack": 0.175,
                                   "deepfake": 0.0875, "synthetic": 0.0875})
    assert sum(fused.values()) == pytest.approx(1.0)


def test_a_confident_deepfake_stays_a_deepfake_although_fas_is_binary():
    u = out(UNIFIED, [0.05, 0.9, 0.03, 0.02])
    f = out(FAS, [0.95, 0.05])
    fused = fuse([u, f], {"unified": 0.5, "fas": 0.5})
    assert max(fused, key=fused.get) == "deepfake"


def test_fusion_weights_and_single_model():
    u = out(UNIFIED, [0.2, 0.6, 0.1, 0.1])
    f = out(FAS, [0.1, 0.9])
    assert fuse([u, f], {"unified": 1, "fas": 3})["bonafide"] == pytest.approx(0.25 * 0.2 + 0.75 * 0.9)
    only_fas = fuse([f], {"fas": 1})
    assert only_fas == pytest.approx({"bonafide": 0.9, "presentation_attack": 0.1, "deepfake": 0.0, "synthetic": 0.0})
    only_unified = fuse([u], {"unified": 1})
    assert only_unified == pytest.approx({"bonafide": 0.2, "presentation_attack": 0.1, "deepfake": 0.6,
                                          "synthetic": 0.1})
