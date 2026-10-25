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

To get the MOSIP working
```
# root of repo.
mvn install:install-file -Dfile=extras/mock-sdk
-1.3.1.jar -DgroupId=io.mosip.mock.sdk -DartifactId=mock-sdk -Dversion=1.3.1 -Dpackaging=jar 
cd mosip/registration-client/registration
mvn clean install -Dgpg.skip=true -DskipTests=true -Dmaven.javadoc.skip=true

# !!! IF USING LINUX (Download and unzip in extras....)
# wget https://download2.gluonhq.com/openjfx/11.0.2/openjfx-11.0.2_linux-x64_bin-sdk.zip
# unzip openjfx-11.0.2_linux-x64_bin-sdk.zip
cp mosip/registration-client/registration/target/registration-client-1.0.0-SNAPSHOT.jar mosip/registration-client/registration/target/lib/

cd mosip/registration-client/registration/target/lib
# Now run this command to start the registration client
java   --module-path ~/mosip/FaceLiveliness-Mosip-Decode/extras/javafx-sdk-11.0.2/lib/   --add-modules=javafx.controls,javafx.fxml,javafx.base,javafx.web,javafx.swing,javafx.graphics   --add-exports javafx.graphics/com.sun.javafx.application=ALL-UNNAMED   -Dmosip.mock.backend=true -Dprism.verbose=true  -cp "*"   io.mosip.registration.controller.Initialization
```
