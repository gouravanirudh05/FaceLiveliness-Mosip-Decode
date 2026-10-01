"""ISO/IEC 30107-3 style evaluation of the passive engine on a labelled dataset.

Dataset layout (one folder per class; images and/or videos, any depth):

    dataset/
      bonafide/            (aliases: live, real, genuine, bona_fide)
      print/               every other folder name is a PAI species
      screen_replay/
      mask_3d/

or a CSV manifest with columns ``path,label[,attack_potential]`` (paths relative to it).

    passive-liveness-eval dataset/ --out reports/run1
    passive-liveness-eval --manifest data.csv --out reports/run1
    passive-liveness-eval --scores reports/run1/scores.csv --out reports/run1b   # metrics only

Outputs: scores.csv, metrics.json, det.csv, report.md (+ det.png if matplotlib is installed).
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Iterable

from . import iso30107
from .iso30107 import Presentation, normalise_label

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"}
VIDEO_EXT = {".mp4", ".avi", ".mov", ".mkv", ".webm", ".m4v"}
SCORE_FIELDS = ["source", "label", "attack_potential", "score", "decision", "attack_category",
                "suspected_pai_species", "non_response_reasons", "seconds"]


def discover(root: Path) -> list[tuple[Path, str, str | None]]:
    items = []
    for cls_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        label = normalise_label(cls_dir.name)
        for f in sorted(cls_dir.rglob("*")):
            if f.suffix.lower() in IMAGE_EXT | VIDEO_EXT:
                items.append((f, label, None))
    return items


def read_manifest(path: Path) -> list[tuple[Path, str, str | None]]:
    with path.open(newline="") as fh:
        return [((path.parent / r["path"]).resolve(), normalise_label(r["label"]), r.get("attack_potential") or None)
                for r in csv.DictReader(fh)]


def score_dataset(engine, items, *, video_frames: int | None = None, progress=print) -> list[dict]:
    from .io import InputError
    from .types import Decision

    rows = []
    for i, (path, label, ap) in enumerate(items, 1):
        t0 = time.perf_counter()
        try:
            if path.suffix.lower() in VIDEO_EXT:
                r = engine.analyze_video(path, max_frames=video_frames, include_frames=False, stop_when_complete=True)
                reasons = ";".join(sorted(r.non_response_reasons))
            else:
                r = engine.analyze_image(path)
                reasons = ";".join(x.value for x in r.quality.reasons)
            score = r.bonafide_probability if r.decision is not Decision.NON_RESPONSE else None
            row = {"decision": r.decision.value, "attack_category": r.attack_category.value,
                   "suspected_pai_species": r.suspected_pai_species.value, "non_response_reasons": reasons}
        except InputError as e:
            score, row = None, {"decision": "non_response", "attack_category": "", "suspected_pai_species": "",
                                "non_response_reasons": f"decode_error: {e}"}
        rows.append({"source": str(path), "label": label, "attack_potential": ap or "",
                     "score": "" if score is None else f"{score:.6f}",
                     "seconds": f"{time.perf_counter() - t0:.3f}", **row})
        if progress:
            progress(f"[{i}/{len(items)}] {label:15s} {row['decision']:12s} {rows[-1]['score'] or '-':>8s}  {path.name}")
    return rows


def write_csv(path: Path, rows: Iterable[dict], fields: list[str]) -> None:
    with path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def species_confusion(rows: list[dict]) -> dict:
    """Heuristic PAI-species suggestion vs ground truth, for attack presentations."""
    out: dict[str, Counter] = {}
    for r in rows:
        if r["label"] != iso30107.BONAFIDE:
            out.setdefault(r["label"], Counter())[r.get("suspected_pai_species") or "-"] += 1
    return {k: dict(v) for k, v in sorted(out.items())}


def _pct(x) -> str:
    return "n/a" if x is None else f"{100 * x:.2f} %"


def _rate(d: dict) -> str:
    if not d or d.get("value") is None:
        return "n/a"
    ci = d.get("ci95")
    s = f"{_pct(d['value'])} ({d['errors']}/{d['total']}"
    if ci:
        s += f", 95 % CI {100 * ci[0]:.2f}-{100 * ci[1]:.2f} %"
    if "rule_of_3_upper" in d:
        s += f", rule-of-3 <= {_pct(d['rule_of_3_upper'])}"
    return s + ")"


def render_report(metrics: dict, meta: dict, confusion: dict | None) -> str:
    L = ["# Passive liveness - ISO/IEC 30107-3 evaluation report", ""]
    L += ["## Target of evaluation", ""]
    for k, v in meta.items():
        L.append(f"- **{k}**: {v}")
    c = metrics["counts"]
    L += ["", "## Test set", "", f"- Bona fide presentations: {c['bonafide']}",
          f"- Attack presentations: {c['attack']}"]
    for s, n in c["per_species"].items():
        L.append(f"  - PAI species `{s}`: {n}")
    nr = metrics["non_response"]
    L += ["", "## Non-response (failure to process)", "",
          f"- APNRR: {_rate(nr['apnrr'])}", f"- BPNRR: {_rate(nr['bpnrr'])}"]
    for s, d in nr["apnrr_per_species"].items():
        L.append(f"  - APNRR `{s}`: {_rate(d)}")
    for name, op in metrics["operating_points"].items():
        L += ["", f"## Operating point `{name}` (attack if score < {op['threshold']:.4f})", "",
              "| Metric | Value |", "|---|---|"]
        for s, d in op["apcer_per_species"].items():
            L.append(f"| APCER `{s}` | {_rate(d)} |")
        L.append(f"| **APCER (max over species: `{op['apcer_max'].get('species')}`)** | {_rate(op['apcer_max'])} |")
        L.append(f"| APCER pooled (informative) | {_rate(op['apcer_pooled'])} |")
        L.append(f"| **BPCER** | {_rate(op['bpcer'])} |")
        for lvl, d in op.get("apcer_per_attack_potential", {}).items():
            L.append(f"| APCER attack potential `{lvl}` (`{d.get('species')}`) | {_rate(d)} |")
        if "acer_informative" in op:
            L.append(f"| ACER (academic summary, not ISO/IEC 30107-3) | {_pct(op['acer_informative'])} |")
    L += ["", "## Threshold-independent summaries", "", "| Metric | Value | Threshold |", "|---|---|---|"]
    for k, v in metrics["bpcer_at_apcer"].items():
        L.append(f"| {k} | {_pct(v['bpcer']) if v else 'n/a'} | {v['threshold']:.4f} |" if v else f"| {k} | n/a | |")
    e = metrics["eer"]
    L.append(f"| EER (pooled attacks) | {_pct(e['eer']) if e else 'n/a'} | {e['threshold']:.4f} |" if e
             else "| EER | n/a | |")
    L.append(f"| AUC | {metrics['auc']:.4f} | |" if metrics["auc"] is not None else "| AUC | n/a | |")
    if confusion:
        L += ["", "## Heuristic PAI-species suggestion vs ground truth (attacks only)", "",
              "Counts of `suspected_pai_species` per true species. These suggestions come from hand-crafted",
              "cues, not from the models.", ""]
        for s, cnt in confusion.items():
            L.append(f"- `{s}`: " + ", ".join(f"{k}={v}" for k, v in sorted(cnt.items())))
    if metrics["notes"]:
        L += ["", "## Notes", ""] + [f"- {n}" for n in metrics["notes"]]
    L += ["", "## Not covered by this report", "",
          "- IAPMR / impostor attack presentation match rate: requires a biometric comparator (out of scope for a PAD-only subsystem).",
          "- Attack potential rating of each PAI species (see ISO/IEC 30107-3 and ISO/IEC 19989-3): supply `attack_potential` in the manifest.",
          "- Test-crew demographics, capture devices and environment must be documented by the evaluator.", ""]
    return "\n".join(L)


def plot_det(rows: list[dict], path: Path) -> bool:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return False
    pts = [(r["apcer_max"], r["bpcer"]) for r in rows if r["apcer_max"] is not None and r["bpcer"] is not None]
    if not pts:
        return False
    fig, ax = plt.subplots(figsize=(5, 5))
    ax.plot([p[0] for p in pts], [p[1] for p in pts], drawstyle="steps-post")
    ax.set_xscale("symlog", linthresh=1e-3)
    ax.set_yscale("symlog", linthresh=1e-3)
    ax.set_xlabel("APCER (max over PAI species)")
    ax.set_ylabel("BPCER")
    ax.set_title("DET")
    ax.grid(True, which="both", alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return True


def run(rows: list[dict], out: Path, thresholds: dict[str, float], meta: dict) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    ps = iso30107.presentations_from_rows(rows)
    metrics = iso30107.evaluate(ps, thresholds)
    det = iso30107.sweep(ps)
    write_csv(out / "scores.csv", rows, SCORE_FIELDS)
    write_csv(out / "det.csv", det, ["threshold", "apcer_max", "apcer_pooled", "bpcer"])
    confusion = species_confusion(rows) if any(r.get("suspected_pai_species") for r in rows) else None
    (out / "metrics.json").write_text(json.dumps({"meta": meta, "metrics": metrics,
                                                  "species_confusion": confusion}, indent=2))
    (out / "report.md").write_text(render_report(metrics, meta, confusion))
    plot_det(det, out / "det.png")
    return metrics


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("dataset", nargs="?", type=Path, help="folder with one sub-folder per class")
    src.add_argument("--manifest", type=Path, help="CSV with path,label[,attack_potential]")
    src.add_argument("--scores", type=Path, help="re-compute metrics from an existing scores.csv")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--config", type=Path, help="passive config YAML (default: config/default.yaml)")
    ap.add_argument("--video-frames", type=int, default=None, help="max frames read per video")
    ap.add_argument("--threshold", type=float, action="append", default=[],
                    help="extra operating threshold(s) to report")
    args = ap.parse_args(argv)

    from .config import DEFAULT_CONFIG_PATH, load_config
    cfg = load_config(args.config or DEFAULT_CONFIG_PATH)
    thresholds = {"reject_threshold": cfg.decision.reject_threshold,
                  "accept_threshold": cfg.decision.accept_threshold}
    for t in args.threshold:
        thresholds[f"custom_{t:g}"] = t
    meta = {"date": time.strftime("%Y-%m-%d %H:%M:%S"),
            "decision rule": "attack if fused bona fide probability < threshold",
            "accept / reject thresholds": f"{cfg.decision.accept_threshold} / {cfg.decision.reject_threshold}",
            "quality gate enforced": cfg.quality.enforce}

    if args.scores:
        with args.scores.open(newline="") as fh:
            rows = list(csv.DictReader(fh))
        meta["scores"] = str(args.scores)
    else:
        from .engine import PassiveLivenessEngine
        items = read_manifest(args.manifest) if args.manifest else discover(args.dataset)
        if not items:
            print("no images/videos found", file=sys.stderr)
            return 2
        engine = PassiveLivenessEngine(cfg)
        try:
            meta["models"] = ", ".join(f"{k} ({v['file']}, weight {v['weight']})" for k, v in engine.info().items())
            meta["dataset"] = str(args.manifest or args.dataset)
            rows = score_dataset(engine, items, video_frames=args.video_frames)
        finally:
            engine.close()      # MediaPipe can deadlock if its landmarker is left to the garbage collector
    run(rows, args.out, thresholds, meta)
    print(f"report written to {args.out / 'report.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
