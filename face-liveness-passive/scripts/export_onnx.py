#!/usr/bin/env python3
"""Export the two FSFM checkpoints to ONNX for on-device use (Android Registration Client) and verify them.

For each model this writes ``models/onnx/<name>.onnx`` (input ``input``: float32 N x 3 x 224 x 224, already
preprocessed; output ``logits``) and checks that ONNX Runtime reproduces PyTorch on real face crops.
Optionally a dynamically quantised int8 copy is written and checked the same way (``--int8``).

It also writes fixtures for the Android port's parity tests (``models/onnx/fixtures``): face crops as PNG, the
exact preprocessed tensors (PIL bicubic 256 -> centre 224 -> normalise) as little-endian float32, and the
reference probabilities. A ``manifest.json`` records file sizes and SHA-256 sums.

Usage (face-liveness-passive env):  python scripts/export_onnx.py [--int8]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from passive_liveness.config import load_config  # noqa: E402
from passive_liveness.face import FaceDetector, crop_box, extract_crop  # noqa: E402
from passive_liveness.io import load_image  # noqa: E402
from passive_liveness.models import FAS, UNIFIED, FSFMClassifier, preprocess, sha256_of  # noqa: E402

OUT = ROOT / "models" / "onnx"


def softmax(x: np.ndarray) -> np.ndarray:
    e = np.exp(x - x.max(axis=1, keepdims=True))
    return e / e.sum(axis=1, keepdims=True)


def face_crops(cfg) -> list[tuple[str, np.ndarray]]:
    """Real face crops made by the service's own pipeline: sample photos, mirrored, and synthetic attacks."""
    import cv2
    import synth
    out = []
    with FaceDetector(cfg.face.landmarker_path, max_faces=cfg.face.max_faces) as det:
        for name in ("portrait.jpg", "business-person.png"):
            rgb = load_image(str(ROOT / "tests" / "data" / name))
            face = det.detect(rgb)[0]
            head = synth.head_shot(rgb, face.box)
            for tag, img in (("orig", rgb), ("mirror", np.ascontiguousarray(rgb[:, ::-1])),
                             ("print", synth.printed_photo(head)), ("screen", synth.screen_replay(head))):
                faces = det.detect(img)
                if faces:
                    box, _ = crop_box(faces[0].box, img.shape[1], img.shape[0], cfg.face.crop_scale)
                    out.append((f"{Path(name).stem}-{tag}", extract_crop(img, box)))
    del cv2
    return out


def export(clf: FSFMClassifier, path: Path) -> None:
    dummy = torch.zeros(1, 3, 224, 224)
    torch.onnx.export(clf.model, dummy, str(path), input_names=["input"], output_names=["logits"],
                      dynamic_axes={"input": {0: "batch"}, "logits": {0: "batch"}}, opset_version=17,
                      dynamo=False)


def check(path: Path, batch: torch.Tensor, ref: np.ndarray, spec) -> dict:
    import onnxruntime as ort
    sess = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
    got = softmax(sess.run(["logits"], {"input": batch.numpy()})[0])
    diff = np.abs(got - ref)
    flips = int(np.sum(np.argmax(got, 1) != np.argmax(ref, 1)))
    bona = np.abs(got[:, spec.bonafide_index] - ref[:, spec.bonafide_index])
    return {"max_abs_prob_diff": float(diff.max()), "max_bonafide_diff": float(bona.max()),
            "argmax_changes": flips, "samples": int(len(ref))}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--int8", action="store_true", help="also write and check a dynamically quantised int8 model")
    args = ap.parse_args()

    cfg = load_config()
    OUT.mkdir(parents=True, exist_ok=True)
    fixtures = OUT / "fixtures"
    fixtures.mkdir(exist_ok=True)

    crops = face_crops(cfg)
    batch = preprocess([c for _, c in crops])
    manifest = {"input": {"name": "input", "shape": ["N", 3, 224, 224], "dtype": "float32",
                          "preprocess": "square face crop -> PIL bicubic 256x256 -> centre crop 224 -> /255 -> "
                                        "(x - mean) / std",
                          "mean": [0.5482207536697388, 0.42340534925460815, 0.3654651641845703],
                          "std": [0.2789176106452942, 0.2438540756702423, 0.23493893444538116]},
                "models": {}, "fixtures": []}

    from PIL import Image
    for name, crop in crops:
        Image.fromarray(crop).save(fixtures / f"{name}.png")
        Image.fromarray(crop).save(fixtures / f"{name}.ppm")  # raw RGB for the Android JVM tests (no ImageIO there)
        t = preprocess([crop]).numpy().astype("<f4")
        t.tofile(fixtures / f"{name}.input.f32")
        manifest["fixtures"].append(name)

    for spec in (UNIFIED, FAS):
        mcfg = getattr(cfg.models, spec.name)
        clf = FSFMClassifier(spec, cfg.models.path(mcfg), expected_sha256=mcfg.sha256 or None)
        with torch.no_grad():
            ref = softmax(clf.model(batch).numpy())
        for (name, _), p in zip(crops, ref):
            (fixtures / f"{name}.{spec.name}.json").write_text(json.dumps(
                {"labels": list(spec.labels), "probabilities": [float(x) for x in p],
                 "bonafide_index": spec.bonafide_index}))
        path = OUT / f"fsfm_{spec.name}.onnx"
        export(clf, path)
        entry = {"file": path.name, "labels": list(spec.labels), "bonafide_index": spec.bonafide_index,
                 "source_checkpoint": mcfg.file, "source_sha256": mcfg.sha256,
                 "bytes": path.stat().st_size, "sha256": sha256_of(path), "parity_fp32": check(path, batch, ref, spec)}
        if args.int8:
            from onnxruntime.quantization import QuantType, quantize_dynamic
            q = OUT / f"fsfm_{spec.name}.int8.onnx"
            quantize_dynamic(str(path), str(q), weight_type=QuantType.QInt8)
            entry["int8"] = {"file": q.name, "bytes": q.stat().st_size, "sha256": sha256_of(q),
                             "parity": check(q, batch, ref, spec)}
        manifest["models"][spec.name] = entry
        print(spec.name, json.dumps(entry, indent=1), flush=True)
        del clf

    write_frame_fixtures(cfg, fixtures, manifest)
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print("wrote", OUT)
    return 0


def write_frame_fixtures(cfg, fixtures: Path, manifest: dict) -> None:
    """Whole frames with the Python engine's per-frame result, for end-to-end parity of the Java pipeline
    (face box and pose from MediaPipe are recorded, since MediaPipe is not available in JVM tests)."""
    import synth
    from PIL import Image
    from passive_liveness.engine import PassiveLivenessEngine
    engine = PassiveLivenessEngine(cfg)
    try:
        with FaceDetector(cfg.face.landmarker_path, max_faces=cfg.face.max_faces) as det:
            frames = []
            for name in ("portrait.jpg", "business-person.png"):
                rgb = load_image(str(ROOT / "tests" / "data" / name))
                head = synth.head_shot(rgb, det.detect(rgb)[0].box)
                for tag, img in (("orig", rgb), ("print", synth.printed_photo(head)),
                                 ("screen", synth.screen_replay(head))):
                    frames.append((f"frame-{Path(name).stem}-{tag}", np.ascontiguousarray(img)))
            for name, img in frames:
                faces = det.detect(img)
                fa = engine.analyze_faces(img, faces, 0, explain=False)
                Image.fromarray(img).save(fixtures / f"{name}.png")
                Image.fromarray(img).save(fixtures / f"{name}.ppm")
                (fixtures / f"{name}.json").write_text(json.dumps({
                    "faces": [{"box": list(f.box), "yaw_deg": f.yaw_deg, "pitch_deg": f.pitch_deg} for f in faces],
                    "decision": fa.decision.value, "bonafide_probability": fa.bonafide_probability,
                    "categories": fa.categories, "crop_box": list(fa.face.crop_box) if fa.face.crop_box else None,
                    "crop_clip": fa.face.crop_clip,
                    "quality": {"reasons": [r.value for r in fa.quality.reasons], "sharpness": fa.quality.sharpness,
                                "brightness": fa.quality.brightness, "contrast": fa.quality.contrast}}, indent=1))
                manifest.setdefault("frame_fixtures", []).append(name)
                print(name, fa.decision.value, fa.bonafide_probability, [r.value for r in fa.quality.reasons])
    finally:
        engine.close()


if __name__ == "__main__":
    sys.exit(main())
