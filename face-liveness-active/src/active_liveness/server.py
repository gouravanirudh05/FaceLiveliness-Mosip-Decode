"""gRPC service exposing active liveness sessions to the Registration Client.

Run:  python -m active_liveness.server [--config config/default.yaml]
"""

from __future__ import annotations

import argparse
import logging
import random
from concurrent import futures
from typing import Callable, Iterator

import grpc

from .analyzer import FaceAnalyzer, MediaPipeFaceAnalyzer
from .config import DEFAULT_CONFIG_PATH, AppConfig, load_config
from .events import (
    ENGINE_ERROR_MESSAGE, ChallengePrompt, ChallengeResult, Decision, Event, Feedback,
    RetryAvailable, SessionStarted,
)
from .frames import FrameDecodeError, FrameEncoding, decode_frame
from .grpc_gen import active_liveness_pb2 as pb
from .grpc_gen import active_liveness_pb2_grpc as pb_grpc
from .session import TERMINAL, ActiveLivenessSession, SessionStatus
from .types import Workflow

log = logging.getLogger(__name__)

_WORKFLOWS = {pb.WORKFLOW_RESIDENT: Workflow.RESIDENT,
              pb.WORKFLOW_OPERATOR: Workflow.OPERATOR,
              pb.WORKFLOW_SUPERVISOR: Workflow.SUPERVISOR}
_ENCODINGS = {pb.FRAME_ENCODING_JPEG: FrameEncoding.JPEG,
              pb.FRAME_ENCODING_PNG: FrameEncoding.PNG,
              pb.FRAME_ENCODING_RAW_RGB: FrameEncoding.RAW_RGB,
              pb.FRAME_ENCODING_RAW_BGR: FrameEncoding.RAW_BGR}


class ActiveLivenessServicer(pb_grpc.ActiveLivenessServiceServicer):
    def __init__(
        self,
        config: AppConfig,
        analyzer_factory: Callable[[], FaceAnalyzer] | None = None,
        rng_factory: Callable[[], random.Random | None] = lambda: None,
    ):
        self.config = config
        self.analyzer_factory = analyzer_factory or (lambda: MediaPipeFaceAnalyzer(
            config.service.model_path,
            max_faces=config.service.max_faces,
            mirrored=config.service.input_mirrored,
        ))
        self.rng_factory = rng_factory

    def RunSession(self, request_iterator, context) -> Iterator[pb.ServerMessage]:
        session: ActiveLivenessSession | None = None
        analyzer: FaceAnalyzer | None = None
        try:
            for msg in request_iterator:
                kind = msg.WhichOneof("payload")
                if session is None:
                    if kind != "start":
                        yield _error(pb.ERROR_INVALID_REQUEST, "first message must be StartSession")
                        continue
                    workflow = _WORKFLOWS.get(msg.start.workflow)
                    if workflow is None:
                        yield _error(pb.ERROR_INVALID_REQUEST, "StartSession.workflow is required")
                        continue
                    passive = msg.start.passive_score if msg.start.HasField("passive_score") else None
                    if passive is not None and not 0.0 <= passive <= 1.0:
                        yield _error(pb.ERROR_INVALID_REQUEST, "passive_score must be within [0, 1]")
                        continue
                    policy = self.config.policy_for(workflow)
                    if policy.enabled:
                        try:
                            analyzer = self.analyzer_factory()
                        except Exception as e:
                            log.error("cannot create analyzer: %s: %s", type(e).__name__, e)
                            yield pb.ServerMessage(decision=pb.Decision(
                                status=pb.DECISION_FAILED, reason=pb.FAILURE_ENGINE_ERROR,
                                message=ENGINE_ERROR_MESSAGE))
                            return
                    session = ActiveLivenessSession(policy, workflow, analyzer=analyzer,
                                                    passive_score=passive, rng=self.rng_factory())
                    events = session.start()
                elif kind == "start":
                    yield _error(pb.ERROR_INVALID_REQUEST, "session already started")
                    continue
                elif kind == "frame":
                    if session.status is not SessionStatus.RUNNING:
                        continue  # e.g. device keeps streaming while a retry is pending
                    encoding = _ENCODINGS.get(msg.frame.encoding)
                    if encoding is None:
                        yield _error(pb.ERROR_INVALID_FRAME, "Frame.encoding is required")
                        continue
                    try:
                        rgb = decode_frame(msg.frame.data, encoding, msg.frame.width, msg.frame.height)
                    except FrameDecodeError as e:
                        yield _error(pb.ERROR_INVALID_FRAME, str(e))
                        continue
                    events = session.process_frame(rgb, msg.frame.timestamp_ms)
                elif kind == "retry":
                    if session.status is not SessionStatus.RETRY_AVAILABLE:
                        yield _error(pb.ERROR_INVALID_REQUEST, "no retry is available")
                        continue
                    events = session.retry()
                elif kind == "cancel":
                    events = session.cancel()
                else:
                    yield _error(pb.ERROR_INVALID_REQUEST, "empty message")
                    continue

                for event in events:
                    yield to_proto(event)
                if session.status in TERMINAL:
                    return
        finally:
            if analyzer is not None:
                analyzer.close()


def to_proto(event: Event) -> pb.ServerMessage:
    match event:
        case SessionStarted():
            return pb.ServerMessage(session_started=pb.SessionStarted(
                session_id=event.session_id,
                workflow=pb.Workflow.Value("WORKFLOW_" + event.workflow.name),
                max_attempts=event.max_attempts))
        case ChallengePrompt():
            return pb.ServerMessage(challenge_prompt=pb.ChallengePrompt(
                attempt=event.attempt, step_index=event.step_index, total_steps=event.total_steps,
                actions=[pb.Action.Value("ACTION_" + a.name) for a in event.actions],
                tier=pb.Tier.Value("TIER_" + event.tier.name),
                prompt=event.prompt, timeout_ms=event.timeout_ms))
        case Feedback():
            return pb.ServerMessage(feedback=pb.Feedback(
                code=pb.FeedbackCode.Value("FEEDBACK_" + event.code.name),
                message=event.message, progress=event.progress))
        case ChallengeResult():
            return pb.ServerMessage(challenge_result=pb.ChallengeResult(
                attempt=event.attempt, step_index=event.step_index, passed=event.passed,
                margin=event.margin, reason=_reason(event.reason)))
        case RetryAvailable():
            return pb.ServerMessage(retry_available=pb.RetryAvailable(
                attempt=event.attempt, retries_remaining=event.retries_remaining,
                reason=_reason(event.reason), message=event.message, guidance=list(event.guidance)))
        case Decision():
            return pb.ServerMessage(decision=pb.Decision(
                status=pb.DecisionStatus.Value("DECISION_" + event.status.name),
                reason=_reason(event.reason), message=event.message))
    raise TypeError(f"unknown event {event!r}")


def _reason(reason) -> int:
    return pb.FailureReason.Value("FAILURE_" + reason.name) if reason else pb.FAILURE_REASON_UNSPECIFIED


def _error(code: int, message: str) -> pb.ServerMessage:
    return pb.ServerMessage(error=pb.Error(code=code, message=message))


def build_server(config: AppConfig, servicer: ActiveLivenessServicer | None = None,
                 address: str | None = None) -> tuple[grpc.Server, int]:
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=config.service.max_workers))
    pb_grpc.add_ActiveLivenessServiceServicer_to_server(servicer or ActiveLivenessServicer(config), server)
    port = server.add_insecure_port(address or f"{config.service.host}:{config.service.port}")
    if port == 0:
        raise RuntimeError("could not bind gRPC port")
    return server, port


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Active face liveness gRPC service")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH))
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    config = load_config(args.config)
    if not config.service.model_path.is_file():
        raise SystemExit(f"model not found: {config.service.model_path}")
    server, port = build_server(config)
    server.start()
    log.info("active liveness service listening on %s:%d", config.service.host, port)
    server.wait_for_termination()


if __name__ == "__main__":
    main()
