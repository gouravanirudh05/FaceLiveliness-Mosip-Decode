"""Performance and interoperability tests for the face liveness integration.

Runs against the same interfaces the Registration Client uses:
  * the liveness engine over gRPC (127.0.0.1:50052, AnalyzeImage / HybridSession / GetInfo), and
  * the L0/L1 face device over SBI HTTP (MockMDS on 127.0.0.1:4501: MOSIPDISC, MOSIPDINFO, STREAM).

Performance
  P1  per-frame passive liveness latency (p50 / p95 / max) at 640x480, 1280x720 and 1920x1080,
      with the engine's own stage breakdown (quality, models, cues)
  P2  hybrid session time-to-decision for a bona fide face streamed at 10 fps
  P3  SBI face stream throughput (frames per second the device delivers)

Interoperability
  I1  frame encodings: one face as JPEG q95, JPEG q60, PNG, BMP, WebP, raw RGB, raw BGR -> same decision
  I2  resolutions / aspect ratios: 480p, 720p, 1080p, portrait 720x1280 -> same decision
  I3  invalid / incomplete frame data is rejected with INVALID_ARGUMENT (no crash, engine stays up)
  I4  SBI device discovery and capability (MOSIPDISC, MOSIPDINFO: spec version, purpose, status)
  I5  SBI STREAM frames are valid JPEG and are analysed by the engine
  I6  a printed-photo replay escalates from passive to an active challenge (hybrid policy)

Usage (engine and MockMDS running, e.g. mosip/scripts/start-services.sh):
  python mosip/tools/perf_interop.py [--out report.json] [--runs 15] [--no-device]
Exit status 0 when every interoperability check passes.
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import queue
import statistics
import sys
import threading
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "face-liveness-passive" / "src"))
sys.path.insert(0, str(REPO / "face-liveness-active" / "src"))

import grpc  # noqa: E402
import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

from active_liveness.grpc_gen import active_liveness_pb2 as apb  # noqa: E402
from passive_liveness.grpc_gen import passive_liveness_pb2 as pb  # noqa: E402
from passive_liveness.grpc_gen import passive_liveness_pb2_grpc as pb_grpc  # noqa: E402

FACE = REPO / "face-liveness-passive" / "tests" / "data" / "portrait.jpg"
PRINT = REPO / "face-liveness-passive" / "models" / "onnx" / "fixtures" / "frame-portrait-print.png"
DECISIONS = {v: k for k, v in pb.Decision.items()}


# ---------------------------------------------------------------- helpers

def canvas(face: Image.Image, w: int, h: int) -> Image.Image:
    """The face scaled to ~45 % of the frame height, centred on a neutral background (a camera-like frame)."""
    img = Image.new("RGB", (w, h), (118, 122, 128))
    s = 0.45 * h / face.height
    f = face.resize((max(1, int(face.width * s)), max(1, int(face.height * s))), Image.BICUBIC)
    img.paste(f, ((w - f.width) // 2, (h - f.height) // 2))
    return img


def encode(img: Image.Image, fmt: str, **kw) -> bytes:
    b = io.BytesIO()
    img.save(b, fmt, **kw)
    return b.getvalue()


def pct(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(p / 100 * (len(xs) - 1))))]


class Report:
    def __init__(self):
        self.performance: dict = {}
        self.interop: list[dict] = []

    def check(self, cid: str, name: str, ok: bool, detail):
        self.interop.append({"id": cid, "check": name, "passed": bool(ok), "detail": detail})
        print(f"  [{'PASS' if ok else 'FAIL'}] {cid} {name}: {detail}", flush=True)


def analyse(stub, data: bytes, encoding=0, w=0, h=0):
    t = time.perf_counter()
    r = stub.AnalyzeImage(pb.AnalyzeImageRequest(data=data, encoding=encoding, width=w, height=h), timeout=60)
    return r, (time.perf_counter() - t) * 1000


# ---------------------------------------------------------------- engine tests

def perf_latency(stub, rep: Report, face: Image.Image, runs: int):
    print("P1 per-frame passive latency", flush=True)
    out = {}
    for w, h in [(640, 480), (1280, 720), (1920, 1080)]:
        data = encode(canvas(face, w, h), "JPEG", quality=90)
        analyse(stub, data)  # warm-up
        lat, stages = [], {}
        for _ in range(runs):
            r, ms = analyse(stub, data)
            lat.append(ms)
            for k, v in r.timings_ms.items():
                stages.setdefault(k, []).append(v)
        out[f"{w}x{h}"] = {"runs": runs, "p50_ms": round(pct(lat, 50), 1), "p95_ms": round(pct(lat, 95), 1),
                           "max_ms": round(max(lat), 1),
                           "engine_stages_mean_ms": {k: round(statistics.mean(v), 1) for k, v in stages.items()}}
        print(f"  {w}x{h}: {out[f'{w}x{h}']}", flush=True)
    rep.performance["passive_frame_latency"] = out


def hybrid_run(stub, frames: list[bytes], fps: float, workflow=apb.WORKFLOW_RESIDENT, until_challenge=False,
               timeout_s=60.0):
    """Streams frames into a hybrid session; returns (decision or None, first active prompt or None, seconds, log)."""
    q: queue.Queue = queue.Queue()
    q.put(pb.HybridClientMessage(start=pb.HybridStart(workflow=workflow)))
    stop = threading.Event()

    def requests():
        while True:
            m = q.get()
            if m is None:
                return
            yield m

    def feeder():
        i, t0 = 0, time.time()
        while not stop.is_set():
            ts = int((time.time() - t0) * 1000) + 1
            q.put(pb.HybridClientMessage(frame=apb.Frame(data=frames[i % len(frames)],
                                                         encoding=apb.FRAME_ENCODING_JPEG, timestamp_ms=ts)))
            i += 1
            time.sleep(1.0 / fps)

    start = time.perf_counter()
    th = threading.Thread(target=feeder, daemon=True)
    th.start()
    decision, challenge, log = None, None, []
    try:
        for msg in stub.HybridSession(requests(), timeout=timeout_s):
            kind = msg.WhichOneof("payload")
            log.append(kind)
            if kind == "decision":
                decision = msg.decision
                break
            if kind == "active" and msg.active.WhichOneof("payload") == "challenge_prompt" and challenge is None:
                challenge = msg.active.challenge_prompt
                if until_challenge:
                    q.put(pb.HybridClientMessage(cancel=apb.Cancel()))
            if kind == "error":
                break
    except grpc.RpcError as e:
        log.append(f"rpc:{e.code().name}")
    finally:
        stop.set()
        q.put(None)
    return decision, challenge, time.perf_counter() - start, log


def perf_hybrid(stub, rep: Report, face: Image.Image, runs: int):
    print("P2 hybrid time-to-decision (bona fide, 10 fps)", flush=True)
    frames = [encode(canvas(face, 1280, 720), "JPEG", quality=90)]
    times, statuses = [], []
    for _ in range(max(3, runs // 5)):
        d, _, secs, log = hybrid_run(stub, frames, fps=10)
        statuses.append(pb.HybridStatus.Name(d.status) if d else "NO_DECISION:" + ",".join(log[-3:]))
        times.append(secs)
    rep.performance["hybrid_time_to_decision_s"] = {
        "runs": len(times), "p50": round(pct(times, 50), 2), "max": round(max(times), 2), "statuses": statuses}
    print(f"  {rep.performance['hybrid_time_to_decision_s']}", flush=True)


def interop_encodings(stub, rep: Report, face: Image.Image):
    print("I1 frame encodings", flush=True)
    img = canvas(face, 1280, 720)
    rgb = np.asarray(img, dtype=np.uint8)
    variants = {
        "jpeg_q95": (encode(img, "JPEG", quality=95), 0),
        "jpeg_q60": (encode(img, "JPEG", quality=60), 0),
        "png": (encode(img, "PNG"), 0),
        "bmp": (encode(img, "BMP"), 0),
        "webp": (encode(img, "WEBP", quality=90), 0),
        "raw_rgb": (rgb.tobytes(), apb.FRAME_ENCODING_RAW_RGB),
        "raw_bgr": (rgb[:, :, ::-1].copy().tobytes(), apb.FRAME_ENCODING_RAW_BGR),
    }
    res = {}
    for name, (data, enc) in variants.items():
        r, _ = analyse(stub, data, enc, img.width, img.height)
        res[name] = (DECISIONS[r.decision], round(r.bonafide_probability, 4) if r.HasField("bonafide_probability") else None)
    decisions = {d for d, _ in res.values()}
    scores = [s for _, s in res.values() if s is not None]
    spread = round(max(scores) - min(scores), 4) if scores else None
    rep.check("I1", "same decision across 7 encodings", len(decisions) == 1 and None not in [s for _, s in res.values()],
              {"results": res, "score_spread": spread})


def interop_resolutions(stub, rep: Report, face: Image.Image):
    print("I2 resolutions / aspect ratios", flush=True)
    res = {}
    for w, h in [(640, 480), (1280, 720), (1920, 1080), (720, 1280)]:
        r, _ = analyse(stub, encode(canvas(face, w, h), "JPEG", quality=90))
        res[f"{w}x{h}"] = (DECISIONS[r.decision], round(r.bonafide_probability, 4) if r.HasField("bonafide_probability") else None)
    rep.check("I2", "same decision across 4 resolutions", len({d for d, _ in res.values()}) == 1, res)


def interop_invalid(stub, rep: Report, face: Image.Image):
    print("I3 invalid / incomplete frames", flush=True)
    jpeg = encode(canvas(face, 640, 480), "JPEG", quality=90)
    cases = {
        "empty": (b"", 0, 0, 0),
        "garbage": (b"\x00\x01not-an-image" * 50, 0, 0, 0),
        "truncated_jpeg": (jpeg[: len(jpeg) // 3], 0, 0, 0),
        "raw_wrong_size": (b"\x00" * 1000, apb.FRAME_ENCODING_RAW_RGB, 640, 480),
        "raw_no_dimensions": (b"\x00" * 921600, apb.FRAME_ENCODING_RAW_RGB, 0, 0),
    }
    out = {}
    for name, (data, enc, w, h) in cases.items():
        try:
            r, _ = analyse(stub, data, enc, w, h)
            out[name] = "accepted:" + DECISIONS[r.decision]
        except grpc.RpcError as e:
            out[name] = e.code().name
    alive = True
    try:
        analyse(stub, jpeg)
    except grpc.RpcError:
        alive = False
    bad = {k: v for k, v in out.items() if v != "INVALID_ARGUMENT" and not v.startswith("accepted:NO_")}
    rep.check("I3", "malformed frames rejected, engine still serving", not bad and alive,
              {"responses": out, "engine_alive_after": alive})


def interop_print_escalates(stub, rep: Report):
    print("I6 printed-photo replay escalates to an active challenge", flush=True)
    if not PRINT.is_file():
        rep.check("I6", "print replay escalates", False, f"fixture missing: {PRINT} (run export_onnx.py)")
        return
    frame = encode(Image.open(PRINT).convert("RGB"), "JPEG", quality=92)
    d, challenge, secs, log = hybrid_run(stub, [frame], fps=10, until_challenge=True)
    ok = challenge is not None and (d is None or d.status != pb.HYBRID_PASSED)
    rep.check("I6", "print replay is not accepted passively", ok,
              {"challenge": challenge.prompt if challenge is not None and hasattr(challenge, "prompt") else str(challenge)[:80],
               "decision": pb.HybridStatus.Name(d.status) if d else None, "seconds": round(secs, 2)})


# ---------------------------------------------------------------- SBI device tests

def sbi(method: str, url: str, body: dict, timeout=15):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method=method,
                                 headers={"Content-Type": "application/json"})
    return urllib.request.urlopen(req, timeout=timeout)


def jwt_payload(token: str) -> dict:
    p = token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(p + "=" * (-len(p) % 4)))


def device_tests(stub, rep: Report, port: int, seconds: float):
    base = f"http://127.0.0.1:{port}"
    print("I4 SBI discovery and capability", flush=True)
    try:
        disc = json.loads(sbi("MOSIPDISC", f"{base}/device", {"type": "Face"}).read())
        dinfo = json.loads(sbi("MOSIPDINFO", f"{base}/info", {}).read())
    except Exception as e:  # noqa: BLE001
        rep.check("I4", "SBI discovery", False, f"device not reachable on {port}: {e}")
        return
    faces = [d for d in disc if d.get("deviceStatus") and "Face" in json.dumps(d.get("digitalId", "")) or d.get("deviceId") == "3"]
    infos = []
    for entry in dinfo:
        di = entry.get("deviceInfo")
        if not di:
            continue
        p = jwt_payload(di) if di.count(".") == 2 else json.loads(base64.urlsafe_b64decode(di + "=" * (-len(di) % 4)))
        dig = p.get("digitalId")
        dig = jwt_payload(dig) if isinstance(dig, str) and dig.count(".") == 2 else dig
        infos.append({"deviceId": p.get("deviceId"), "type": (dig or {}).get("type"), "specVersion": p.get("specVersion"),
                      "purpose": p.get("purpose"), "status": p.get("deviceStatus"), "subIds": p.get("deviceSubId")})
    face_info = [i for i in infos if i["type"] == "Face"]
    rep.check("I4", "face device discovered with Registration purpose and spec version",
              bool(face_info) and face_info[0]["purpose"] == "Registration" and bool(face_info[0]["specVersion"]),
              {"discovered": len(disc), "face": face_info, "face_disc_entries": len(faces)})
    if not face_info:
        return

    print("I5 / P3 SBI STREAM frames", flush=True)
    resp = sbi("STREAM", f"{base}/stream",
               {"deviceId": face_info[0]["deviceId"], "deviceSubId": "0", "timeout": str(int(seconds * 1000) + 5000)},
               timeout=seconds + 15)
    frames, buf, t0 = [], b"", time.time()
    while time.time() - t0 < seconds:
        chunk = resp.read(65536)
        if not chunk:
            break
        buf += chunk
        while True:
            s = buf.find(b"\xff\xd8")
            e = buf.find(b"\xff\xd9", s + 2)
            if s < 0 or e < 0:
                break
            frames.append(buf[s:e + 2])
            buf = buf[e + 2:]
    resp.close()
    elapsed = time.time() - t0
    rep.performance["sbi_stream_fps"] = round(len(frames) / elapsed, 1) if elapsed else 0
    print(f"  stream: {len(frames)} frames in {elapsed:.1f} s", flush=True)
    valid, analysed = 0, {}
    for f in frames[:: max(1, len(frames) // 5)][:5]:
        try:
            Image.open(io.BytesIO(f)).verify()
            valid += 1
            r, _ = analyse(stub, f)
            analysed[DECISIONS[r.decision]] = analysed.get(DECISIONS[r.decision], 0) + 1
        except Exception:  # noqa: BLE001
            pass
    rep.check("I5", "SBI stream frames are valid JPEG and analysable", len(frames) > 0 and valid == min(5, len(frames)),
              {"frames": len(frames), "sampled_valid": valid, "decisions": analysed})


# ---------------------------------------------------------------- main

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--engine", default="127.0.0.1:50052")
    ap.add_argument("--mds-port", type=int, default=4501)
    ap.add_argument("--runs", type=int, default=15)
    ap.add_argument("--stream-seconds", type=float, default=5.0)
    ap.add_argument("--no-device", action="store_true", help="skip the SBI device checks")
    ap.add_argument("--out", type=Path, default=REPO / ".run" / "perf_interop_report.json")
    a = ap.parse_args()

    stub = pb_grpc.PassiveLivenessServiceStub(grpc.insecure_channel(
        a.engine, options=[("grpc.max_send_message_length", 64 << 20), ("grpc.max_receive_message_length", 64 << 20)]))
    info = json.loads(stub.GetInfo(pb.GetInfoRequest(), timeout=15).json)
    face = Image.open(FACE).convert("RGB")
    rep = Report()
    import os
    import platform
    env = {"cpu": platform.processor() or platform.machine(), "cpus": os.cpu_count(), "python": platform.python_version(),
           "models": {k: v.get("sha256", "")[:12] for k, v in info.get("models", {}).items()},
           "accept_threshold": info["config"]["decision"]["accept_threshold"]}
    print("environment:", env, flush=True)

    perf_latency(stub, rep, face, a.runs)
    perf_hybrid(stub, rep, face, a.runs)
    interop_encodings(stub, rep, face)
    interop_resolutions(stub, rep, face)
    interop_invalid(stub, rep, face)
    interop_print_escalates(stub, rep)
    if not a.no_device:
        device_tests(stub, rep, a.mds_port, a.stream_seconds)

    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps({"environment": env, "performance": rep.performance, "interoperability": rep.interop},
                                indent=2, default=str))
    failed = [c["id"] for c in rep.interop if not c["passed"]]
    print(f"\nreport: {a.out}\ninteroperability: {len(rep.interop) - len(failed)}/{len(rep.interop)} passed"
          + (f"; FAILED {failed}" if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
