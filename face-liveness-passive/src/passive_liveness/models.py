"""FSFM classifiers: preprocessing, strict checkpoint loading, inference, Grad-CAM, fusion.

Preprocessing reproduces the evaluation transform the checkpoints were validated with
(``apply_simple_augment=True`` in their saved args): square face crop -> bicubic resize
to 256 -> centre crop 224 -> normalise with the VGGFace2 statistics of FSFM pre-training.
"""

from __future__ import annotations

import hashlib
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, Sequence, runtime_checkable

import numpy as np
import torch
from PIL import Image

from .types import CATEGORY_LABELS, ModelOutput
from .vit import build_vit

# pretrain_ds_mean_std.txt shipped with both checkpoints (VGGFace2, FSFM pre-training).
FSFM_MEAN = (0.5482207536697388, 0.42340534925460815, 0.3654651641845703)
FSFM_STD = (0.2789176106452942, 0.2438540756702423, 0.23493893444538116)
RESIZE, INPUT = 256, 224


class ModelError(RuntimeError):
    pass


@dataclass(frozen=True)
class ModelSpec:
    name: str
    arch: str
    labels: tuple[str, ...]
    bonafide_index: int
    # Index of each fused category (CATEGORY_LABELS) in this model's outputs, or None.
    category_index: tuple[int | None, ...]
    description: str


UNIFIED = ModelSpec(
    name="unified",
    arch="vit_base_patch16",
    labels=("bonafide", "deepfake", "synthetic", "presentation_attack"),
    bonafide_index=0,
    category_index=(0, 3, 1, 2),
    description="FSFM ViT-B/16 Unified-detector v1: real / deepfake / diffusion-AIGC / spoofing",
)
FAS = ModelSpec(
    name="fas",
    arch="vit_base_patch16",
    labels=("presentation_attack", "bonafide"),          # ImageFolder order: fake=0, real=1
    bonafide_index=1,
    category_index=(1, 0, None, None),
    description="FSFM ViT-B/16 face anti-spoofing, fine-tuned on MSU-MFSD, CASIA-FASD, Idiap Replay, OULU-NPU",
)
SPECS = {s.name: s for s in (UNIFIED, FAS)}
assert all(len(s.category_index) == len(CATEGORY_LABELS) for s in SPECS.values())


def preprocess(crops: Sequence[np.ndarray]) -> torch.Tensor:
    """HxWx3 uint8 RGB square crops -> normalised (N, 3, 224, 224) float tensor."""
    off = (RESIZE - INPUT) // 2
    mean = np.asarray(FSFM_MEAN, np.float32)
    std = np.asarray(FSFM_STD, np.float32)
    batch = []
    for c in crops:
        img = Image.fromarray(np.ascontiguousarray(c)).resize((RESIZE, RESIZE), Image.BICUBIC)
        a = np.asarray(img, np.float32)[off:off + INPUT, off:off + INPUT] / 255.0
        batch.append(((a - mean) / std).transpose(2, 0, 1))
    return torch.from_numpy(np.stack(batch).astype(np.float32))


@runtime_checkable
class Classifier(Protocol):
    """Anything that maps face crops to per-class probabilities (lets tests inject fakes)."""
    spec: ModelSpec

    def predict(self, crops: Sequence[np.ndarray]) -> list[ModelOutput]: ...

    def gradcam(self, crop: np.ndarray, class_index: int) -> np.ndarray: ...


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class FSFMClassifier:
    """One FSFM ViT checkpoint. Thread-safe: inference is serialised by a lock."""

    def __init__(self, spec: ModelSpec, checkpoint: str | Path, *, expected_sha256: str | None = None,
                 device: str = "cpu"):
        path = Path(checkpoint)
        if not path.is_file():
            raise ModelError(f"checkpoint not found: {path} (run scripts/download_models.py)")
        if expected_sha256:
            got = sha256_of(path)
            if got != expected_sha256:
                raise ModelError(f"sha256 mismatch for {path.name}: {got}")
        self.spec = spec
        self.path = path
        self.device = torch.device(device)
        try:
            ckpt = torch.load(path, map_location="cpu", weights_only=False)
            state = ckpt["model"] if isinstance(ckpt, dict) and "model" in ckpt else ckpt
            model = build_vit(spec.arch, len(spec.labels))
            model.load_state_dict(state, strict=True)
        except Exception as e:  # unpickling / truncated / mismatching checkpoints raise many types
            raise ModelError(f"cannot load {path.name}: {type(e).__name__}: {e}") from e
        self.model = model.to(self.device).eval()
        self._lock = threading.Lock()

    def predict(self, crops: Sequence[np.ndarray]) -> list[ModelOutput]:
        x = preprocess(crops).to(self.device)
        with self._lock, torch.inference_mode():
            t0 = time.perf_counter()
            logits = self.model(x).float().cpu()
            ms = (time.perf_counter() - t0) * 1000 / max(1, len(crops))
        probs = torch.softmax(logits, dim=1).numpy()
        return [ModelOutput(
            name=self.spec.name,
            labels=self.spec.labels,
            probabilities=tuple(float(p) for p in pr),
            logits=tuple(float(v) for v in lg),
            bonafide_probability=float(pr[self.spec.bonafide_index]),
            inference_ms=round(ms, 2),
        ) for pr, lg in zip(probs, logits.numpy())]

    def gradcam(self, crop: np.ndarray, class_index: int) -> np.ndarray:
        """Grad-CAM over the patch tokens entering the last block (14x14, values in [0, 1])."""
        x = preprocess([crop]).to(self.device)
        captured = {}

        def hook(_module, _inp, out):
            out.retain_grad()
            captured["a"] = out

        with self._lock:
            handle = self.model.blocks[-1].norm1.register_forward_hook(hook)
            try:
                with torch.enable_grad():
                    self.model.zero_grad(set_to_none=True)
                    logits = self.model(x)
                    logits[0, class_index].backward()
            finally:
                handle.remove()
            a = captured["a"][0, 1:, :].detach()           # (196, C)
            g = captured["a"].grad[0, 1:, :]
            self.model.zero_grad(set_to_none=True)
        side = int(a.shape[0] ** 0.5)
        cam = torch.relu((a * g.mean(dim=0)).sum(dim=1)).reshape(side, side).cpu().numpy()
        return cam / cam.max() if cam.max() > 0 else cam


def fuse(outputs: Sequence[ModelOutput], weights: dict[str, float]) -> dict[str, float]:
    """Fused distribution over CATEGORY_LABELS (sums to 1).

    * bona fide probability: weighted mean of every model's bona fide probability;
    * the remaining (attack) mass is split between presentation attack / deepfake /
      synthetic using only models that can tell attack types apart (the 4-class model),
      weighted and normalised. A binary model's "attack" output says *whether*, not
      *which*, so it does not take part in the split. Without any typing model the whole
      attack mass is a presentation attack.
    """
    total = sum(weights[o.name] for o in outputs)
    bonafide = sum(weights[o.name] * o.bonafide_probability for o in outputs) / total
    split = np.zeros(len(CATEGORY_LABELS) - 1)
    for o in outputs:
        idx = SPECS[o.name].category_index[1:]
        if sum(i is not None for i in idx) < 2:
            continue
        cond = np.array([o.probabilities[i] if i is not None else 0.0 for i in idx])
        if cond.sum() > 0:
            split += weights[o.name] * cond / cond.sum()
    if split.sum() == 0:
        split[0] = 1.0                                         # presentation_attack
    split = split / split.sum() * (1.0 - bonafide)
    return {label: float(p) for label, p in zip(CATEGORY_LABELS, [bonafide, *split])}
