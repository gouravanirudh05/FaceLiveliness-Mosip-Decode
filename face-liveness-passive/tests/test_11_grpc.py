"""The gRPC service in-process on a random localhost port."""

import json
import random
import threading

import cv2
import grpc
import numpy as np
import pytest

from active_liveness.events import ChallengePrompt
from active_liveness.grpc_gen import active_liveness_pb2 as apb
from conftest import HAVE_CHECKPOINTS, Scores
from passive_liveness import server as server_mod
from passive_liveness.engine import PassiveLivenessEngine
from passive_liveness.grpc_gen import passive_liveness_pb2 as pb
from passive_liveness.grpc_gen import passive_liveness_pb2_grpc as pb_grpc
from passive_liveness.hybrid import ActiveEvent
from passive_liveness.server import PassiveLivenessServicer, build_server
from sim import SimulatedUser
from test_10_hybrid import ScriptedAnalyzer


def jpeg(rgb):
    return cv2.imencode(".jpg", cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))[1].tobytes()


def frame_msg(rgb, ts):
    return apb.Frame(data=jpeg(rgb), encoding=apb.FRAME_ENCODING_JPEG, timestamp_ms=ts)


@pytest.fixture
def serve(make_engine, monkeypatch):
    """serve(score, **config sections) -> (stub, analyzer). Prompts reach the scripted active
    analyzer server-side, so the client only has to keep streaming frames."""
    started = []

    def factory(score, engine=None, **sections):
        engine = engine or make_engine(score, **sections)
        analyzer = ScriptedAnalyzer()
        user = SimulatedUser()
        servicer = PassiveLivenessServicer(engine, active_analyzer_factory=lambda: analyzer,
                                           rng_factory=lambda: random.Random(7))
        original = server_mod.hybrid_to_proto

        def spy(e):
            if isinstance(e, ActiveEvent) and isinstance(e.event, ChallengePrompt):
                policy = servicer._load_active_config().policies[next(iter(servicer._load_active_config().policies))]
                analyzer.pending = list(user.frames_for(e.event, policy.step_params(e.event.step_index)))
            return original(e)

        monkeypatch.setattr(server_mod, "hybrid_to_proto", spy)
        server, port = build_server(engine.config, servicer, address="127.0.0.1:0")
        server.start()
        channel = grpc.insecure_channel(f"127.0.0.1:{port}")
        started.append((server, channel))
        return pb_grpc.PassiveLivenessServiceStub(channel), analyzer

    yield factory
    for server, channel in started:
        channel.close()
        server.stop(None)


# ---------------------------------------------------------------- unary

def test_analyze_image(serve, portrait):
    stub, _ = serve(0.9)
    r = stub.AnalyzeImage(pb.AnalyzeImageRequest(data=jpeg(portrait), explain=True))
    assert r.decision == pb.DECISION_BONAFIDE and r.bonafide_probability == pytest.approx(0.9, abs=1e-5)
    assert r.attack_category == pb.ATTACK_CATEGORY_NONE
    assert r.face.count == 1 and r.face.box.x1 > r.face.box.x0
    assert r.quality.passed and r.HasField("bonafide_probability")
    assert {m.name for m in r.models} == {"unified", "fas"}
    assert set(r.categories) == {"bonafide", "presentation_attack", "deepfake", "synthetic"}
    assert r.heatmap_png.startswith(b"\x89PNG")
    full = json.loads(r.json)
    assert full["decision"] == "bonafide" and full["face"]["count"] == 1


def test_analyze_raw_image_and_errors(serve, portrait):
    stub, _ = serve(0.1)
    h, w = portrait.shape[:2]
    r = stub.AnalyzeImage(pb.AnalyzeImageRequest(data=portrait.tobytes(), encoding=apb.FRAME_ENCODING_RAW_RGB,
                                                 width=w, height=h))
    assert r.decision == pb.DECISION_ATTACK and r.attack_detected
    r = stub.AnalyzeImage(pb.AnalyzeImageRequest(data=jpeg(np.zeros_like(portrait))))
    assert r.decision == pb.DECISION_NON_RESPONSE and list(r.quality.reasons) == [pb.NON_RESPONSE_NO_FACE]
    assert not r.HasField("bonafide_probability")
    with pytest.raises(grpc.RpcError) as e:
        stub.AnalyzeImage(pb.AnalyzeImageRequest(data=b"junk"))
    assert e.value.code() == grpc.StatusCode.INVALID_ARGUMENT


def test_analyze_video(serve, portrait, tmp_path):
    path = tmp_path / "v.mp4"
    h, w = portrait.shape[:2]
    vw = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 25, (w, h))
    for _ in range(30):
        vw.write(cv2.cvtColor(portrait, cv2.COLOR_RGB2BGR))
    vw.release()
    stub, _ = serve(0.9)
    r = stub.AnalyzeVideo(pb.AnalyzeVideoRequest(data=path.read_bytes(), filename_hint="v.mp4", include_frames=True))
    assert r.decision == pb.DECISION_BONAFIDE and r.complete and r.frames_received == 30
    assert len(r.frames) == r.frames_analysed > 0
    assert json.loads(r.json)["frames_used"] == r.frames_used
    with pytest.raises(grpc.RpcError) as e:
        stub.AnalyzeVideo(pb.AnalyzeVideoRequest(data=b"junk"))
    assert e.value.code() == grpc.StatusCode.INVALID_ARGUMENT


def test_get_info(serve):
    stub, _ = serve(0.9)
    info = json.loads(stub.GetInfo(pb.GetInfoRequest()).json)
    assert set(info["models"]) == {"unified", "fas"}
    assert info["config"]["decision"]["accept_threshold"] == 0.8


# ---------------------------------------------------------------- streaming

def test_analyze_stream(serve, portrait):
    stub, _ = serve(0.9, stream={"frames_required": 3, "min_frame_interval_ms": 0})
    msgs = [pb.StreamRequest(start=pb.StartStream(include_frames=True))]
    msgs += [pb.StreamRequest(frame=frame_msg(portrait, 40 * (i + 1))) for i in range(10)]
    got = list(stub.AnalyzeStream(iter(msgs)))
    kinds = [m.WhichOneof("payload") for m in got]
    assert kinds == ["frame", "frame", "frame", "result"]
    res = got[-1].result
    assert res.decision == pb.DECISION_BONAFIDE and res.complete and len(res.frames) == 3


def test_stream_end_early_and_errors(serve, portrait):
    stub, _ = serve(0.2, stream={"frames_required": 5, "min_frame_interval_ms": 0})
    msgs = [pb.StreamRequest(start=pb.StartStream(allow_partial=True)),
            pb.StreamRequest(frame=frame_msg(portrait, 40)),
            pb.StreamRequest(frame=apb.Frame(data=b"bad", encoding=apb.FRAME_ENCODING_JPEG, timestamp_ms=80)),
            pb.StreamRequest(start=pb.StartStream()),
            pb.StreamRequest(frame=frame_msg(portrait, 120)),
            pb.StreamRequest(end=pb.EndStream())]
    got = list(stub.AnalyzeStream(iter(msgs)))
    errors = [m.error.code for m in got if m.HasField("error")]
    assert errors == [pb.ERROR_INVALID_FRAME, pb.ERROR_INVALID_REQUEST]
    res = got[-1].result
    assert res.decision == pb.DECISION_ATTACK and not res.complete and res.frames_used == 2

    got = list(stub.AnalyzeStream(iter([pb.StreamRequest(frame=frame_msg(portrait, 40))])))
    assert got[0].error.code == pb.ERROR_INVALID_REQUEST


# ---------------------------------------------------------------- hybrid

def run_hybrid(stub, image, workflow=apb.WORKFLOW_RESIDENT, max_frames=2000):
    done = threading.Event()

    def requests():
        yield pb.HybridClientMessage(start=pb.HybridStart(workflow=workflow))
        for i in range(max_frames):
            if done.is_set():
                return
            yield pb.HybridClientMessage(frame=frame_msg(image, 40 * (i + 1)))

    out = []
    for m in stub.HybridSession(requests()):
        out.append(m)
        if m.HasField("decision"):
            done.set()
    return out


def test_hybrid_passive_accept(serve, portrait):
    stub, _ = serve(0.95)
    got = run_hybrid(stub, portrait)
    kinds = [m.WhichOneof("payload") for m in got]
    assert kinds == ["started"] + ["passive_progress"] * 5 + ["passive_verdict", "decision"]
    assert got[-2].passive_verdict.next_step == pb.NEXT_STEP_ACCEPT
    d = got[-1].decision
    assert d.status == pb.HYBRID_PASSED and d.reason == pb.HYBRID_REASON_PASSIVE_BONAFIDE


def test_hybrid_attack(serve, portrait):
    stub, _ = serve(0.1)
    d = run_hybrid(stub, portrait)[-1].decision
    assert d.status == pb.HYBRID_FAILED and d.reason == pb.HYBRID_REASON_ATTACK_DETECTED


def test_hybrid_active_path(serve, portrait):
    stub, analyzer = serve(0.6)
    got = run_hybrid(stub, portrait)
    active = [m.active for m in got if m.HasField("active")]
    kinds = [a.WhichOneof("payload") for a in active]
    assert kinds[0] == "session_started"
    prompts = [a.challenge_prompt for a in active if a.HasField("challenge_prompt")]
    assert [p.tier for p in prompts] == [apb.TIER_EASY, apb.TIER_MEDIUM, apb.TIER_HARD]
    assert any(m.HasField("monitor") for m in got)
    d = got[-1].decision
    assert d.status == pb.HYBRID_PASSED and d.reason == pb.HYBRID_REASON_ACTIVE_PASSED
    assert d.passive_score == pytest.approx(0.6, abs=1e-5) and d.active_status == "passed"


def test_hybrid_protocol_errors(serve, portrait):
    stub, _ = serve(0.6)
    got = list(stub.HybridSession(iter([pb.HybridClientMessage(frame=frame_msg(portrait, 40))])))
    assert got[0].error.code == pb.ERROR_INVALID_REQUEST
    got = list(stub.HybridSession(iter([pb.HybridClientMessage(start=pb.HybridStart())])))
    assert got[0].error.code == pb.ERROR_INVALID_REQUEST
    msgs = [pb.HybridClientMessage(start=pb.HybridStart(workflow=apb.WORKFLOW_OPERATOR)),
            pb.HybridClientMessage(retry=apb.Retry()),
            pb.HybridClientMessage(cancel=apb.Cancel())]
    got = list(stub.HybridSession(iter(msgs)))
    assert got[1].error.code == pb.ERROR_INVALID_REQUEST
    assert got[-1].decision.status == pb.HYBRID_CANCELLED


# ---------------------------------------------------------------- real models over gRPC

@pytest.mark.models
@pytest.mark.skipif(not HAVE_CHECKPOINTS, reason="run scripts/download_models.py")
def test_real_models_over_grpc(serve, real_engine, portrait):
    stub, _ = serve(None, engine=real_engine)
    r = stub.AnalyzeImage(pb.AnalyzeImageRequest(data=jpeg(portrait)))
    assert r.decision == pb.DECISION_BONAFIDE
    assert all(m.bonafide_probability > 0.85 for m in r.models)
