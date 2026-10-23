"""gRPC service: image, video, live stream and hybrid passive + active liveness.

    python -m passive_liveness.server [--config config/default.yaml] [--port 50052]
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import logging
import os
import random
import tempfile
from concurrent import futures
from pathlib import Path
from typing import Callable, Iterator

import grpc

from active_liveness.grpc_gen import active_liveness_pb2 as apb

from .config import DEFAULT_CONFIG_PATH, PassiveConfig, load_config
from .engine import PassiveLivenessEngine
from .grpc_gen import passive_liveness_pb2 as pb
from .grpc_gen import passive_liveness_pb2_grpc as pb_grpc
from .io import FrameEncoding, InputError, decode_frame
from .types import (
    AttackCategory, Decision, FaceInfo, FrameAnalysis, NonResponseReason, PAISpecies, Quality,
    StreamResult,
)

log = logging.getLogger("passive_liveness.server")

DECISION = {Decision.BONAFIDE: pb.DECISION_BONAFIDE, Decision.ATTACK: pb.DECISION_ATTACK,
            Decision.UNCERTAIN: pb.DECISION_UNCERTAIN, Decision.NON_RESPONSE: pb.DECISION_NON_RESPONSE}
CATEGORY = {AttackCategory.NONE: pb.ATTACK_CATEGORY_NONE,
            AttackCategory.PRESENTATION_ATTACK: pb.ATTACK_CATEGORY_PRESENTATION_ATTACK,
            AttackCategory.DEEPFAKE: pb.ATTACK_CATEGORY_DEEPFAKE, AttackCategory.SYNTHETIC: pb.ATTACK_CATEGORY_SYNTHETIC}
SPECIES = {PAISpecies.NONE: pb.PAI_SPECIES_NONE, PAISpecies.PRINT: pb.PAI_SPECIES_PRINT,
           PAISpecies.SCREEN_REPLAY: pb.PAI_SPECIES_SCREEN_REPLAY, PAISpecies.UNSPECIFIED: pb.PAI_SPECIES_UNKNOWN}
REASON = {r: pb.NonResponseReason.Value(f"NON_RESPONSE_{r.name}") for r in NonResponseReason}
ENCODING = {apb.FRAME_ENCODING_UNSPECIFIED: FrameEncoding.ENCODED, apb.FRAME_ENCODING_JPEG: FrameEncoding.ENCODED,
            apb.FRAME_ENCODING_PNG: FrameEncoding.ENCODED, apb.FRAME_ENCODING_RAW_RGB: FrameEncoding.RAW_RGB,
            apb.FRAME_ENCODING_RAW_BGR: FrameEncoding.RAW_BGR}


# ------------------------------------------------------------------ conversion

def _box(b) -> pb.Box | None:
    return pb.Box(x0=b[0], y0=b[1], x1=b[2], y1=b[3]) if b else None


def face_to_proto(f: FaceInfo) -> pb.FaceInfo:
    m = pb.FaceInfo(count=f.count, crop_clip=f.crop_clip, all_boxes=[_box(b) for b in f.all_boxes])
    if f.box:
        m.box.CopyFrom(_box(f.box))
    if f.crop_box:
        m.crop_box.CopyFrom(_box(f.crop_box))
    for name in ("yaw_deg", "pitch_deg", "roll_deg", "eye_blink"):
        if getattr(f, name) is not None:
            setattr(m, name, getattr(f, name))
    return m


def quality_to_proto(q: Quality) -> pb.Quality:
    return pb.Quality(passed=q.passed, reasons=[REASON[r] for r in q.reasons], face_px=q.face_px,
                      sharpness=q.sharpness, brightness=q.brightness, contrast=q.contrast)


def frame_to_proto(fa: FrameAnalysis) -> pb.FrameAnalysis:
    m = pb.FrameAnalysis(
        timestamp_ms=fa.timestamp_ms, decision=DECISION[fa.decision], attack_detected=fa.attack_detected,
        categories=fa.categories, attack_category=CATEGORY[fa.attack_category],
        suspected_pai_species=SPECIES[fa.suspected_pai_species],
        face=face_to_proto(fa.face), quality=quality_to_proto(fa.quality),
        models=[pb.ModelOutput(name=o.name, probabilities=o.as_map, logits=o.logits, labels=o.labels,
                               bonafide_probability=o.bonafide_probability, inference_ms=o.inference_ms)
                for o in fa.models],
        cues=pb.Cues(values=fa.cues.values, indicators=fa.cues.indicators, evidence=fa.cues.evidence),
        timings_ms=fa.timings_ms, heatmap_png=fa.heatmap_png or b"",
        json=json.dumps(fa.to_dict()),
    )
    if fa.bonafide_probability is not None:
        m.bonafide_probability = fa.bonafide_probability
    return m


def stream_to_proto(r: StreamResult) -> pb.StreamResult:
    t = r.temporal
    temporal = pb.TemporalCues(frames=t.frames)
    for name in ("head_motion", "expression_range", "blink_detected", "static_face", "score_std"):
        if getattr(t, name) is not None:
            setattr(temporal, name, getattr(t, name))
    d = r.to_dict()
    d.pop("frames")
    m = pb.StreamResult(
        decision=DECISION[r.decision], attack_detected=r.attack_detected, categories=r.categories,
        attack_category=CATEGORY[r.attack_category], suspected_pai_species=SPECIES[r.suspected_pai_species],
        pai_indicators=r.pai_indicators, frames_received=r.frames_received, frames_analysed=r.frames_analysed,
        frames_used=r.frames_used, complete=r.complete, duration_ms=r.duration_ms,
        non_response_reasons=r.non_response_reasons, temporal=temporal, thresholds=r.thresholds,
        frames=[frame_to_proto(f) for f in r.frames], json=json.dumps(d),
    )
    if r.bonafide_probability is not None:
        m.bonafide_probability = r.bonafide_probability
    return m


def decode(frame) -> tuple:
    enc = ENCODING.get(frame.encoding)
    if enc is None:
        raise InputError(f"unsupported encoding {frame.encoding}")
    return decode_frame(frame.data, enc, frame.width, frame.height), int(frame.timestamp_ms)


def _error(code: int, message: str) -> pb.Error:
    return pb.Error(code=code, message=message)


# ------------------------------------------------------------------ servicer

class PassiveLivenessServicer(pb_grpc.PassiveLivenessServiceServicer):
    def __init__(self, engine: PassiveLivenessEngine, *, active_config_loader: Callable | None = None,
                 active_analyzer_factory: Callable | None = None,
                 rng_factory: Callable[[], random.Random | None] = lambda: None):
        self.engine = engine
        self.config: PassiveConfig = engine.config
        self._active_config = None
        self._active_config_loader = active_config_loader
        self._active_analyzer_factory = active_analyzer_factory
        self._rng_factory = rng_factory

    # -------------------------------------------------------------- unary

    def AnalyzeImage(self, request, context):
        try:
            enc = ENCODING.get(request.encoding)
            if enc is None:
                raise InputError(f"unsupported encoding {request.encoding}")
            rgb = decode_frame(request.data, enc, request.width, request.height)
        except InputError as e:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(e))
        try:
            return frame_to_proto(self.engine.analyze_image(rgb, explain=request.explain))
        except InputError as e:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(e))
        except Exception:
            log.exception("image analysis failed")
            context.abort(grpc.StatusCode.INTERNAL, "internal error while analysing the image")

    def AnalyzeVideo(self, request, context):
        if not request.data:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "empty video data")
        suffix = Path(request.filename_hint).suffix or ".mp4"
        fd, path = tempfile.mkstemp(suffix=suffix, prefix="passive_video_")
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(request.data)
            try:
                result = self.engine.analyze_video(path, max_frames=request.max_frames or None,
                                                   include_frames=request.include_frames,
                                                   stop_when_complete=request.stop_when_complete)
            except InputError as e:
                context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(e))
        finally:
            os.unlink(path)
        return stream_to_proto(result)

    def GetInfo(self, request, context):
        models = self.engine.info()
        return pb.ServiceInfo(json=json.dumps({"models": models,
                                               "capabilities": self.capabilities(models),
                                               "config": dataclasses.asdict(self.config)}, default=str))

    def capabilities(self, models: dict) -> dict:
        """What this engine supports, for capability discovery by the Registration Client (diagnostics, policy)."""
        from active_liveness.types import Action
        return {
            "modes": ["passive", "active", "hybrid"],
            "workflows": ["resident", "operator", "supervisor"],
            "challenge_types": [a.value for a in Action],
            "attack_classes": sorted({label for m in models.values() for label in m.get("labels", [])
                                      if label != "bonafide"}),
            "frame_encodings": ["jpeg", "png", "bmp", "webp", "raw_rgb", "raw_bgr"],
            "per_session_policy": True,
            "model_integrity_verified": bool(self.config.models.verify_sha256),
        }

    # -------------------------------------------------------------- streaming

    def AnalyzeStream(self, request_iterator, context) -> Iterator[pb.StreamResponse]:
        stream = None
        allow_partial = False
        try:
            for msg in request_iterator:
                kind = msg.WhichOneof("payload")
                if stream is None:
                    if kind != "start":
                        yield pb.StreamResponse(error=_error(pb.ERROR_INVALID_REQUEST, "first message must be start"))
                        return
                    s = msg.start
                    allow_partial = s.allow_partial
                    stream = self.engine.open_stream(include_frames=s.include_frames, explain=s.explain,
                                                     frames_required=s.frames_required or None)
                    continue
                if kind == "start":
                    yield pb.StreamResponse(error=_error(pb.ERROR_INVALID_REQUEST, "stream already started"))
                    continue
                if kind == "end":
                    break
                try:
                    rgb, ts = decode(msg.frame)
                except InputError as e:
                    yield pb.StreamResponse(error=_error(pb.ERROR_INVALID_FRAME, str(e)))
                    continue
                try:
                    fa = stream.push(rgb, ts)
                except Exception:
                    log.exception("passive stream failed")
                    yield pb.StreamResponse(error=_error(pb.ERROR_INTERNAL, "internal error while analysing the frame"))
                    return
                if fa is not None:
                    yield pb.StreamResponse(frame=frame_to_proto(fa))
                if stream.done:
                    break
            if stream is not None:
                yield pb.StreamResponse(result=stream_to_proto(stream.result(allow_partial=allow_partial)))
        finally:
            if stream is not None:
                stream.close()

    def HybridSession(self, request_iterator, context) -> Iterator[pb.HybridServerMessage]:
        from active_liveness.types import Workflow

        from .hybrid import HybridLivenessSession, HybridStatus, PolicyError

        session = None
        workflows = {apb.WORKFLOW_RESIDENT: Workflow.RESIDENT, apb.WORKFLOW_OPERATOR: Workflow.OPERATOR,
                     apb.WORKFLOW_SUPERVISOR: Workflow.SUPERVISOR}
        try:
            for msg in request_iterator:
                kind = msg.WhichOneof("payload")
                if session is None:
                    if kind != "start" or msg.start.workflow not in workflows:
                        yield pb.HybridServerMessage(error=_error(
                            pb.ERROR_INVALID_REQUEST, "first message must be start with a workflow"))
                        return
                    try:
                        session = HybridLivenessSession(
                            self.engine, self._load_active_config(), workflows[msg.start.workflow],
                            active_analyzer_factory=self._active_analyzer_factory, rng=self._rng_factory(),
                            policy=session_policy_from_proto(msg.start.policy) if msg.start.HasField("policy")
                            else None)
                    except PolicyError as e:
                        yield pb.HybridServerMessage(error=_error(pb.ERROR_INVALID_REQUEST, f"invalid policy: {e}"))
                        return
                    except Exception:
                        log.exception("cannot create hybrid session")
                        yield pb.HybridServerMessage(error=_error(pb.ERROR_INTERNAL, "cannot start the session"))
                        return
                    events = session.start()
                elif kind == "frame":
                    if session.retry_available:
                        continue                       # waiting for Retry; frames are ignored
                    try:
                        rgb, ts = decode(msg.frame)
                    except InputError as e:
                        yield pb.HybridServerMessage(error=_error(pb.ERROR_INVALID_FRAME, str(e)))
                        continue
                    try:
                        events = session.process_frame(rgb, ts)
                    except Exception:
                        log.exception("hybrid session failed")
                        yield pb.HybridServerMessage(error=_error(pb.ERROR_INTERNAL,
                                                                 "internal error while analysing the frame"))
                        return
                elif kind == "retry":
                    if not session.retry_available:
                        yield pb.HybridServerMessage(error=_error(pb.ERROR_INVALID_REQUEST, "no retry available"))
                        continue
                    events = session.retry()
                elif kind == "cancel":
                    events = session.cancel()
                else:
                    yield pb.HybridServerMessage(error=_error(pb.ERROR_INVALID_REQUEST, f"unexpected {kind}"))
                    continue
                for e in events:
                    yield hybrid_to_proto(e)
                if session.status in (HybridStatus.PASSED, HybridStatus.FAILED, HybridStatus.CANCELLED):
                    return
        finally:
            if session is not None:
                session.close()

    def _load_active_config(self):
        if self._active_config is None:
            if self._active_config_loader is not None:
                self._active_config = self._active_config_loader()
            else:
                from active_liveness.config import DEFAULT_CONFIG_PATH as ACTIVE_DEFAULT, load_config as load_active
                self._active_config = load_active(self.config.hybrid.active_config or ACTIVE_DEFAULT)
        return self._active_config


def session_policy_from_proto(p: pb.SessionPolicy):
    from .hybrid import SessionPolicy

    def opt(name):
        return getattr(p, name) if p.HasField(name) else None

    return SessionPolicy(
        accept_threshold=opt("accept_threshold"), reject_threshold=opt("reject_threshold"),
        fail_on_passive_no_response=opt("fail_on_passive_no_response"), active_enabled=opt("active_enabled"),
        min_challenges=opt("min_challenges"), challenge_pool=tuple(p.challenge_pool),
        compound_challenges=opt("compound_challenges"), max_retries=opt("max_retries"),
        step_timeouts_s=tuple(p.step_timeout_s))


def hybrid_to_proto(e) -> pb.HybridServerMessage:
    from active_liveness.server import to_proto as active_to_proto

    from .hybrid import (
        ActiveEvent, HybridDecision, HybridStarted, HybridStatus, MonitorResult, PassiveProgress, PassiveVerdict,
    )
    match e:
        case HybridStarted():
            return pb.HybridServerMessage(started=pb.HybridStarted(
                session_id=e.session_id, workflow=apb.Workflow.Value(f"WORKFLOW_{e.workflow.name}"),
                frames_required=e.frames_required, policy_json=json.dumps(e.policy, sort_keys=True)))
        case PassiveProgress():
            return pb.HybridServerMessage(passive_progress=pb.PassiveProgress(
                frames_used=e.frames_used, frames_required=e.frames_required,
                quality=quality_to_proto(e.frame.quality)))
        case PassiveVerdict():
            return pb.HybridServerMessage(passive_verdict=pb.PassiveVerdict(
                result=stream_to_proto(e.result), next_step=pb.NextStep.Value(f"NEXT_STEP_{e.next_step.name}")))
        case ActiveEvent():
            return pb.HybridServerMessage(active=active_to_proto(e.event))
        case MonitorResult():
            return pb.HybridServerMessage(monitor=pb.MonitorResult(
                frame=frame_to_proto(e.frame), consecutive_attacks=e.consecutive_attacks))
        case HybridDecision():
            status = {HybridStatus.PASSED: pb.HYBRID_PASSED, HybridStatus.FAILED: pb.HYBRID_FAILED,
                      HybridStatus.CANCELLED: pb.HYBRID_CANCELLED}[e.status]
            m = pb.HybridDecision(status=status, reason=pb.HybridReason.Value(f"HYBRID_REASON_{e.reason.name}"),
                                  message=e.message, active_status=e.active_status or "")
            if e.passive_score is not None:
                m.passive_score = e.passive_score
            return pb.HybridServerMessage(decision=m)
    raise TypeError(f"unknown hybrid event {e!r}")


# ------------------------------------------------------------------ server

def build_server(config: PassiveConfig, servicer: PassiveLivenessServicer,
                 address: str | None = None) -> tuple[grpc.Server, int]:
    size = config.service.max_message_mb * 1024 * 1024
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=config.service.max_workers),
                         options=[("grpc.max_receive_message_length", size),
                                  ("grpc.max_send_message_length", size)])
    pb_grpc.add_PassiveLivenessServiceServicer_to_server(servicer, server)
    port = server.add_insecure_port(address or f"{config.service.host}:{config.service.port}")
    if port == 0:
        raise RuntimeError(f"cannot bind {address or config.service.host}")
    return server, port


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Passive face liveness gRPC service")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH))
    parser.add_argument("--port", type=int, help="override service.port")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    config = load_config(args.config)
    engine = PassiveLivenessEngine(config)
    address = f"{config.service.host}:{args.port}" if args.port else None
    server, port = build_server(config, PassiveLivenessServicer(engine), address)
    server.start()
    log.info("passive liveness service listening on %s:%d (models: %s)", config.service.host, port,
             ", ".join(engine.info()))
    server.wait_for_termination()


if __name__ == "__main__":
    main()
