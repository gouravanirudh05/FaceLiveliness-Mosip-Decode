#!/usr/bin/env python3
"""Turn MockMDS into a live L0 face device: feed webcam (or video file) frames into its face stream.

MockMDS (mosip-mock-services, SBI 0.9.5) re-reads its face stream image
`Biometric Devices/Face/Stream Image/0.jpeg` (relative to its working directory, i.e. MockMDS/target)
for every frame it streams, about every 30 ms. This script keeps replacing that file atomically with
the latest camera frame, so the Registration Client's face stream, and therefore liveness, sees a live
person. MockMDS code is not changed. The original image is restored on exit.

Frames are written un-mirrored, as a real device sends them.
RCAPTURE still returns MockMDS's profile face (ISO data), not the camera frame; that is a MockMDS limit.

Run in the face-liveness-passive conda env (it has OpenCV):
    python mosip/tools/mockmds_webcam_feeder.py                      # camera 0
    python mosip/tools/mockmds_webcam_feeder.py --source clip.mp4    # video file, looped
"""
from __future__ import annotations

import argparse
import os
import shutil
import signal
import sys
import time
from pathlib import Path

import cv2

REPO = Path(__file__).resolve().parents[2]
DEFAULT_TARGET = REPO / "mosip/mosip-mock-services/MockMDS/target/Biometric Devices/Face/Stream Image/0.jpeg"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--camera", type=int, default=0, help="camera index (default 0)")
    ap.add_argument("--source", help="video file instead of a camera (looped)")
    ap.add_argument("--target", type=Path, default=DEFAULT_TARGET, help="MockMDS face stream image")
    ap.add_argument("--fps", type=float, default=25.0, help="frames written per second (default 25)")
    ap.add_argument("--width", type=int, default=640)
    ap.add_argument("--height", type=int, default=480)
    ap.add_argument("--jpeg-quality", type=int, default=90)
    ap.add_argument("--max-seconds", type=float, default=0, help="stop after this many seconds (0 = run until Ctrl-C)")
    args = ap.parse_args()

    target: Path = args.target
    if not target.parent.is_dir():
        print(f"MockMDS stream image folder not found: {target.parent}\n"
              "Build MockMDS first (mvn clean install in mosip/mosip-mock-services/MockMDS).", file=sys.stderr)
        return 2
    backup = target.with_suffix(".jpeg.orig")
    if target.exists() and not backup.exists():
        shutil.copy2(target, backup)

    cap = cv2.VideoCapture(args.source if args.source else args.camera)
    if not args.source:
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, args.width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, args.height)
    if not cap.isOpened():
        print(f"cannot open {'video ' + args.source if args.source else 'camera %d' % args.camera}", file=sys.stderr)
        return 1

    stop = False

    def on_signal(*_):
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)

    tmp = target.with_name(".feeder-tmp.jpeg")
    interval = 1.0 / args.fps
    started = time.monotonic()
    written = 0
    print(f"feeding {'video ' + args.source if args.source else 'camera %d' % args.camera} -> {target}  (Ctrl-C to stop)",
          flush=True)
    try:
        while not stop:
            t0 = time.monotonic()
            ok, frame = cap.read()
            if not ok:
                if args.source:                       # loop the video
                    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    continue
                print("camera read failed", file=sys.stderr)
                return 1
            ok, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, args.jpeg_quality])
            if ok:
                tmp.write_bytes(jpeg.tobytes())
                os.replace(tmp, target)               # atomic: MockMDS never reads a half-written file
                written += 1
            if args.max_seconds and time.monotonic() - started >= args.max_seconds:
                break
            time.sleep(max(0.0, interval - (time.monotonic() - t0)))
    finally:
        cap.release()
        if backup.exists():
            shutil.copy2(backup, target)
        tmp.unlink(missing_ok=True)
        print(f"stopped after {written} frames; original MockMDS stream image restored", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
