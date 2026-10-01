"""The evaluation runner end to end: dataset folder -> scores -> ISO/IEC 30107-3 report.

The models are replaced by a transparent rule (periodic spectrum or washed-out colour
=> attack) so the expected metrics are known exactly; the face detection, cues, decision
logic, file handling and report generation are the real ones.
"""

import csv
import json

import cv2
import numpy as np
import pytest

import synth
from conftest import FakeClassifier
from passive_liveness import evaluate
from passive_liveness.cues import moire_peak_ratio
from passive_liveness.engine import PassiveLivenessEngine
from passive_liveness.models import FAS, UNIFIED


def rule(crop):
    sat = cv2.cvtColor(crop, cv2.COLOR_RGB2HSV)[..., 1].mean() / 255
    return 0.9 if moire_peak_ratio(crop) < 1.6 and sat > 0.15 else 0.1


@pytest.fixture
def rule_engine(monkeypatch, config):
    def build(cfg=None):
        return PassiveLivenessEngine(cfg or config, classifiers=[FakeClassifier(UNIFIED, rule),
                                                                 FakeClassifier(FAS, rule)])
    monkeypatch.setattr("passive_liveness.engine.PassiveLivenessEngine", build)
    return build


def save(path, rgb):
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))


@pytest.fixture(scope="module")
def dataset(tmp_path_factory, portrait, business):
    root = tmp_path_factory.mktemp("ds")
    from passive_liveness.face import FaceDetector
    from conftest import ROOT
    with FaceDetector(ROOT / "models" / "face_landmarker.task") as d:
        shots = [synth.head_shot(img, d.detect(img)[0].box) for img in (portrait, business)]
    shots += [cv2.flip(s, 1) for s in shots]
    for i, s in enumerate(shots):
        save(root / "live" / f"live_{i}.png", s)                     # folder alias for bona fide
        save(root / "print" / f"print_{i}.jpg", synth.printed_photo(s, seed=i))
        save(root / "screen_replay" / f"screen_{i}.png", synth.screen_replay(s, seed=i))
    save(root / "live" / "empty_room.png", np.full((480, 640, 3), 90, np.uint8))     # no face
    (root / "print" / "corrupt.jpg").write_bytes(b"not a jpeg")
    h, w = shots[0].shape[:2]
    vw = cv2.VideoWriter(str(root / "live" / "clip.mp4"), cv2.VideoWriter_fourcc(*"mp4v"), 25, (w, h))
    for _ in range(40):
        vw.write(cv2.cvtColor(shots[0], cv2.COLOR_RGB2BGR))
    vw.release()
    return root


def test_discover_maps_folders_to_labels(dataset):
    items = evaluate.discover(dataset)
    labels = sorted({label for _, label, _ in items})
    assert labels == ["bonafide", "print", "screen_replay"]
    assert len(items) == 6 + 5 + 4


def test_full_run_writes_a_consistent_report(dataset, rule_engine, tmp_path):
    out = tmp_path / "report"
    assert evaluate.main([str(dataset), "--out", str(out)]) == 0
    for f in ["scores.csv", "metrics.json", "det.csv", "report.md"]:
        assert (out / f).is_file()

    rows = list(csv.DictReader((out / "scores.csv").open()))
    assert len(rows) == 15
    by_name = {r["source"].split("/")[-1]: r for r in rows}
    assert by_name["empty_room.png"]["score"] == "" and "no_face" in by_name["empty_room.png"]["non_response_reasons"]
    assert by_name["corrupt.jpg"]["decision"] == "non_response"
    assert by_name["clip.mp4"]["decision"] == "bonafide"

    m = json.loads((out / "metrics.json").read_text())["metrics"]
    assert m["counts"] == {"bonafide": 6, "attack": 9, "per_species": {"print": 5, "screen_replay": 4}}
    assert m["non_response"]["bpnrr"]["value"] == pytest.approx(1 / 6)
    assert m["non_response"]["apnrr_per_species"]["print"]["value"] == pytest.approx(1 / 5)

    # every reported rate must agree with the per-presentation scores
    t = 0.40
    def scored(label):
        return [float(r["score"]) for r in rows if r["label"] == label and r["score"] != ""]
    op = m["operating_points"]["reject_threshold"]
    bona = scored("bonafide")
    assert op["bpcer"]["value"] == pytest.approx(sum(x < t for x in bona) / len(bona))
    for species in ("print", "screen_replay"):
        xs = scored(species)
        assert op["apcer_per_species"][species]["value"] == pytest.approx(sum(x >= t for x in xs) / len(xs))
    assert op["apcer_max"]["value"] == max(op["apcer_per_species"][s]["value"] for s in ("print", "screen_replay"))
    assert sum(x >= t for x in bona) == 5                    # the rule accepts every bona fide sample

    confusion = json.loads((out / "metrics.json").read_text())["species_confusion"]
    for species in ("print", "screen_replay"):
        suggested = [r["suspected_pai_species"] for r in rows if r["label"] == species]
        assert sum(confusion[species].values()) == len(suggested)
    caught = [r for r in rows if r["label"] == "screen_replay" and r["decision"] == "attack"]
    assert caught and all(r["suspected_pai_species"] == "screen_replay" for r in caught)

    report = (out / "report.md").read_text()
    for text in ["APCER (max over species", "BPCER", "APNRR", "BPCER100", "EER", "not ISO/IEC 30107-3",
                 "IAPMR", "PAI species `print`: 5"]:
        assert text in report


def test_metrics_can_be_recomputed_from_scores(dataset, rule_engine, tmp_path):
    first, second = tmp_path / "a", tmp_path / "b"
    evaluate.main([str(dataset), "--out", str(first)])
    evaluate.main(["--scores", str(first / "scores.csv"), "--out", str(second), "--threshold", "0.5"])
    a = json.loads((first / "metrics.json").read_text())["metrics"]
    b = json.loads((second / "metrics.json").read_text())["metrics"]
    assert a["operating_points"]["reject_threshold"] == b["operating_points"]["reject_threshold"]
    assert "custom_0.5" in b["operating_points"]


def test_manifest_with_attack_potential(dataset, rule_engine, tmp_path):
    manifest = tmp_path / "m.csv"
    with manifest.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["path", "label", "attack_potential"])
        w.writerow([str(dataset / "live" / "live_0.png"), "bonafide", ""])
        w.writerow([str(dataset / "print" / "print_0.jpg"), "print", "basic"])
        w.writerow([str(dataset / "screen_replay" / "screen_0.png"), "screen_replay", "enhanced"])
    out = tmp_path / "r"
    evaluate.main(["--manifest", str(manifest), "--out", str(out)])
    m = json.loads((out / "metrics.json").read_text())["metrics"]
    assert set(m["operating_points"]["reject_threshold"]["apcer_per_attack_potential"]) == {"basic", "enhanced"}


def test_empty_dataset(tmp_path, rule_engine):
    (tmp_path / "bonafide").mkdir()
    assert evaluate.main([str(tmp_path), "--out", str(tmp_path / "o")]) == 2
