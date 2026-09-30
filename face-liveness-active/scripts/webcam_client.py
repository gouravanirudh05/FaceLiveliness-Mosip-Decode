#!/usr/bin/env python
"""Webcam demo client for the active liveness gRPC service (manual testing).

Start the server first:   python -m active_liveness.server
Then run:                 python scripts/webcam_client.py [--camera 0] [--workflow resident] [--passive 0.3]

Keys:  R = retry (when offered)   N = new session (after a decision)   Q / Esc = quit

Frames are sent un-mirrored, as the server expects. The preview window is mirrored
(selfie view) by default for comfort; use --no-mirror-preview to show the raw frames.
--source lets you feed a video or image file instead of a camera, and --headless prints
the events instead of opening a window.
"""

from __future__ import annotations

import argparse
import queue
import sys
import threading
import time
from pathlib import Path

import cv2
import grpc
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from active_liveness.grpc_gen import active_liveness_pb2 as pb  # noqa: E402
from active_liveness.grpc_gen import active_liveness_pb2_grpc as pb_grpc  # noqa: E402

WORKFLOWS = {"resident": pb.WORKFLOW_RESIDENT, "operator": pb.WORKFLOW_OPERATOR,
             "supervisor": pb.WORKFLOW_SUPERVISOR}
_END = object()


class FrameSource:
    """Camera index, video file, or a still image (repeated)."""

    def __init__(self, source: str):
        self.still = None
        if source.isdigit():
            self.cap = cv2.VideoCapture(int(source))
        else:
            img = cv2.imread(source)
            if img is not None:
                self.still, self.cap = img, None
            else:
                self.cap = cv2.VideoCapture(source)
        if self.still is None and not self.cap.isOpened():
            raise SystemExit(f"cannot open video source {source!r}")

    def read(self) -> np.ndarray | None:
        if self.still is not None:
            time.sleep(1 / 25)
            return self.still.copy()
        ok, frame = self.cap.read()
        return frame if ok else None

    def close(self):
        if self.cap is not None:
            self.cap.release()


class Session:
    """One gRPC stream. Frames are dropped (not queued) if the server falls behind."""

    def __init__(self, stub, workflow: int, passive: float | None, jpeg_quality: int):
        self.outbox: queue.Queue = queue.Queue(maxsize=2)
        self.jpeg_quality = jpeg_quality
        self.lock = threading.Lock()
        self.prompt = "Connecting..."
        self.feedback = ""
        self.progress = 0.0
        self.step = ""
        self.deadline: float | None = None
        self.retry_offered = False
        self.guidance: list[str] = []
        self.decision: pb.Decision | None = None
        self.error = ""
        self.log: list[str] = []

        start = pb.StartSession(workflow=workflow)
        if passive is not None:
            start.passive_score = passive
        self._send(pb.ClientMessage(start=start), block=True)
        self._responses = stub.RunSession(self._requests())
        threading.Thread(target=self._read, daemon=True).start()

    # --------------------------------------------------------------- outgoing

    def _requests(self):
        while True:
            msg = self.outbox.get()
            if msg is _END:
                return
            yield msg

    def _send(self, msg, block=False):
        if block:
            self.outbox.put(msg)
            return
        try:
            self.outbox.put_nowait(msg)
        except queue.Full:
            pass  # drop this frame; the server is still busy with earlier ones

    def send_frame(self, bgr: np.ndarray):
        if self.finished:
            return
        ok, jpg = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, self.jpeg_quality])
        if ok:
            self._send(pb.ClientMessage(frame=pb.Frame(
                data=jpg.tobytes(), encoding=pb.FRAME_ENCODING_JPEG,
                timestamp_ms=int(time.monotonic() * 1000))))

    def retry(self):
        with self.lock:
            if not self.retry_offered:
                return
            self.retry_offered = False
            self.guidance = []
        self._send(pb.ClientMessage(retry=pb.Retry()), block=True)

    def close(self):
        if not self.finished:
            self._send(pb.ClientMessage(cancel=pb.Cancel()), block=True)
        self.outbox.put(_END)

    @property
    def finished(self) -> bool:
        return self.decision is not None

    # --------------------------------------------------------------- incoming

    def _read(self):
        try:
            for m in self._responses:
                self._handle(m)
        except grpc.RpcError as e:
            with self.lock:
                self.error = f"connection error: {e.code().name} {e.details()}"
                self.decision = self.decision or pb.Decision(status=pb.DECISION_FAILED,
                                                             message="Service unavailable")
            self._note(self.error)

    def _handle(self, m: pb.ServerMessage):
        kind = m.WhichOneof("payload")
        with self.lock:
            if kind == "session_started":
                s = m.session_started
                self._note(f"session {s.session_id[:8]} started, up to {s.max_attempts} attempts")
            elif kind == "challenge_prompt":
                p = m.challenge_prompt
                self.prompt, self.feedback, self.progress = p.prompt, "", 0.0
                self.step = (f"Attempt {p.attempt} - step {p.step_index + 1}/{p.total_steps} "
                             f"({pb.Tier.Name(p.tier).removeprefix('TIER_').lower()})")
                self.deadline = time.monotonic() + p.timeout_ms / 1000
                self._note(f"{self.step}: {p.prompt} [{p.timeout_ms / 1000:.0f}s]")
            elif kind == "feedback":
                self.feedback, self.progress = m.feedback.message, m.feedback.progress
            elif kind == "challenge_result":
                r = m.challenge_result
                verdict = "passed" if r.passed else pb.FailureReason.Name(r.reason)
                self._note(f"  step {r.step_index + 1}: {verdict}"
                           + (f" (margin {r.margin:.2f})" if r.passed else ""))
            elif kind == "retry_available":
                r = m.retry_available
                self.retry_offered, self.deadline = True, None
                self.prompt = r.message
                self.feedback = f"Press R to retry ({r.retries_remaining} left)"
                self.guidance = list(r.guidance)
                self._note(f"retry available ({r.retries_remaining} left): "
                           f"{pb.FailureReason.Name(r.reason)}")
            elif kind == "decision":
                d = m.decision
                self.decision, self.deadline = d, None
                self.prompt, self.feedback = d.message, "Press N for a new session, Q to quit"
                self._note(f"DECISION {pb.DecisionStatus.Name(d.status)}"
                           + (f" ({pb.FailureReason.Name(d.reason)})" if d.reason else ""))
            elif kind == "error":
                self.error = m.error.message
                self._note(f"error: {pb.ErrorCode.Name(m.error.code)} {m.error.message}")

    def _note(self, line: str):
        self.log.append(line)
        print(line, flush=True)


# ------------------------------------------------------------------- drawing

def wrap(text: str, max_width: int, scale: float, thickness: int) -> list[str]:
    lines, current = [], ""
    for word in text.split():
        candidate = f"{current} {word}".strip()
        width = cv2.getTextSize(candidate, cv2.FONT_HERSHEY_SIMPLEX, scale, thickness)[0][0]
        if width > max_width and current:
            lines.append(current)
            current = word
        else:
            current = candidate
    return lines + [current] if current else lines


def draw(frame: np.ndarray, s: Session) -> np.ndarray:
    h, w = frame.shape[:2]
    out = frame.copy()
    with s.lock:
        prompt, feedback, progress, step = s.prompt, s.feedback, s.progress, s.step
        guidance, decision, deadline = list(s.guidance), s.decision, s.deadline

    color = (255, 255, 255)
    if decision is not None:
        color = (80, 220, 80) if decision.status == pb.DECISION_PASSED else (60, 60, 240)

    # face positioning guide
    cv2.ellipse(out, (w // 2, h // 2), (int(w * 0.17), int(h * 0.3)), 0, 0, 360, (200, 200, 200), 1)

    band = out.copy()
    cv2.rectangle(band, (0, 0), (w, 100), (0, 0, 0), -1)
    cv2.rectangle(band, (0, h - 60), (w, h), (0, 0, 0), -1)
    out = cv2.addWeighted(band, 0.55, out, 0.45, 0)

    cv2.putText(out, step, (12, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (180, 180, 180), 1, cv2.LINE_AA)
    for i, line in enumerate(wrap(prompt, w - 24, 0.7, 2)[:2]):
        cv2.putText(out, line, (12, 56 + 30 * i), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2, cv2.LINE_AA)
    if deadline is not None:
        left = max(0.0, deadline - time.monotonic())
        cv2.putText(out, f"{left:4.1f}s", (w - 90, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                    (0, 200, 255), 2, cv2.LINE_AA)
    cv2.putText(out, feedback, (12, h - 32), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (230, 230, 230), 1, cv2.LINE_AA)
    cv2.rectangle(out, (12, h - 18), (w - 12, h - 8), (90, 90, 90), 1)
    cv2.rectangle(out, (12, h - 18), (12 + int((w - 24) * progress), h - 8), (80, 220, 80), -1)
    for i, g in enumerate(guidance):
        cv2.putText(out, g, (24, 130 + 26 * i), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 220, 255), 1, cv2.LINE_AA)
    return out


# ------------------------------------------------------------------- main

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--server", default="127.0.0.1:50051")
    ap.add_argument("--camera", default="0", help="camera index (default 0)")
    ap.add_argument("--source", help="video or image file instead of a camera")
    ap.add_argument("--workflow", choices=WORKFLOWS, default="resident")
    ap.add_argument("--passive", type=float, help="passive score in [0,1] to send (omit = not sent)")
    ap.add_argument("--jpeg-quality", type=int, default=85)
    ap.add_argument("--no-mirror-preview", action="store_true")
    ap.add_argument("--headless", action="store_true", help="no window; print events only")
    ap.add_argument("--max-seconds", type=float, help="stop after this many seconds")
    args = ap.parse_args(argv)

    channel = grpc.insecure_channel(args.server)
    try:
        grpc.channel_ready_future(channel).result(timeout=5)
    except grpc.FutureTimeoutError:
        raise SystemExit(f"cannot reach the liveness service at {args.server} "
                         f"(start it with: python -m active_liveness.server)")
    stub = pb_grpc.ActiveLivenessServiceStub(channel)
    source = FrameSource(args.source or args.camera)
    session = Session(stub, WORKFLOWS[args.workflow], args.passive, args.jpeg_quality)
    started = time.monotonic()
    window = "Active liveness"

    try:
        while True:
            frame = source.read()
            if frame is None:
                print("video source ended / camera unavailable", flush=True)
                break
            session.send_frame(frame)

            if args.max_seconds and time.monotonic() - started > args.max_seconds:
                break
            if args.headless:
                if session.finished:
                    break
                continue

            view = cv2.flip(frame, 1) if not args.no_mirror_preview else frame
            cv2.imshow(window, draw(view, session))
            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27) or cv2.getWindowProperty(window, cv2.WND_PROP_VISIBLE) < 1:
                break
            if key == ord("r"):
                session.retry()
            if key == ord("n") and session.finished:
                session.close()
                session = Session(stub, WORKFLOWS[args.workflow], args.passive, args.jpeg_quality)
    finally:
        session.close()
        time.sleep(0.2)   # let the cancel reach the server
        source.close()
        channel.close()
        if not args.headless:
            cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
