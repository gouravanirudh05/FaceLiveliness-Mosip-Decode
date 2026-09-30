"""The gRPC service, in-process on a random localhost port.

Flow tests record a session offline with a SimulatedUser and replay the identical
client messages over gRPC (same RNG seed); the server must emit the same events.
"""

import random
from collections import deque

import cv2
import grpc
import numpy as np
import pytest

from active_liveness.events import Decision, DecisionStatus
from active_liveness.grpc_gen import active_liveness_pb2 as pb
from active_liveness.grpc_gen import active_liveness_pb2_grpc as pb_grpc
from active_liveness.server import ActiveLivenessServicer, build_server, to_proto
from active_liveness.session import ActiveLivenessSession
from active_liveness.types import Workflow

from conftest import SAMPLE_IMAGE
from sim import SimulatedUser, drive

SEED = 11
TINY_PNG = cv2.imencode(".png", np.zeros((2, 2, 3), np.uint8))[1].tobytes()


class ReplayAnalyzer:
    """Returns pre-recorded observations keyed by frame timestamp (pixels are ignored)."""

    def __init__(self, by_ts):
        self.by_ts = by_ts
        self.closed = False

    def analyze(self, rgb, ts):
        return self.by_ts[ts]

    def close(self):
        self.closed = True


@pytest.fixture
def service(app_config):
    """Yields (stub, set_analyzer_factory)."""
    holder = {}
    servicer = ActiveLivenessServicer(
        app_config,
        analyzer_factory=lambda: holder["factory"](),
        rng_factory=lambda: random.Random(SEED),
    )
    server, port = build_server(app_config, servicer, address="127.0.0.1:0")
    server.start()
    channel = grpc.insecure_channel(f"127.0.0.1:{port}")
    yield pb_grpc.ActiveLivenessServiceStub(channel), holder
    channel.close()
    server.stop(None)


def start(workflow=pb.WORKFLOW_RESIDENT, passive=None):
    s = pb.StartSession(workflow=workflow)
    if passive is not None:
        s.passive_score = passive
    return pb.ClientMessage(start=s)


def frame(ts, data=TINY_PNG, enc=pb.FRAME_ENCODING_PNG, **kw):
    return pb.ClientMessage(frame=pb.Frame(data=data, encoding=enc, timestamp_ms=ts, **kw))


def record(policy, user, passive):
    s = ActiveLivenessSession(policy, Workflow.RESIDENT, passive_score=passive, rng=random.Random(SEED))
    return drive(s, user)


def replay(stub, holder, tr, passive):
    by_ts = {m[1].timestamp_ms: m[1] for m in tr.client if m[0] == "frame"}
    analyzer = ReplayAnalyzer(by_ts)
    holder["factory"] = lambda: analyzer
    msgs = [start(passive=passive)]
    for m in tr.client:
        msgs.append(frame(m[1].timestamp_ms) if m[0] == "frame" else pb.ClientMessage(retry=pb.Retry()))
    return list(stub.RunSession(iter(msgs))), analyzer


def comparable(msgs):
    out = []
    for m in msgs:
        m = pb.ServerMessage.FromString(m.SerializeToString())
        if m.WhichOneof("payload") == "session_started":
            m.session_started.session_id = ""
        out.append(m)
    return out


# ---------------------------------------------------------------- full flows

def test_passing_session_over_grpc_matches_local_session(service, policy):
    stub, holder = service
    tr = record(policy, SimulatedUser(), passive=0.9)
    assert tr.decision.status is DecisionStatus.PASSED
    got, analyzer = replay(stub, holder, tr, passive=0.9)
    assert comparable(got) == comparable([to_proto(e) for e in tr.events])
    assert got[-1].decision.status == pb.DECISION_PASSED
    assert analyzer.closed


def test_retry_flow_over_grpc(service, policy):
    class FailsFirstAttempt(SimulatedUser):
        def frames_for(self, prompt, step):
            return [] if prompt.attempt == 1 else super().frames_for(prompt, step)

    stub, holder = service
    tr = record(policy, FailsFirstAttempt(), passive=None)
    got, _ = replay(stub, holder, tr, passive=None)
    kinds = [m.WhichOneof("payload") for m in got]
    assert "retry_available" in kinds
    ra = got[kinds.index("retry_available")].retry_available
    assert ra.retries_remaining == 3 and ra.reason == pb.FAILURE_CHALLENGE_TIMEOUT
    prompts = [m.challenge_prompt for m in got if m.HasField("challenge_prompt")]
    assert [p.tier for p in prompts if p.attempt == 2][0] == pb.TIER_MEDIUM
    assert got[-1].decision.status == pb.DECISION_PASSED
    assert comparable(got) == comparable([to_proto(e) for e in tr.events])


# ---------------------------------------------------------------- protocol errors

def test_first_message_must_be_start(service):
    stub, holder = service
    got = list(stub.RunSession(iter([frame(40)])))
    assert got[0].error.code == pb.ERROR_INVALID_REQUEST


def test_workflow_required(service):
    stub, _ = service
    got = list(stub.RunSession(iter([start(workflow=pb.WORKFLOW_UNSPECIFIED)])))
    assert got[0].error.code == pb.ERROR_INVALID_REQUEST


def test_passive_score_out_of_range(service):
    stub, _ = service
    got = list(stub.RunSession(iter([start(passive=2.0)])))
    assert "passive_score" in got[0].error.message


def test_corrupt_frame_is_reported_and_session_continues(service):
    stub, holder = service
    holder["factory"] = lambda: ReplayAnalyzer({})
    msgs = [start(passive=0.9), frame(40, data=b"not an image"),
            frame(80, data=b"\x00" * 10, enc=pb.FRAME_ENCODING_RAW_RGB, width=4, height=4),
            pb.ClientMessage(cancel=pb.Cancel())]
    got = list(stub.RunSession(iter(msgs)))
    errors = [m.error for m in got if m.HasField("error")]
    assert [e.code for e in errors] == [pb.ERROR_INVALID_FRAME, pb.ERROR_INVALID_FRAME]
    assert got[-1].decision.status == pb.DECISION_CANCELLED


def test_retry_when_not_available(service):
    stub, holder = service
    holder["factory"] = lambda: ReplayAnalyzer({})
    got = list(stub.RunSession(iter([start(), pb.ClientMessage(retry=pb.Retry()),
                                     pb.ClientMessage(cancel=pb.Cancel())])))
    assert any(m.error.code == pb.ERROR_INVALID_REQUEST for m in got if m.HasField("error"))


def test_disabled_workflow(app_config):
    import dataclasses
    policies = dict(app_config.policies)
    policies[Workflow.OPERATOR] = dataclasses.replace(policies[Workflow.OPERATOR], enabled=False)
    cfg = dataclasses.replace(app_config, policies=policies)
    server, port = build_server(cfg, ActiveLivenessServicer(cfg, analyzer_factory=lambda: 1 / 0),
                                address="127.0.0.1:0")
    server.start()
    try:
        with grpc.insecure_channel(f"127.0.0.1:{port}") as ch:
            got = list(pb_grpc.ActiveLivenessServiceStub(ch).RunSession(iter([start(pb.WORKFLOW_OPERATOR)])))
        assert got[-1].decision.status == pb.DECISION_DISABLED   # no analyzer was created
    finally:
        server.stop(None)


# ---------------------------------------------------------------- real MediaPipe over gRPC

def test_real_mediapipe_photo_over_grpc(app_config):
    """Default analyzer factory (real FaceLandmarker) with JPEG frames of a photo."""
    server, port = build_server(app_config, ActiveLivenessServicer(
        app_config, rng_factory=lambda: random.Random(SEED)), address="127.0.0.1:0")
    server.start()
    jpeg = cv2.imencode(".jpg", cv2.imread(str(SAMPLE_IMAGE)))[1].tobytes()
    try:
        with grpc.insecure_channel(f"127.0.0.1:{port}") as ch:
            msgs = [start(passive=0.9)] + [frame(40 * (i + 1), jpeg, pb.FRAME_ENCODING_JPEG) for i in range(30)] \
                + [pb.ClientMessage(cancel=pb.Cancel())]
            got = list(pb_grpc.ActiveLivenessServiceStub(ch).RunSession(iter(msgs)))
    finally:
        server.stop(None)
    kinds = [m.WhichOneof("payload") for m in got]
    assert kinds[:2] == ["session_started", "challenge_prompt"]
    assert "feedback" in kinds
    assert not any(m.challenge_result.passed for m in got if m.HasField("challenge_result"))
    assert got[-1].decision.status == pb.DECISION_CANCELLED


# ---------------------------------------------------------------- frame decoding

def test_decode_frame_encodings():
    from active_liveness.frames import FrameDecodeError, FrameEncoding, decode_frame
    rgb = np.zeros((2, 3, 3), np.uint8)
    rgb[..., 0] = 200                                              # red
    bgr = rgb[..., ::-1].copy()
    png = cv2.imencode(".png", bgr)[1].tobytes()
    assert (decode_frame(png, FrameEncoding.PNG) == rgb).all()
    assert (decode_frame(rgb.tobytes(), FrameEncoding.RAW_RGB, 3, 2) == rgb).all()
    assert (decode_frame(bgr.tobytes(), FrameEncoding.RAW_BGR, 3, 2) == rgb).all()
    for bad in [lambda: decode_frame(b"", FrameEncoding.PNG),
                lambda: decode_frame(png[:20], FrameEncoding.PNG),             # truncated
                lambda: decode_frame(rgb.tobytes(), FrameEncoding.RAW_RGB, 0, 2),
                lambda: decode_frame(rgb.tobytes()[:-1], FrameEncoding.RAW_RGB, 3, 2)]:
        with pytest.raises(FrameDecodeError):
            bad()
