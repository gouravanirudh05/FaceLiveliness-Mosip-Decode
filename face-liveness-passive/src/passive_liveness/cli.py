"""Command line: analyse images, videos or a camera in-process and print JSON.

    passive-liveness face.jpg                       # one or more images
    passive-liveness clip.mp4 --frames             # video, with per-frame detail
    passive-liveness --camera 0 --seconds 3        # live camera, aggregate result
    passive-liveness face.jpg --heatmap out.png    # also save the Grad-CAM overlay
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from .config import DEFAULT_CONFIG_PATH, load_config
from .evaluate import VIDEO_EXT
from .io import InputError


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="*", type=Path, help="image or video files")
    ap.add_argument("--camera", type=int, help="analyse this camera index instead of files")
    ap.add_argument("--seconds", type=float, default=5.0, help="camera: maximum capture time")
    ap.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    ap.add_argument("--frames", action="store_true", help="videos/camera: include per-frame analyses")
    ap.add_argument("--heatmap", type=Path, help="images: write the Grad-CAM overlay PNG here")
    ap.add_argument("--compact", action="store_true", help="one JSON object per line")
    args = ap.parse_args(argv)
    if not args.inputs and args.camera is None:
        ap.error("give image/video files or --camera")

    from .engine import PassiveLivenessEngine
    engine = PassiveLivenessEngine(load_config(args.config))

    def emit(source: str, result) -> None:
        d = {"source": source, **result.to_dict()}
        print(json.dumps(d) if args.compact else json.dumps(d, indent=2), flush=True)

    try:
        return _run(args, engine, emit)
    finally:
        engine.close()      # MediaPipe can deadlock if its landmarker is left to the garbage collector


def _run(args, engine, emit) -> int:
    status = 0
    if args.camera is not None:
        from .io import iter_video
        deadline = time.monotonic() + args.seconds
        with engine.open_stream(include_frames=args.frames) as stream:
            for rgb, ts in iter_video(args.camera):
                stream.push(rgb, ts)
                if stream.done or time.monotonic() > deadline:
                    break
            emit(f"camera:{args.camera}", stream.result(allow_partial=True))
    for path in args.inputs:
        try:
            if path.suffix.lower() in VIDEO_EXT:
                emit(str(path), engine.analyze_video(path, include_frames=args.frames))
            else:
                r = engine.analyze_image(path, explain=bool(args.heatmap))
                if args.heatmap and r.heatmap_png:
                    out = args.heatmap if len(args.inputs) == 1 else args.heatmap.with_name(
                        f"{args.heatmap.stem}_{path.stem}{args.heatmap.suffix}")
                    out.write_bytes(r.heatmap_png)
                emit(str(path), r)
        except InputError as e:
            print(json.dumps({"source": str(path), "error": str(e)}), file=sys.stderr)
            status = 1
    return status


if __name__ == "__main__":
    sys.exit(main())
