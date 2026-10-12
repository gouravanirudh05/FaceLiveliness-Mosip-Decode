"""Passive liveness engine: still images, video files and live frame streams.

    engine = PassiveLivenessEngine.from_config()          # loads the models once
    result = engine.analyze_image("face.jpg")             # FrameAnalysis
    video = engine.analyze_video("clip.mp4")              # StreamResult
    with engine.open_stream() as stream:                  # live frames
        for rgb, ts in camera:
            stream.push(rgb, ts)
            if stream.done:
                break
        final = stream.result()

The engine is thread-safe and meant to be shared; streams are per session.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import replace
from pathlib import Path
from statistics import median
from typing import Callable, Sequence

import cv2
import numpy as np
import torch

from . import cues as cue_mod
from . import quality as quality_mod
from .config import DEFAULT_CONFIG_PATH, DecisionConfig, PassiveConfig, load_config
from .face import DetectedFace, FaceDetector, crop_box, extract_crop
from .io import ImageInput, VideoSource, iter_video, load_image
from .models import FAS, UNIFIED, Classifier, FSFMClassifier, fuse
from .temporal import TemporalTracker, static_face_score
from .types import (
    CATEGORY_LABELS, AttackCategory, Cues, Decision, FaceInfo, FrameAnalysis, ModelOutput,
    NonResponseReason, PAISpecies, Quality, StreamResult,
)

log = logging.getLogger("passive_liveness")
audit_log = logging.getLogger("passive_liveness.audit")

DetectorFactory = Callable[[bool], FaceDetector]   # video_mode -> detector

SPECIES_MIN_INDICATOR = 0.5


def decide(bonafide: float | None, reasons: Sequence[NonResponseReason], cfg: PassiveConfig) -> Decision:
    if bonafide is None or NonResponseReason.MULTIPLE_FACES in reasons:
        return Decision.NON_RESPONSE
    if reasons and cfg.quality.enforce:
        return Decision.NON_RESPONSE
    if bonafide >= cfg.decision.accept_threshold:
        return Decision.BONAFIDE
    if bonafide < cfg.decision.reject_threshold:
        return Decision.ATTACK
    return Decision.UNCERTAIN


def attack_category(categories: dict[str, float]) -> AttackCategory:
    if not categories:
        return AttackCategory.NONE
    top = max(categories, key=categories.get)
    return AttackCategory.NONE if top == "bonafide" else AttackCategory(top)


def suspected_species(decision: Decision, category: AttackCategory, indicators: dict[str, float]) -> PAISpecies:
    """A species is only suggested when the frame is not judged bona fide."""
    if decision not in (Decision.ATTACK, Decision.UNCERTAIN):
        return PAISpecies.NONE
    if indicators:
        name = max(indicators, key=indicators.get)
        if indicators[name] >= SPECIES_MIN_INDICATOR:
            return PAISpecies(name)
    return PAISpecies.UNSPECIFIED if category is AttackCategory.PRESENTATION_ATTACK else PAISpecies.NONE


class PassiveLivenessEngine:
    def __init__(self, config: PassiveConfig | None = None, *,
                 classifiers: Sequence[Classifier] | None = None,
                 detector_factory: DetectorFactory | None = None):
        self.config = config or load_config(DEFAULT_CONFIG_PATH)
        m = self.config.models
        if m.torch_threads:
            torch.set_num_threads(m.torch_threads)
        if classifiers is None:
            classifiers = []
            for spec, entry in ((UNIFIED, m.unified), (FAS, m.fas)):
                if entry.enabled:
                    classifiers.append(FSFMClassifier(
                        spec, m.path(entry), expected_sha256=entry.sha256 if m.verify_sha256 else None))
        if not classifiers:
            raise ValueError("no classifiers enabled")
        self.classifiers = list(classifiers)
        self.weights = {c.spec.name: getattr(m, c.spec.name).weight for c in self.classifiers}
        f = self.config.face
        self._detector_factory = detector_factory or (
            lambda video: FaceDetector(f.landmarker_path, max_faces=f.max_faces, video=video))
        self._image_detector: FaceDetector | None = None
        self._image_lock = threading.Lock()

    @classmethod
    def from_config(cls, path: str | Path = DEFAULT_CONFIG_PATH, **kw) -> "PassiveLivenessEngine":
        return cls(load_config(path), **kw)

    # ------------------------------------------------------------ public API

    def analyze_image(self, image: ImageInput, *, explain: bool | None = None) -> FrameAnalysis:
        rgb = load_image(image)
        with self._image_lock:
            if self._image_detector is None:
                self._image_detector = self._detector_factory(False)
            faces = self._image_detector.detect(rgb)
        result = self.analyze_faces(rgb, faces, 0, explain=explain)
        self._audit("image", result)
        return result

    def analyze_video(self, source: VideoSource, *, max_frames: int | None = None,
                      include_frames: bool = True, explain: bool | None = None,
                      stop_when_complete: bool = False) -> StreamResult:
        """Analyse a whole video (file, URL, camera index, or iterable of frames).

        Frames are sampled every ``stream.min_frame_interval_ms``. All sampled frames are
        analysed unless ``stop_when_complete``; the score aggregates the quality-passing ones.
        """
        with self.open_stream(include_frames=include_frames, explain=explain,
                              enforce_duration=False, keep_going=not stop_when_complete) as stream:
            for rgb, ts in iter_video(source, max_frames=max_frames):
                stream.push(rgb, ts)
                if stop_when_complete and stream.done:
                    break
            return stream.result(allow_partial=True)

    def open_stream(self, *, include_frames: bool = True, explain: bool | None = None,
                    frames_required: int | None = None, enforce_duration: bool = True,
                    keep_going: bool = False, decision: DecisionConfig | None = None) -> "PassiveStream":
        """``keep_going``: keep analysing (and aggregating) sampled frames after ``done``.
        ``decision``: accept/reject thresholds for this stream's result (default: the configured ones)."""
        return PassiveStream(self, include_frames=include_frames, explain=explain,
                             frames_required=frames_required, enforce_duration=enforce_duration,
                             keep_going=keep_going, decision=decision)

    def info(self) -> dict:
        out = {}
        for c in self.classifiers:
            out[c.spec.name] = {
                "description": c.spec.description,
                "architecture": c.spec.arch,
                "labels": list(c.spec.labels),
                "weight": self.weights[c.spec.name],
                "file": Path(getattr(c, "path", "")).name or None,
                "sha256": getattr(self.config.models, c.spec.name).sha256 or None,
                "license": "CC BY-NC 4.0 (FSFM, Wang et al., CVPR 2025 / FS-VFM)",
            }
        return out

    def close(self) -> None:
        with self._image_lock:
            if self._image_detector is not None:
                self._image_detector.close()
                self._image_detector = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # ------------------------------------------------------------ core

    def analyze_faces(self, rgb: np.ndarray, faces: list[DetectedFace], timestamp_ms: int,
                      *, explain: bool | None = None) -> FrameAnalysis:
        """Analyse one frame given its detected faces (largest first)."""
        cfg = self.config
        timings = {}
        if not faces:
            return self._no_analysis(timestamp_ms, FaceInfo(count=0), (NonResponseReason.NO_FACE,))
        face = faces[0]
        reasons: list[NonResponseReason] = []
        if len(faces) > 1:
            reasons.append(NonResponseReason.MULTIPLE_FACES)
        h, w = rgb.shape[:2]
        box, clip = crop_box(face.box, w, h, cfg.face.crop_scale)
        info = FaceInfo(count=len(faces), box=face.box, crop_box=box, crop_clip=clip,
                        yaw_deg=round(face.yaw_deg, 2), pitch_deg=round(face.pitch_deg, 2),
                        roll_deg=round(face.roll_deg, 2),
                        eye_blink=None if face.eye_blink is None else round(face.eye_blink, 4),
                        all_boxes=tuple(f.box for f in faces))
        if box[2] - box[0] < 16 or box[3] - box[1] < 16:
            return self._no_analysis(timestamp_ms, info, tuple(reasons) + (NonResponseReason.FACE_CUT_OFF,))
        crop = extract_crop(rgb, box)

        t0 = time.perf_counter()
        q = quality_mod.assess(face, crop, clip, cfg.quality)
        reasons += [r for r in q.reasons if r not in reasons]
        timings["quality"] = _ms(t0)

        t0 = time.perf_counter()
        outputs: list[ModelOutput] = [c.predict([crop])[0] for c in self.classifiers]
        timings["models"] = _ms(t0)
        categories = fuse(outputs, self.weights)
        bonafide = categories["bonafide"]

        cues = Cues()
        if cfg.cues.enabled:
            t0 = time.perf_counter()
            cues = cue_mod.compute(rgb, crop, box, face.box, face.landmarks)
            timings["cues"] = _ms(t0)

        decision = decide(bonafide, reasons, cfg)
        category = attack_category(categories)
        heatmap = None
        if explain if explain is not None else cfg.explain.gradcam:
            t0 = time.perf_counter()
            heatmap = self._heatmap(crop, outputs)
            timings["gradcam"] = _ms(t0)
        return FrameAnalysis(
            timestamp_ms=int(timestamp_ms),
            decision=decision,
            bonafide_probability=round(bonafide, 6),
            attack_detected=decision is Decision.ATTACK,
            categories={k: round(v, 6) for k, v in categories.items()},
            attack_category=category,
            suspected_pai_species=suspected_species(decision, category, cues.indicators),
            face=info,
            quality=replace(q, passed=not reasons, reasons=tuple(reasons)),
            models=tuple(outputs),
            cues=cues,
            timings_ms=timings,
            heatmap_png=heatmap,
        )

    def _no_analysis(self, ts: int, info: FaceInfo, reasons: tuple[NonResponseReason, ...]) -> FrameAnalysis:
        return FrameAnalysis(
            timestamp_ms=int(ts), decision=Decision.NON_RESPONSE, bonafide_probability=None,
            attack_detected=False, categories={}, attack_category=AttackCategory.NONE,
            suspected_pai_species=PAISpecies.NONE, face=info,
            quality=Quality(passed=False, reasons=reasons))

    def _heatmap(self, crop: np.ndarray, outputs: list[ModelOutput]) -> bytes | None:
        """Grad-CAM of the FAS model (or the first model) for its predicted class, over the crop."""
        by_name = {c.spec.name: c for c in self.classifiers}
        clf = by_name.get("fas") or self.classifiers[0]
        out = next(o for o in outputs if o.name == clf.spec.name)
        cam = clf.gradcam(crop, int(np.argmax(out.probabilities)))
        side = 224
        base = cv2.resize(crop, (side, side), interpolation=cv2.INTER_AREA)
        heat = cv2.applyColorMap((cv2.resize(cam, (side, side)) * 255).astype(np.uint8), cv2.COLORMAP_JET)
        blended = cv2.addWeighted(cv2.cvtColor(base, cv2.COLOR_RGB2BGR), 0.55, heat, 0.45, 0)
        ok, png = cv2.imencode(".png", blended)
        return png.tobytes() if ok else None

    def _audit(self, kind: str, r: FrameAnalysis | StreamResult) -> None:
        # Decision metadata only - never pixels, landmarks or other biometric data.
        if audit_log.isEnabledFor(logging.INFO):
            import json
            audit_log.info(json.dumps({
                "event": f"passive_{kind}", "decision": r.decision.value,
                "bonafide_probability": r.bonafide_probability,
                "attack_category": r.attack_category.value,
                "suspected_pai_species": r.suspected_pai_species.value,
            }))


class PassiveStream:
    """Per-session frame stream. Feed frames with strictly increasing timestamps."""

    def __init__(self, engine: PassiveLivenessEngine, *, include_frames: bool, explain: bool | None,
                 frames_required: int | None, enforce_duration: bool, keep_going: bool = False,
                 decision: DecisionConfig | None = None):
        self.engine = engine
        self.cfg = engine.config.stream
        self.decision_config = decision or engine.config.decision
        self.frames_required = frames_required or self.cfg.frames_required
        self.include_frames = include_frames
        self.explain = explain
        self.enforce_duration = enforce_duration
        self.keep_going = keep_going
        self._detector = engine._detector_factory(True)
        self._tracker = TemporalTracker()
        self._frames: list[FrameAnalysis] = []
        self._used: list[FrameAnalysis] = []
        self._received = 0
        self._first_ts: int | None = None
        self._last_ts: int | None = None
        self._last_analysed_ts: int | None = None
        self._timed_out = False
        self._closed = False

    @property
    def done(self) -> bool:
        return len(self._used) >= self.frames_required or self._timed_out

    @property
    def frames_used(self) -> int:
        return len(self._used)

    def push(self, rgb: np.ndarray, timestamp_ms: int) -> FrameAnalysis | None:
        """Analyse a frame if it is due; returns its analysis, or None if it was skipped."""
        if self._closed:
            raise RuntimeError("stream is closed")
        self._received += 1
        ts = int(timestamp_ms)
        if self._last_ts is not None and ts <= self._last_ts:
            return None                                       # out of order / duplicate
        self._last_ts = ts
        if self._first_ts is None:
            self._first_ts = ts
        if self.enforce_duration and ts - self._first_ts > self.cfg.max_duration_ms:
            self._timed_out = True
        if self.done and not self.keep_going:
            return None
        if (self._last_analysed_ts is not None
                and ts - self._last_analysed_ts < self.cfg.min_frame_interval_ms):
            return None
        self._last_analysed_ts = ts
        faces = self._detector.detect(load_image(rgb), ts)
        fa = self.engine.analyze_faces(rgb, faces, ts, explain=self.explain)
        self._frames.append(fa)
        if fa.analysed and fa.face.count == 1:
            self._tracker.add(faces[0].landmarks, faces[0].size, faces[0].blendshapes, fa.bonafide_probability)
        if fa.decision is not Decision.NON_RESPONSE:      # scored and not gated by quality
            self._used.append(fa)
        return fa

    def probe(self, rgb: np.ndarray, timestamp_ms: int) -> FrameAnalysis | None:
        """Analyse one frame with this stream's face tracker without adding it to the
        aggregate (used to keep monitoring after the result). None if out of order."""
        ts = int(timestamp_ms)
        if self._last_ts is not None and ts <= self._last_ts:
            return None
        self._last_ts = ts
        faces = self._detector.detect(load_image(rgb), ts)
        return self.engine.analyze_faces(rgb, faces, ts, explain=False)

    def result(self, *, allow_partial: bool = False) -> StreamResult:
        """Aggregate. Without ``allow_partial`` fewer than ``frames_required`` usable frames
        is a NON_RESPONSE (INSUFFICIENT_FRAMES); with it, any usable frame yields a score."""
        cfg = replace(self.engine.config, decision=self.decision_config)
        used = self._used
        complete = len(used) >= self.frames_required
        reasons: dict[str, int] = {}
        for f in self._frames:
            for r in f.quality.reasons:
                reasons[r.value] = reasons.get(r.value, 0) + 1
        temporal = self._tracker.cues()
        static = static_face_score(temporal)
        temporal = replace(temporal, static_face=static)

        if not used or (not complete and not allow_partial):
            reasons[NonResponseReason.INSUFFICIENT_FRAMES.value] = 1
            bonafide, categories = None, {}
            decision, category, species, indicators = Decision.NON_RESPONSE, AttackCategory.NONE, PAISpecies.NONE, {}
        else:
            scores = [f.bonafide_probability for f in used]
            agg = {"mean": float(np.mean(scores)), "median": float(median(scores)), "min": float(min(scores))}
            bonafide = agg[cfg.stream.aggregation]
            categories = {k: float(np.mean([f.categories[k] for f in used])) for k in CATEGORY_LABELS}
            categories = {k: round(v, 6) for k, v in categories.items()}
            decision = decide(bonafide, (), cfg)
            category = attack_category(categories)
            indicators = {}
            names = {n for f in used for n in f.cues.indicators}
            for n in sorted(names):
                indicators[n] = float(np.mean([f.cues.indicators.get(n, 0.0) for f in used]))
            if static is not None and "print" in indicators:
                # a rigid, non-blinking face is evidence for a print (or a still image on a screen)
                indicators["print"] = min(1.0, indicators["print"] + 0.4 * static)
            indicators = {k: round(v, 4) for k, v in indicators.items()}
            species = suspected_species(decision, category, indicators)
            bonafide = round(bonafide, 6)

        result = StreamResult(
            decision=decision,
            bonafide_probability=bonafide,
            attack_detected=decision is Decision.ATTACK,
            categories=categories,
            attack_category=category,
            suspected_pai_species=species,
            pai_indicators=indicators,
            frames_received=self._received,
            frames_analysed=len(self._frames),
            frames_used=len(used),
            complete=complete,
            duration_ms=(self._last_ts - self._first_ts) if self._first_ts is not None else 0,
            non_response_reasons=reasons,
            temporal=temporal,
            thresholds={"accept": cfg.decision.accept_threshold, "reject": cfg.decision.reject_threshold},
            models=self.engine.info(),
            frames=tuple(self._frames) if self.include_frames else (),
        )
        self.engine._audit("stream", result)
        return result

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._detector.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def _ms(t0: float) -> float:
    return round((time.perf_counter() - t0) * 1000, 2)
