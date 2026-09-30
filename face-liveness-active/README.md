# face-liveness-active

Active face liveness (challenge-response) for the MOSIP Registration Client, built on
MediaPipe **FaceLandmarker** (478 landmarks, 52 blendshapes, head-pose matrix). It runs
as a local gRPC service; one bidirectional stream is one liveness session. Everything
runs offline, and the model is committed in `models/`.

## Setup

```bash
export PATH="$HOME/miniconda3/condabin:$PATH"
conda env create -f environment.yml      # creates env "face-liveness-active" and installs this package (-e .)
source ~/miniconda3/etc/profile.d/conda.sh
conda activate face-liveness-active
python -m pytest                          # 164 tests, ~30 s
python -m active_liveness.server          # listens on 127.0.0.1:50051 (config/default.yaml)
```

### Webcam demo (manual testing)

With the server running, in a second terminal:

```bash
python scripts/webcam_client.py                      # camera 0, resident workflow, no passive score
python scripts/webcam_client.py --camera 1 --workflow supervisor --passive 0.3
python scripts/webcam_client.py --headless --source some_video.mp4   # no window, prints events
```

The window shows the prompt, a countdown, live feedback, a progress bar and a face guide.
Keys: **R** retry (when offered), **N** new session (after a decision), **Q/Esc** quit.
Frames go to the server un-mirrored. The preview is mirrored like a selfie view
(`--no-mirror-preview` turns that off). "Left" always means *your* left.

To regenerate the gRPC stubs after editing `proto/active_liveness.proto`, run `./scripts/generate_proto.sh`.
The Java Registration Client generates its client from the same `.proto`
(`java_package = io.mosip.extensions.liveness.active.grpc`).

## How a session runs

1. The client sends `StartSession{workflow, passive_score?}`, then streams `Frame`s (JPEG/PNG/raw RGB/BGR with increasing `timestamp_ms`).
2. The server replies with a `ChallengePrompt` (for example "Please turn your head to the left") and live `Feedback`
   ("Hold still", "Please continue", "Action detected", "Keep your face within the capture area", …).
3. Each step must be completed before its timeout. If a step fails, the server sends `RetryAvailable` (with the user
   guidance from the spec) and the client sends `Retry`. Once attempts run out, the server sends
   `Decision{FAILED, MAX_RETRIES_EXCEEDED}`.
4. Every session ends with exactly one `Decision`: PASSED / FAILED / CANCELLED / DISABLED.

Every challenge must begin from a steady, neutral face: no smile for a smile challenge, still head for a
head turn. That neutral frame sets the baseline, and the action is measured relative to it. A static
photo therefore cannot pass, and a person whose resting pose is already off-centre still has to move
the full angle. A clearly opposite movement (turning right when asked to turn left) fails the step
immediately.

## Challenges and escalation

| Tier   | Actions |
|--------|---------|
| EASY   | blink, smile, open mouth |
| MEDIUM | turn head left/right, tilt head up/down |
| HARD   | nod, eye gaze left/right/up/down (head still), or two EASY/MEDIUM actions in order |

Directions are from the **subject's** point of view, assuming an un-mirrored camera. Set
`service.input_mirrored: true` if the device mirrors its frames.

Challenges are chosen with `secrets.SystemRandom`, and no action repeats within an attempt. Difficulty grows in four ways:

- **Tiers**: the base sequence is EASY → MEDIUM → HARD (`min_challenges` > 3 adds further HARD steps).
- **Stricter per step**: step N uses `steps[N]`: 8 s / 15° / 10° → 6 s / 20° / 12° → 5 s / 25° / 15°.
- **Weakness**: `passive_score < 0.5` adds a HARD step. So does a step passed with margin < 0.15. At most `max_extra_challenges` (2) steps are added.
- **Retry**: attempt k starts k tiers higher (EASY → MEDIUM → HARD).

All of this lives in `config/default.yaml`, with optional per-workflow overrides (resident / operator / supervisor).

## Plugging in passive liveness

`active_liveness.passive` defines the `PassiveLivenessEngine` protocol and `PassiveResult(score, attack_detected)`.
The hybrid orchestrator you add later should:

- reject on `attack_detected`;
- accept when `score >= threshold`;
- otherwise start an active session with `passive_score=result.score`, either in process with
  `ActiveLivenessSession(..., passive_score=...)` or over gRPC with `StartSession.passive_score`.

The active module needs nothing else from passive.

## Layout

```
src/active_liveness/
  analyzer.py    MediaPipe -> FaceObservation (head pose, gaze, blendshapes)
  detectors.py   per-action detectors (baseline, hold, wrong-direction, compound)
  challenges.py  catalogue, random selection, escalation plan
  session.py     state machine: steps, timeouts, retries, audit log
  server.py      gRPC service
  passive.py     passive-liveness plug-in interface
tests/           01 config → 02 detectors → 03 planner → 04 session (synthetic users)
                 → 05 real MediaPipe on a public image → 06 gRPC end-to-end
```

The test image `tests/data/business-person.png` is MediaPipe's own sample asset
(`storage.googleapis.com/mediapipe-assets`). The model `models/face_landmarker.task` is the float16 v1
FaceLandmarker (sha256 `64184e22…c9ff`).

## Known limitations

- Head-pose challenges alone cannot stop a printed photo that is physically *tilted*. Moving a photo
  around in front of the camera shifted the estimated yaw by up to ~11° and pitch by ~7° in testing,
  below the 15°/10° thresholds but without much headroom. Presentation-attack detection (PAD) is the
  job of the passive engine.
- Thresholds were tuned against synthetic signals and one still image, not against recordings of real
  people. Calibrate them with real users and devices.
