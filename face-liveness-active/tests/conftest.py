import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from active_liveness.config import load_config  # noqa: E402
from active_liveness.types import Workflow  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = ROOT / "models" / "face_landmarker.task"
SAMPLE_IMAGE = Path(__file__).parent / "data" / "business-person.png"


@pytest.fixture(scope="session")
def app_config():
    return load_config(ROOT / "config" / "default.yaml")


@pytest.fixture
def policy(app_config):
    return app_config.policy_for(Workflow.RESIDENT)


@pytest.fixture
def thresholds(policy):
    return policy.thresholds


@pytest.fixture
def rng():
    return random.Random(1234)
