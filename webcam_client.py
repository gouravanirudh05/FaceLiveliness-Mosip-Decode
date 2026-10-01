#!/usr/bin/env python
"""Webcam demo client for the liveness services (manual testing).

One client for all three modes:

  active  : challenge-response only        -> active service  (python -m active_liveness.server,  :50051)
  passive : passive PAD only (frame stream) -> passive service (python -m passive_liveness.server, :50052)
  hybrid  : passive first, then challenges   -> passive service (python -m passive_liveness.server, :50052)

    python webcam_client.py --mode hybrid
    python webcam_client.py --mode active --workflow supervisor --passive 0.3
    python webcam_client.py --mode passive --headless --source clip.mp4

Keys:  R = retry (when offered)   N = new session (after a decision)   Q / Esc = quit

Frames are sent un-mirrored, as the services expect; the preview is mirrored (selfie view)
unless --no-mirror-preview. --source feeds a video or image file instead of a camera, and
--headless prints the events instead of opening a window.

Run it in the face-liveness-passive conda environment (it has both modules installed);
the face-liveness-active environment is enough for --mode active.
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

ROOT = Path(__file__).resolve().parent
for src in (ROOT / "face-liveness-active" / "src", ROOT / "face-liveness-passive" / "src"):
    sys.path.insert(0, str(src))

from active_liveness.grpc_gen import active_liveness_pb2 as apb  # noqa: E402
from active_liveness.grpc_gen import active_liveness_pb2_grpc as apb_grpc  # noqa: E402

try:
    from passive_liveness.grpc_gen import passive_liveness_pb2 as pb  # noqa: E402
    from passive_liveness.grpc_gen import passive_liveness_pb2_grpc as pb_grpc  # noqa: E402
except ImportError:          # face-liveness-active environment: only --mode active works
    pb = pb_grpc = None

MODES = ("active", "passive", "hybrid")
DEFAULT_SERVER = {"active": "127.0.0.1:50051", "passive": "127.0.0.1:50052", "hybrid": "127.0.0.1:50052"}
SERVER_COMMAND = {"active": "python -m active_liveness.server", "passive": "python -m passive_liveness.server",
                  "hybrid": "python -m passive_liveness.server"}
WORKFLOWS = {"resident": apb.WORKFLOW_RESIDENT, "operator": apb.WORKFLOW_OPERATOR,
             "supervisor": apb.WORKFLOW_SUPERVISOR}
_END = object()


def name(enum, value: int, prefix: str) -> str:
    return enum.Name(value).removeprefix(prefix).lower()


class FrameSource:
    """Camera index, video file, or a still image (repeated)."""

    def __init__(self, source: str):
        self.still = None
        self.cap = None
        if source.isdigit():
            self.cap = cv2.VideoCapture(int(source))
        else:
            img = cv2.imread(source)
            if img is not None:
                self.still = img
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


# ------------------------------------------------------------------ sessions

class Session:
    """One gRPC stream. Frames are dropped (not queued) when the server falls behind."""

    def __init__(self, jpeg_quality: int):
        self.outbox: queue.Queue = queue.Queue(maxsize=2)
        self.jpeg_quality = jpeg_quality
        self.lock = threading.Lock()
        self.step = ""                  # small grey line at the top
        self.headline = "Connecting..."
        self.detail = ""
        self.result_line = ""           # latest model output (passive / hybrid)
        self.guidance: list[str] = []
        self.progress = 0.0
        self.deadline: float | None = None
        self.retry_offered = False
        self.final_ok: bool | None = None
        self.finished = False
        self.closing = False

    def start(self, first_message, rpc):
        self._send(first_message, block=True)
        self._responses = rpc(self._requests())
        threading.Thread(target=self._read, daemon=True).start()

    # outgoing
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
            pass                         # drop this frame; the server is still busy

    def send_frame(self, bgr: np.ndarray):
        if self.finished:
            return
        ok, jpg = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, self.jpeg_quality])
        if ok:
            self._send(self.wrap_frame(apb.Frame(data=jpg.tobytes(), encoding=apb.FRAME_ENCODING_JPEG,
                                                 timestamp_ms=int(time.monotonic() * 1000))))

    def retry(self):
        with self.lock:
            if not self.retry_offered:
                return
            self.retry_offered = False
            self.guidance = []
        self._send(self.retry_message(), block=True)

    def close(self):
        self.closing = True
        if not self.finished:
            self._send(self.cancel_message(), block=True)
        self.outbox.put(_END)

    # incoming
    def _read(self):
        try:
            for m in self._responses:
                with self.lock:
                    self.handle(m)
        except grpc.RpcError as e:
            with self.lock:
                if self.finished or self.closing:
                    return
                self.headline, self.finished, self.final_ok = f"Connection error: {e.code().name}", True, False
            print(self.headline, flush=True)

    def finish(self, ok: bool, message: str):
        self.headline, self.deadline = message, None
        self.detail = "Press N for a new session, Q to quit"
        self.final_ok, self.finished = ok, True

    # active-service messages (used by the active and hybrid modes)
    def handle_active(self, m):
        kind = m.WhichOneof("payload")
        if kind == "session_started":
            s = m.session_started
            print(f"active session {s.session_id[:8]} started, up to {s.max_attempts} attempts", flush=True)
        elif kind == "challenge_prompt":
            p = m.challenge_prompt
            self.headline, self.detail, self.progress = p.prompt, "", 0.0
            self.step = (f"Attempt {p.attempt} - step {p.step_index + 1}/{p.total_steps} "
                         f"({name(apb.Tier, p.tier, 'TIER_')})")
            self.deadline = time.monotonic() + p.timeout_ms / 1000
            print(f"{self.step}: {p.prompt} [{p.timeout_ms / 1000:.0f}s]", flush=True)
        elif kind == "feedback":
            self.detail, self.progress = m.feedback.message, m.feedback.progress
        elif kind == "challenge_result":
            r = m.challenge_result
            verdict = "passed" if r.passed else apb.FailureReason.Name(r.reason)
            print(f"  step {r.step_index + 1}: {verdict}" + (f" (margin {r.margin:.2f})" if r.passed else ""),
                  flush=True)
        elif kind == "retry_available":
            r = m.retry_available
            self.retry_offered, self.deadline = True, None
            self.headline = r.message
            self.detail = f"Press R to retry ({r.retries_remaining} left)"
            self.guidance = list(r.guidance)
            print(f"retry available ({r.retries_remaining} left): {apb.FailureReason.Name(r.reason)}", flush=True)
        elif kind == "decision":
            d = m.decision
            print(f"active DECISION {apb.DecisionStatus.Name(d.status)}"
                  + (f" ({apb.FailureReason.Name(d.reason)})" if d.reason else ""), flush=True)
            return d
        elif kind == "error":
            print(f"error: {apb.ErrorCode.Name(m.error.code)} {m.error.message}", flush=True)
        return None


class ActiveSession(Session):
    def __init__(self, channel, workflow: int, passive: float | None, jpeg_quality: int):
        super().__init__(jpeg_quality)
        start = apb.StartSession(workflow=workflow)
        if passive is not None:
            start.passive_score = passive
        self.start(apb.ClientMessage(start=start), apb_grpc.ActiveLivenessServiceStub(channel).RunSession)

    def wrap_frame(self, frame):
        return apb.ClientMessage(frame=frame)

    def retry_message(self):
        return apb.ClientMessage(retry=apb.Retry())

    def cancel_message(self):
        return apb.ClientMessage(cancel=apb.Cancel())

    def handle(self, m):
        d = self.handle_active(m)
        if d is not None:
            self.finish(d.status == apb.DECISION_PASSED, d.message)


def frame_text(f) -> str:
    if not f.HasField("bonafide_probability"):
        reasons = ", ".join(name(pb.NonResponseReason, r, "NON_RESPONSE_") for r in f.quality.reasons)
        return f"no decision ({reasons})"
    species = name(pb.PAISpecies, f.suspected_pai_species, "PAI_SPECIES_")
    return (f"{name(pb.Decision, f.decision, 'DECISION_')}  live={f.bonafide_probability:.2f}  "
            f"category={name(pb.AttackCategory, f.attack_category, 'ATTACK_CATEGORY_')}"
            + (f"  pai={species}" if species != "none" else ""))


def result_text(r) -> str:
    score = f"{r.bonafide_probability:.2f}" if r.HasField("bonafide_probability") else "-"
    return (f"{name(pb.Decision, r.decision, 'DECISION_')}  live={score}  "
            f"category={name(pb.AttackCategory, r.attack_category, 'ATTACK_CATEGORY_')}  "
            f"pai={name(pb.PAISpecies, r.suspected_pai_species, 'PAI_SPECIES_')}  "
            f"frames={r.frames_used}/{r.frames_analysed}")


class PassiveSession(Session):
    def __init__(self, channel, jpeg_quality: int):
        super().__init__(jpeg_quality)
        self.step = "Passive liveness"
        self.start(pb.StreamRequest(start=pb.StartStream()), pb_grpc.PassiveLivenessServiceStub(channel).AnalyzeStream)

    def wrap_frame(self, frame):
        return pb.StreamRequest(frame=frame)

    def retry_message(self):
        return None

    def cancel_message(self):
        return pb.StreamRequest(end=pb.EndStream())

    def handle(self, m):
        kind = m.WhichOneof("payload")
        if kind == "frame":
            self.headline = "Look at the camera"
            self.result_line = frame_text(m.frame)
            print("  frame:", self.result_line, flush=True)
        elif kind == "result":
            text = "RESULT " + result_text(m.result)
            print(text, flush=True)
            self.result_line = text
            self.finish(m.result.decision == pb.DECISION_BONAFIDE, text)
        elif kind == "error":
            print("error:", m.error.message, flush=True)


class HybridSession(Session):
    def __init__(self, channel, workflow: int, jpeg_quality: int):
        super().__init__(jpeg_quality)
        self.step = "Hybrid: passive check"
        self.start(pb.HybridClientMessage(start=pb.HybridStart(workflow=workflow)),
                   pb_grpc.PassiveLivenessServiceStub(channel).HybridSession)

    def wrap_frame(self, frame):
        return pb.HybridClientMessage(frame=frame)

    def retry_message(self):
        return pb.HybridClientMessage(retry=apb.Retry())

    def cancel_message(self):
        return pb.HybridClientMessage(cancel=apb.Cancel())

    def handle(self, m):
        kind = m.WhichOneof("payload")
        if kind == "started":
            self.headline = "Look at the camera"
            print(f"hybrid session {m.started.session_id[:8]} started", flush=True)
        elif kind == "passive_progress":
            p = m.passive_progress
            self.progress = p.frames_used / max(1, p.frames_required)
            self.detail = ("" if p.quality.passed else
                           ", ".join(name(pb.NonResponseReason, r, "NON_RESPONSE_") for r in p.quality.reasons))
        elif kind == "passive_verdict":
            v = m.passive_verdict
            self.result_line = "passive: " + result_text(v.result)
            print(self.result_line, "->", name(pb.NextStep, v.next_step, "NEXT_STEP_"), flush=True)
        elif kind == "monitor":
            self.result_line = "monitor: " + frame_text(m.monitor.frame)
        elif kind == "active":
            self.handle_active(m.active)          # the hybrid decision follows separately
        elif kind == "decision":
            d = m.decision
            print(f"DECISION {pb.HybridStatus.Name(d.status)} ({pb.HybridReason.Name(d.reason)})", flush=True)
            self.finish(d.status == pb.HYBRID_PASSED, d.message)
        elif kind == "error":
            print("error:", m.error.message, flush=True)


# ------------------------------------------------------------------ drawing

def wrap(text: str, max_width: int, scale: float, thickness: int) -> list[str]:
    lines, current = [], ""
    for word in text.split():
        candidate = f"{current} {word}".strip()
        if cv2.getTextSize(candidate, cv2.FONT_HERSHEY_SIMPLEX, scale, thickness)[0][0] > max_width and current:
            lines.append(current)
            current = word
        else:
            current = candidate
    return lines + [current] if current else lines


def draw(frame: np.ndarray, s: Session, mode: str) -> np.ndarray:
    h, w = frame.shape[:2]
    out = frame.copy()
    with s.lock:
        step, headline, detail, line, progress = s.step, s.headline, s.detail, s.result_line, s.progress
        guidance, deadline, ok = list(s.guidance), s.deadline, s.final_ok
    color = (255, 255, 255) if ok is None else ((80, 220, 80) if ok else (60, 60, 240))

    cv2.ellipse(out, (w // 2, h // 2), (int(w * 0.17), int(h * 0.3)), 0, 0, 360, (200, 200, 200), 1)
    band = out.copy()
    cv2.rectangle(band, (0, 0), (w, 100), (0, 0, 0), -1)
    cv2.rectangle(band, (0, h - 80), (w, h), (0, 0, 0), -1)
    out = cv2.addWeighted(band, 0.55, out, 0.45, 0)

    cv2.putText(out, f"[{mode}] {step}", (12, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (180, 180, 180), 1, cv2.LINE_AA)
    for i, text in enumerate(wrap(headline, w - 24, 0.65, 2)[:2]):
        cv2.putText(out, text, (12, 56 + 28 * i), cv2.FONT_HERSHEY_SIMPLEX, 0.65, color, 2, cv2.LINE_AA)
    if deadline is not None:
        cv2.putText(out, f"{max(0.0, deadline - time.monotonic()):4.1f}s", (w - 90, 24),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 200, 255), 2, cv2.LINE_AA)
    for i, g in enumerate(guidance):
        cv2.putText(out, g, (24, 130 + 26 * i), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 220, 255), 1, cv2.LINE_AA)
    cv2.putText(out, line[:95], (12, h - 56), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 200, 120), 1, cv2.LINE_AA)
    cv2.putText(out, detail, (12, h - 32), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (230, 230, 230), 1, cv2.LINE_AA)
    cv2.rectangle(out, (12, h - 18), (w - 12, h - 8), (90, 90, 90), 1)
    cv2.rectangle(out, (12, h - 18), (12 + int((w - 24) * min(1.0, progress)), h - 8), (80, 220, 80), -1)
    return out


# ------------------------------------------------------------------ main

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mode", choices=MODES, default="hybrid")
    ap.add_argument("--server", help="host:port (default: 127.0.0.1:50051 for active, :50052 otherwise)")
    ap.add_argument("--camera", default="0", help="camera index (default 0)")
    ap.add_argument("--source", help="video or image file instead of a camera")
    ap.add_argument("--workflow", choices=WORKFLOWS, default="resident", help="active / hybrid modes")
    ap.add_argument("--passive", type=float, help="active mode: passive score in [0,1] to send")
    ap.add_argument("--jpeg-quality", type=int, default=90)
    ap.add_argument("--no-mirror-preview", action="store_true")
    ap.add_argument("--headless", action="store_true", help="no window; print events only")
    ap.add_argument("--max-seconds", type=float, help="stop after this many seconds")
    args = ap.parse_args(argv)

    if args.mode != "active" and pb is None:
        raise SystemExit(f"--mode {args.mode} needs the passive module "
                         "(conda activate face-liveness-passive)")
    if args.passive is not None and args.mode != "active":
        ap.error("--passive only applies to --mode active (passive/hybrid compute the score themselves)")

    address = args.server or DEFAULT_SERVER[args.mode]
    channel = grpc.insecure_channel(address)
    try:
        grpc.channel_ready_future(channel).result(timeout=5)
    except grpc.FutureTimeoutError:
        raise SystemExit(f"cannot reach the {args.mode} liveness service at {address} "
                         f"(start it with: {SERVER_COMMAND[args.mode]})")

    def new_session() -> Session:
        if args.mode == "active":
            return ActiveSession(channel, WORKFLOWS[args.workflow], args.passive, args.jpeg_quality)
        if args.mode == "passive":
            return PassiveSession(channel, args.jpeg_quality)
        return HybridSession(channel, WORKFLOWS[args.workflow], args.jpeg_quality)

    source = FrameSource(args.source or args.camera)
    session = new_session()
    started = time.monotonic()
    window = "Face liveness"
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
            view = frame if args.no_mirror_preview else cv2.flip(frame, 1)
            cv2.imshow(window, draw(view, session, args.mode))
            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27) or cv2.getWindowProperty(window, cv2.WND_PROP_VISIBLE) < 1:
                break
            if key == ord("r"):
                session.retry()
            if key == ord("n") and session.finished:
                session.close()
                session = new_session()
    finally:
        session.close()
        time.sleep(0.2)                   # let the cancel reach the server
        source.close()
        channel.close()
        if not args.headless:
            cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
