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
| [browser.py](browser.py) | Browser based webcam demo client for all three modes |

How to get started with browser.py:
```bash
# clone the repo
uv venv --python 3.12 #create a virtual environment
source ~/.venv/bin/activate
cd face-liveness-passive
uv sync --active #will build both active and passive modules

# Now on three terminals (use source/.venv/bin/activate to activate the virtual environment in each)
uv run python -m active_liveness.server
uv run python -m passive_liveness.server

# To run the browser based client.
uv pip install fastapi uvicorn websockets
uv run --active python browser.py
```