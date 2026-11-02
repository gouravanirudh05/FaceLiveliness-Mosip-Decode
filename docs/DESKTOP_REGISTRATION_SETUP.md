# Desktop Registration Setup
## Prerequisites

- Python 3.12
- [uv](https://docs.astral.sh/uv/) OR [conda](https://anaconda.org/anaconda/conda) for Python environment management
- JDK 11 (`/usr/lib/jvm/java-11-openjdk-amd64` on Debian/Ubuntu)
- Maven
- Git, with submodules initialised
- A webcam

## 1. Clone the repository

```bash
git clone --recurse-submodules <repo-url> FaceLiveliness-Mosip-Decode
cd FaceLiveliness-Mosip-Decode
```

If you cloned without `--recurse-submodules`:

```bash
git submodule update --init --recursive
```

## 2. Set up the environment

```bash
# Download Passive Liveness Modules
# To be run from <REPO_ROOT>/face-liveness-passive
python3 scripts/download_models.py  #Download the passive liveness detection modules from huggingface.

# Set up MockMDS
# To be run from <REPO_ROOT>/mosip/mosip-mock-services/MockMDS/
mvn clean install -Dgpg.skip=true -DskipTests=true -Dmaven.javadoc.skip=true

# To create and start active, passive, and mockmds services.
# To be run from <REPO_ROOT>/mosip/
./scripts/start-services.sh      #If using conda.
./scripts/start-services-uv.sh   #If using uv.
# logs will be located in <REPO_ROOT>/.run/
```
The scripts will create the environments if they dont exist already, and start the services.

## 3. Build the MOSIP Registration Client

Set the Java environment:

```bash
export JAVA_HOME=/usr/lib/jvm/java-11-openjdk-amd64
export PATH=$JAVA_HOME/bin:$PATH
```
Build LivenessGRPC Client for Mosip
```bash
# To be run from <REPO_ROOT>/face-liveness-desktop
mvn clean install -DskipTests=true
```

Apply the Desktop Registration Patches for enabling Face Liveness Engine in Desktop Registration
```bash
# To be run from <REPO_ROOT>/mosip/registration-client
git apply --ignore-whitespace ../patches/registration-client-face-liveness.patch
```

[OPTIONAL] If you do not have access to a MOSIP Backend, you can use the STUB backend patch, to bypass the MOSIP backend, to try out our implementation. 
```bash
# To be run from <REPO_ROOT>/mosip/registration-client
git apply --ignore-whitespace ../patches/mock-backend.patch
```

Build the registration client:
```bash
# To be run from <REPO_ROOT>/mosip/registration_client/registration/
mvn clean install -Dgpg.skip=true -DskipTests=true -Dmaven.javadoc.skip=true
cd ../../..
```

## 4. Set up the JavaFX SDK (Linux only)

Download and extract JavaFX into `extras/`:

```bash
# To be run from <REPO_ROOT>/extras
unzip openjfx-11.0.2_linux-x64_bin-sdk.zip
```

## 5. Start the webcam feeder for MockMDS

Run the feeder in the background and write its log to `.run/webcam.log`:

```bash
# To be run from <REPO_ROOT>/mosip/
nohup scripts/run-webcam-device.sh > .run/webcam.log 2>&1 &
```

To run manually:
```bash
# To be run from <REPO_ROOT>/mosip/
python3 mockmds_webcam_feeder.py
# python3 webcam_server.py # use this incase, you are using WSL and dont have access to real camera drivers.
```

## 6. Prepare the registration client JAR

From the `mosip/registration-client/registration/registration-client` directory:

```bash
# To be run from <REPO_ROOT>/mosip/
cd registration-client/registration/registration-client
cp target/registration-client-1.2.0.2.jar target/lib/
```

## 7. Download the mock SDK
Download the mockSDK from Maven Repository.
```bash
# To be run from <REPO_ROOT>/mosip/registration-client/registration/registration-client
cd target/lib
wget -nc https://repo1.maven.org/maven2/io/mosip/mock/sdk/mock-sdk/1.2.0.2/mock-sdk-1.2.0.2.jar
```

## 8. Launch the Registration Client

Still inside `target/lib`, run:

```bash
# To be run from <REPO_ROOT>/mosip/registration-client/registration/registration-client/target/lib
java \
  --module-path ../../../../../../extras/javafx-sdk-11.0.2/lib/ \
  --add-modules=javafx.controls,javafx.fxml,javafx.base,javafx.web,javafx.swing,javafx.graphics \
  --add-exports javafx.graphics/com.sun.javafx.application=ALL-UNNAMED \
  -Dmosip.mock.backend=true \
  -Dprism.verbose=true \
  -cp "*" \
  io.mosip.registration.controller.Initialization
```
If using the official backend, then login with your credentials, else if you are using the STUB backend then Log in with username `dev` and password `dev`. 
You may have to restart the application 2-3 times, to reach the dashboard. 

## Stopping the services

Stop the MOSIP support services and the webcam feeder:

```bash
cd mosip
scripts/stop-services.sh
pkill -f mockmds_webcam_feeder
```

## Extras
### Tryout Active/Passive Detection Engine without MOSIP Integration
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