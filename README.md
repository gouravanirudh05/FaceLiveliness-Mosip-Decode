# FaceLiveliness-Mosip-Decode

| Directory | What it is |
|---|---|
| [face-liveness-active/](face-liveness-active/README.md) | Active liveness: challenge-response with MediaPipe, gRPC service on `:50051` |
| [face-liveness-passive/](face-liveness-passive/README.md) | Passive liveness (PAD) with FSFM models, and hybrid passive + active; gRPC service on `:50052` |
| [face-liveness-desktop/](face-liveness-desktop/) | Java modules; `liveness-grpc-client` is the Java client used by the Registration Client |
| [mosip/](mosip/README.md) | MOSIP integration: Desktop and Android Registration Clients + MockMDS (git submodules), patches, scripts, tools |
| [command.md](command.md) | Commands to set up, run and test the MOSIP integration |
| [docs/TECHNICAL_DESIGN.md](docs/TECHNICAL_DESIGN.md) | Technical design (architecture, flows, configuration, interfaces, security, ISO/IEC 30107) |
| [docs/MOSIP_Liveness_Tracker.xlsx](docs/MOSIP_Liveness_Tracker.xlsx) | Team tracker: open tasks to claim, and the status of every line of the problem statement |
| [webcam_client.py](webcam_client.py) | One webcam demo client for all three modes |

## Webcam demo

Use the `face-liveness-passive` conda environment, which has both modules installed. Start the
service for the mode you want, then run the client from this directory.

```bash
source ~/miniconda3/etc/profile.d/conda.sh && conda activate face-liveness-passive

python -m active_liveness.server     # for --mode active   (127.0.0.1:50051)
python -m passive_liveness.server    # for --mode passive and --mode hybrid   (127.0.0.1:50052)

python webcam_client.py --mode active                  # challenge-response only
python webcam_client.py --mode passive                 # passive PAD only
python webcam_client.py --mode hybrid                  # passive first, then challenges if needed (default)
```

| Option | |
|---|---|
| `--mode active\|passive\|hybrid` | which flow to run (default `hybrid`) |
| `--camera N` / `--source FILE` | camera index, or a video / image file instead of a camera |
| `--workflow resident\|operator\|supervisor` | active and hybrid modes |
| `--passive 0.3` | active mode only: passive score to send |
| `--server HOST:PORT` | default `:50051` for active, `:50052` otherwise |
| `--headless`, `--max-seconds N` | no window (events are printed), stop after N seconds |
| `--no-mirror-preview` | show the raw frames instead of a selfie-style mirrored preview |

Keys: **R** retry (when offered), **N** new session (after a decision), **Q / Esc** quit.
Frames are always sent un-mirrored, so "left" means the user's own left.
