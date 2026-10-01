# face-liveness-passive

Passive face liveness (presentation attack detection, PAD) for MOSIP. It uses the pre-trained
**FSFM / FS-VFM** ViT checkpoints from
[wolo-wolo/FSFM-CVPR25 (FSVFM-extension)](https://github.com/wolo-wolo/FSFM-CVPR25/tree/FSVFM-extension).
It runs fully offline on CPU, and you can use it in three ways:

1. **as a Python submodule**: `PassiveLivenessEngine` for images, videos and live frame streams;
2. **as a local gRPC server**: image, video upload, live stream, and hybrid sessions;
3. **in hybrid mode with `face-liveness-active`**: passive PAD first, active challenges only when passive is inconclusive.

> **Licence.** The FSFM model weights are **CC BY-NC 4.0 (non-commercial use only)**.
> Commercial deployment needs permission from the authors, or a different model. The engine
> accepts any classifier that implements `models.Classifier`, so a model can be swapped in.

## Setup

```bash
export PATH="$HOME/miniconda3/condabin:$PATH"
conda env create -f environment.yml          # env "face-liveness-passive": CPU PyTorch, MediaPipe, gRPC,
                                             # this package and ../face-liveness-active (for hybrid)
source ~/miniconda3/etc/profile.d/conda.sh && conda activate face-liveness-passive
python scripts/download_models.py            # 2 x 1 GB from Hugging Face, pinned revision, sha256-checked
python -m pytest                             # 167 tests, ~60 s (model tests are skipped without the weights)
```

The FaceLandmarker model (`models/face_landmarker.task`, Apache-2.0) is committed. The FSFM
checkpoints are gitignored.

## How to test

Run everything from `face-liveness-passive/` with the environment activated:

```bash
source ~/miniconda3/etc/profile.d/conda.sh
conda activate face-liveness-passive
```

**1. Automated tests** (167 tests, about 1 minute)

```bash
python -m pytest                               # everything
python -m pytest -m "not models"               # skip the slow real-model tests
python -m pytest tests/test_07_real_models.py  # only the real FSFM checkpoints
python -m pytest tests/test_10_hybrid.py -v    # one file, listing each test
```

**2. Your own image or video** (no server needed)

```bash
passive-liveness path/to/face.jpg                       # full JSON result
passive-liveness path/to/clip.mp4 --compact             # video, one JSON line
passive-liveness path/to/face.jpg --heatmap heat.png    # also saves the Grad-CAM heat map
passive-liveness --camera 0 --seconds 3                 # webcam, aggregated result
```

In the output, look at `decision`, `bonafide_probability`, `attack_category` and
`suspected_pai_species`.

**3. Live webcam test through the server** (two terminals, both with the environment activated)

```bash
# terminal 1
python -m passive_liveness.server

# terminal 2 (the client is at the repository root and covers all modes)
python ../webcam_client.py --mode passive   # passive only
python ../webcam_client.py --mode hybrid    # passive first, then active challenges if needed
```

Keys: **R** retry, **N** new session, **Q** quit. To test an attack, hold a printed photo or a
phone showing a face up to the camera.

**4. Accuracy on your own data** (ISO/IEC 30107-3 report)

```
mydata/
  bonafide/        real people
  print/           printed photos
  screen_replay/   phone or monitor replays
```

```bash
passive-liveness-eval mydata --out reports/run1
```

The results are in `reports/run1/report.md`. The
[ISO/IEC 30107 evaluation](#isoiec-30107-evaluation) section has the details.

## What it outputs

Every analysed frame or image returns a `FrameAnalysis`, and streams and videos also return a
`StreamResult`. Both have `.to_dict()` and are also exposed over gRPC.

| Field | Meaning |
|---|---|
| `decision` | `bonafide` / `attack` / `uncertain` / `non_response` |
| `bonafide_probability` | fused liveness score in [0, 1] (the PAD score) |
| `attack_detected` | `decision == attack` |
| `categories` | fused distribution over `bonafide`, `presentation_attack`, `deepfake`, `synthetic` |
| `attack_category` | the most likely class: `none` / `presentation_attack` / `deepfake` / `synthetic` |
| `suspected_pai_species` | `print` / `screen_replay` / `unspecified` / `none`. A **heuristic** suggestion, only given when the decision isn't bona fide |
| `models[]` | per model: labels, probabilities, logits, bona fide probability, inference time |
| `cues` | raw measurements (moiré, straight edges around the face, glare, tonal range, saturation), PAI indicators and human-readable evidence |
| `face` | face count, landmark box, model crop box, crop clipping, yaw/pitch/roll, eye-blink level |
| `quality` | pass/fail with reasons, face size, sharpness, brightness, contrast |
| `timings_ms` | quality, models, cues and Grad-CAM time |
| `heatmap_png` | optional Grad-CAM overlay (`explain=True`) |
| *(stream only)* `temporal` | head motion, expression range, blink detected, `static_face` score, score std |
| *(stream only)* `frames_*`, `complete`, `non_response_reasons`, `thresholds`, `models` (with SHA-256) | |

### How a decision is made

1. **Face:** MediaPipe FaceLandmarker finds faces, and the largest one is analysed. More than
   one face is always a `non_response`. The model crop is a square of 1.17 × the landmark
   extent, which reproduces upstream's dlib box × 1.3 (calibrated against dlib, see `face.py`).
2. **Quality gate:** face size, sharpness, brightness, pose, and how much of the crop is cut off
   at the frame edge. A failed gate gives `non_response` (scores are still reported), which is
   an APNRR/BPNRR event in ISO terms.
3. **Models:** two FSFM ViT-B/16 checkpoints, loaded with **strict** key matching, using the
   preprocessing they were validated with (resize to 256, centre-crop 224, VGGFace2 mean/std):
   - *Unified-detector v1*: 4 classes (bona fide, deepfake, diffusion/AIGC, spoof);
   - *FAS on MCIO*: binary (spoof, bona fide), trained on MSU, CASIA, Idiap Replay and OULU-NPU.
4. **Fusion:**
   - `bonafide_probability` is the weighted mean of the two models' bona fide probabilities.
   - The remaining attack probability is split into presentation attack, deepfake and synthetic
     using **only the 4-class model**. The binary model says *whether* there's an attack, not
     *which* kind.
5. **Thresholds** (`decision` in the config):
   - `≥ accept_threshold` (0.80) → `bonafide`;
   - `< reject_threshold` (0.40) → `attack`;
   - in between → `uncertain`.
6. **PAI species** (heuristic): a held medium shows up as straight edges around the face. A
   screen adds moiré from the pixel grid and glare; a print adds compressed tone and washed-out
   colour. In streams, a face whose expression never changes raises the print indicator.
7. **Streams:**
   - Frames are sampled every `min_frame_interval_ms`, and `frames_required` quality-passing
     frames are aggregated (mean, median or min).
   - Running out of `max_duration_ms` without enough frames gives `non_response`
     (`insufficient_frames`).
   - Videos analyse every sampled frame.

## Use as a Python submodule

```python
from passive_liveness import PassiveLivenessEngine

engine = PassiveLivenessEngine.from_config()            # loads both models once; thread-safe, share it
r = engine.analyze_image("face.jpg")                    # path, encoded bytes, or RGB ndarray
print(r.decision.value, r.bonafide_probability, r.attack_category.value, r.suspected_pai_species.value)
r.to_dict()                                             # everything, JSON-ready

v = engine.analyze_video("clip.mp4")                    # file, URL/RTSP, camera index, or iterable of frames
v = engine.analyze_video(0, max_frames=50)              # camera 0

with engine.open_stream() as stream:                    # live frames from your own capture loop
    for rgb, ts_ms in frames:
        frame_result = stream.push(rgb, ts_ms)          # FrameAnalysis, or None if skipped by sampling
        if stream.done:
            break
    result = stream.result()                            # StreamResult
engine.close()
```

**Plugging into the active module's protocol**: `passive_liveness.adapter.ActivePassiveAdapter`
implements `active_liveness.passive.PassiveLivenessEngine` (`start` / `process_frame` →
`PassiveResult` / `close`).

**Hybrid passive + active, in-process:**

```python
from active_liveness import load_config as load_active, Workflow
from passive_liveness.hybrid import HybridLivenessSession, HybridDecision

session = HybridLivenessSession(engine, load_active(), Workflow.RESIDENT)
events = session.start()
for rgb, ts in frames:
    events = session.process_frame(rgb, ts)            # PassiveProgress, PassiveVerdict, ActiveEvent(prompt...) ...
    if session.retry_available:
        events += session.retry()
    if any(isinstance(e, HybridDecision) for e in events):
        break
```

| Passive result | Hybrid outcome |
|---|---|
| `attack` | **FAILED** (`attack_detected`); no challenges are shown |
| `bonafide` | **PASSED** (`passive_bonafide`) |
| `uncertain` | active challenges start with `passive_score`. A score below 0.5 adds a hard challenge (active module escalation) |
| `non_response` | active challenges without a score (treated as weak), or **FAILED** if `hybrid.on_passive_no_response: fail` |

While the challenges run, PAD keeps sampling a frame every `monitor_interval_ms`. Two
consecutive `attack` frames end the session as **FAILED** (`attack_detected_during_active`).
User-facing messages never say that an attack was detected.

## Use as a server

```bash
python -m passive_liveness.server            # 127.0.0.1:50052 (service.* in the config)
```

| RPC | |
|---|---|
| `AnalyzeImage(AnalyzeImageRequest) → FrameAnalysis` | encoded image or raw RGB/BGR; `explain` adds Grad-CAM |
| `AnalyzeVideo(AnalyzeVideoRequest) → StreamResult` | an uploaded video file (up to `max_message_mb`) |
| `AnalyzeStream(stream StreamRequest) → stream StreamResponse` | `StartStream`, then `Frame`s, then an optional `EndStream`; one `FrameAnalysis` per analysed frame and one final `StreamResult` |
| `HybridSession(stream HybridClientMessage) → stream HybridServerMessage` | passive progress and verdict, then the active module's own `ServerMessage`s (prompts, feedback, retries), then `HybridDecision` |
| `GetInfo → ServiceInfo` | models, SHA-256 values, licence, full configuration (JSON) |

`proto/passive_liveness.proto` imports `face-liveness-active/proto/active_liveness.proto`
and reuses its `Frame`, `Workflow`, `Retry`, `Cancel` and `ServerMessage`, so a client needs
only one frame format. Every result message also carries the complete result as `json`.
Regenerate the stubs with `./scripts/generate_proto.sh`. The Java package is
`io.mosip.extensions.liveness.passive.grpc`.

**Command line and demo client:**

```bash
passive-liveness face.jpg clip.mp4 --compact       # in-process, prints JSON
passive-liveness face.jpg --heatmap cam.png
passive-liveness --camera 0 --seconds 3
python ../webcam_client.py --mode hybrid           # needs the server; R retry, N new session, Q quit
python ../webcam_client.py --mode passive --headless --source some_video.mp4
```

## ISO/IEC 30107 evaluation

```bash
passive-liveness-eval DATASET --out reports/run1   # DATASET/bonafide|live, DATASET/<pai_species>/...
passive-liveness-eval --manifest data.csv --out reports/run1      # path,label[,attack_potential]
passive-liveness-eval --scores reports/run1/scores.csv --out reports/run1b --threshold 0.6
```

The tool reports, per ISO/IEC 30107-3:
- APCER per PAI species and the worst-case APCER (per attack-potential level when given);
- BPCER, APNRR and BPNRR;
- BPCER10/20/100, a DET curve, EER and AUC (the last two labelled informative);
- a Wilson 95 % interval on every rate, rule-of-3 bounds and sample-size warnings.

[docs/ISO30107_CONFORMANCE.md](docs/ISO30107_CONFORMANCE.md) has the requirement-by-requirement
assessment. [docs/example-evaluation/](docs/example-evaluation/) is a pipeline demonstration on
synthetic data, **not** a performance claim.

## Layout

```
src/passive_liveness/
  vit.py        ViT-S/B/L with FSFM parameter names (strict loading; no timm dependency)
  models.py     checkpoint specs and labels, preprocessing, inference, Grad-CAM, fusion
  face.py       MediaPipe FaceLandmarker, dlib-calibrated crop
  quality.py    quality gate -> non-response reasons
  cues.py       heuristic PAI cues (moire, edges, glare, tone, colour)
  temporal.py   stream cues (expression change, blink, head motion)
  engine.py     PassiveLivenessEngine / PassiveStream (images, videos, streams)
  hybrid.py     passive -> active orchestration (uses face-liveness-active)
  adapter.py    active module's PassiveLivenessEngine protocol
  iso30107.py   ISO/IEC 30107-3 metrics          evaluate.py   dataset runner and report
  server.py     gRPC service                     cli.py        command line
tests/  01 config -> 02 models -> 03 face/quality -> 04 cues -> 05 decisions -> 06 streams/videos
        -> 07 real checkpoints -> 08 ISO metrics -> 09 evaluation runner -> 10 hybrid -> 11 gRPC
```

## Known limitations

- **Not validated on real attack data.** The only data available here is two public sample
  photos (MediaPipe assets) and synthetic renderings. Before deployment, run
  `passive-liveness-eval` on presentations captured with your MOSIP devices, and set the
  thresholds from the result.
- **Synthetic attacks land in "uncertain".** Synthetic prints and screens score 0.49–0.77: never
  accepted by passive alone, but not rejected either. The hybrid flow then relies on the active
  challenges. Expect real physical attacks to behave differently, in either direction.
- **The PAI species is a heuristic.** The cue thresholds were calibrated on synthetic renderings
  only. Rooms with strong straight edges (doors, shelves) can raise the "held medium" evidence.
- **Masks are not explicitly covered.** 3D and silicone masks are only detected through the
  Unified model's generic spoof class.
- **Speed.** About 0.3 s per analysed frame for both ViT-B models on a 16-core CPU, so streams
  sample frames rather than analyse every one.
- **Temporal cue reliability.** Abrupt frame-to-frame jumps can make MediaPipe report spurious
  expression changes. That only suppresses the print hint and never causes an attack decision.
- **Licence.** The weights are CC BY-NC 4.0, as stated at the top.
