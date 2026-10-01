#!/usr/bin/env python
"""Download the FSFM checkpoints used by the passive liveness engine.

Files come from the Hugging Face repo ``Wolowolo/fsfm-3c`` at a pinned revision and are
verified by sha256. After this, the engine runs fully offline. The weights are licensed
CC BY-NC 4.0 (non-commercial use only); see README.md.

    python scripts/download_models.py            # both models into ./models
    python scripts/download_models.py --only fas
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import urllib.request
from pathlib import Path

REPO = "Wolowolo/fsfm-3c"
REVISION = "59f7b50a1865d53b0cc1c80ec620022c39b11c9a"
MODELS_DIR = Path(__file__).resolve().parents[1] / "models"

# name -> (remote path, local file name, sha256 or None for small text files, size)
FILES = {
    "unified": [
        ("finetuned_models/Unified-detector/v1_Fine-tuned_on_4_classes/checkpoint-min_train_loss.pth",
         "fsfm_unified_4class_vitb16.pth",
         "803f2eb06cda9cc4ee9ba6165001992623473eec374422284ccbaee9edee9550", 1029818789),
    ],
    "fas": [
        ("finetuned_models/MCIO_protocol/Both_MCIO/checkpoint-min_val_loss.pth",
         "fsfm_fas_mcio_vitb16.pth",
         "325ab622baab1df57eb9a0a43ed66ca644155db58759f1f784a4f6b432dd889c", 1029799137),
    ],
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch(remote: str, dest: Path, expected_sha: str, size: int) -> None:
    if dest.exists() and dest.stat().st_size == size and sha256(dest) == expected_sha:
        print(f"ok        {dest.name}")
        return
    part = dest.with_suffix(dest.suffix + ".part")
    start = part.stat().st_size if part.exists() else 0
    url = f"https://huggingface.co/{REPO}/resolve/{REVISION}/{remote}"
    req = urllib.request.Request(url, headers={"Range": f"bytes={start}-"} if start else {})
    with urllib.request.urlopen(req) as r, part.open("ab" if start and r.status == 206 else "wb") as out:
        done = start if r.status == 206 else 0
        while chunk := r.read(1 << 20):
            out.write(chunk)
            done += len(chunk)
            print(f"\r{dest.name}: {done / 1e6:7.1f} / {size / 1e6:.1f} MB", end="", flush=True)
    print()
    got = sha256(part)
    if got != expected_sha:
        part.unlink()
        raise SystemExit(f"sha256 mismatch for {dest.name}: {got}")
    part.rename(dest)
    print(f"verified  {dest.name}")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", choices=sorted(FILES), action="append", help="download only this model")
    ap.add_argument("--dest", type=Path, default=MODELS_DIR)
    args = ap.parse_args(argv)
    args.dest.mkdir(parents=True, exist_ok=True)
    for name in args.only or sorted(FILES):
        for remote, local, sha, size in FILES[name]:
            fetch(remote, args.dest / local, sha, size)


if __name__ == "__main__":
    sys.exit(main())
