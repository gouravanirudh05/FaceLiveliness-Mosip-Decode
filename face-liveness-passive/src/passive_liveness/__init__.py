"""Passive face liveness / presentation attack detection (PAD) built on FSFM ViT models.

Use it in-process (``PassiveLivenessEngine``), over gRPC (``passive_liveness.server``),
or combined with active challenge-response (``passive_liveness.hybrid``).
"""

from .config import ConfigError, PassiveConfig, load_config
from .engine import PassiveLivenessEngine, PassiveStream
from .io import InputError, iter_video, load_image
from .models import ModelError
from .types import (
    AttackCategory, Decision, FrameAnalysis, NonResponseReason, PAISpecies, StreamResult,
)

__all__ = [
    "AttackCategory", "ConfigError", "Decision", "FrameAnalysis", "InputError", "ModelError",
    "NonResponseReason", "PAISpecies", "PassiveConfig", "PassiveLivenessEngine", "PassiveStream",
    "StreamResult", "iter_video", "load_config", "load_image",
]
