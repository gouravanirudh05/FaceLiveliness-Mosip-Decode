import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

TESTS = Path(__file__).resolve().parent
ROOT = TESTS.parent
ACTIVE_TESTS = ROOT.parent / "face-liveness-active" / "tests"
sys.path.insert(0, str(TESTS))
sys.path.append(str(ACTIVE_TESTS))          # active module's SimulatedUser (hybrid tests)

from passive_liveness.config import DEFAULT_CONFIG_PATH, load_config, replace  # noqa: E402
from passive_liveness.engine import PassiveLivenessEngine  # noqa: E402
from passive_liveness.models import FAS, UNIFIED, ModelSpec  # noqa: E402
from passive_liveness.types import ModelOutput  # noqa: E402

DATA = TESTS / "data"
PORTRAIT = DATA / "portrait.jpg"            # MediaPipe sample asset
BUSINESS = DATA / "business-person.png"     # MediaPipe sample asset
MODELS = ROOT / "models"
CHECKPOINTS = [MODELS / "fsfm_unified_4class_vitb16.pth", MODELS / "fsfm_fas_mcio_vitb16.pth"]
HAVE_CHECKPOINTS = all(p.is_file() for p in CHECKPOINTS)


def read_rgb(path: Path) -> np.ndarray:
    return cv2.cvtColor(cv2.imread(str(path)), cv2.COLOR_BGR2RGB)


class FakeClassifier:
    """Stands in for an FSFM model. ``fn(crop) -> bona fide probability`` (or a constant);
    the remaining mass goes to ``attack_label``."""

    def __init__(self, spec: ModelSpec, fn, attack_label: str = "presentation_attack"):
        self.spec = spec
        self.fn = fn if callable(fn) else (lambda _crop, v=fn: v)
        self.attack_label = attack_label
        self.calls = 0

    def predict(self, crops):
        out = []
        for c in crops:
            self.calls += 1
            p = float(self.fn(c))
            probs = [0.0] * len(self.spec.labels)
            probs[self.spec.bonafide_index] = p
            idx = self.spec.labels.index(self.attack_label if self.attack_label in self.spec.labels
                                         else "presentation_attack")
            probs[idx] += 1.0 - p
            out.append(ModelOutput(self.spec.name, self.spec.labels, tuple(probs),
                                   tuple(float(np.log(max(x, 1e-6))) for x in probs), probs[self.spec.bonafide_index],
                                   0.1))
        return out

    def gradcam(self, crop, class_index):
        return np.linspace(0, 1, 196, dtype=np.float32).reshape(14, 14)


class Scores:
    """Mutable score source shared by fake classifiers (tests change it mid-session)."""

    def __init__(self, value: float):
        self.value = value

    def __call__(self, _crop):
        return self.value


@pytest.fixture(scope="session")
def config():
    return load_config(DEFAULT_CONFIG_PATH)


@pytest.fixture(scope="session")
def portrait():
    return read_rgb(PORTRAIT)


@pytest.fixture(scope="session")
def business():
    return read_rgb(BUSINESS)


@pytest.fixture
def make_engine(config):
    """make_engine(score, attack_label=..., **config sections) -> engine with fake models."""
    engines = []

    def factory(score=0.9, attack_label="presentation_attack", **sections):
        cfg = replace(config, **sections) if sections else config
        clfs = [FakeClassifier(UNIFIED, score, attack_label), FakeClassifier(FAS, score)]
        e = PassiveLivenessEngine(cfg, classifiers=clfs)
        engines.append(e)
        return e

    yield factory
    for e in engines:
        e.close()


@pytest.fixture(scope="session")
def real_engine(config):
    if not HAVE_CHECKPOINTS:
        pytest.skip("FSFM checkpoints missing - run scripts/download_models.py")
    e = PassiveLivenessEngine(config)
    yield e
    e.close()
