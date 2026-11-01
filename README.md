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
cd mosip/registration-client/registration
# git apply --ignore-whitespace ../patches/mock-backend.patch #apply the mock backend patch
mvn clean install -Dgpg.skip=true -DskipTests=true -Dmaven.javadoc.skip=true

# !!! IF USING LINUX (Download and unzip in extras....)
# wget https://download2.gluonhq.com/openjfx/11.0.2/openjfx-11.0.2_linux-x64_bin-sdk.zip
# unzip openjfx-11.0.2_linux-x64_bin-sdk.zip
cp mosip/registration-client/registration/target/registration-client-1.0.0-SNAPSHOT.jar mosip/registration-client/registration/target/lib/

cd mosip/registration-client/registration/target/lib
# Now run this command to start the registration client
wget https://repo1.maven.org/maven2/io/mosip/mock/sdk/mock-sdk/1.2.0.2/mock-sdk-1.2.0.2.jar #download the mock sdk
java   --module-path ~/mosip/FaceLiveliness-Mosip-Decode/extras/javafx-sdk-11.0.2/lib/   --add-modules=javafx.controls,javafx.fxml,javafx.base,javafx.web,javafx.swing,javafx.graphics   --add-exports javafx.graphics/com.sun.javafx.application=ALL-UNNAMED   -Dmosip.mock.backend=true -Dprism.verbose=true  -cp "*"   io.mosip.registration.controller.Initialization
# use credentials demo-operator, demo-operator
```


cd /home/gourav-anirudh/Desktop/Mosip/FaceLiveliness-Mosip-Decode/mosip/registration-client/registration && mvn clean install -Dgpg.skip=true -DskipTests=true -Dmaven.javadoc.skip=true && cd registration-client && cp target/registration-client-1.2.0.2.jar target/lib/ && cd target/lib && wget -nc https://repo1.maven.org/maven2/io/mosip/mock/sdk/mock-sdk/1.2.0.2/mock-sdk-1.2.0.2.jar && mkdir -p lib && cp ../../../lib/logback.xml lib/ && java --module-path ../../../../../../extras/javafx-sdk-11.0.2/lib/ --add-modules=javafx.controls,javafx.fxml,javafx.base,javafx.web,javafx.swing,javafx.graphics --add-exports javafx.graphics/com.sun.javafx.application=ALL-UNNAMED -Dmosip.mock.backend=true -Dprism.verbose=true -cp "*" io.mosip.registration.controller.Initialization


```
cd /home/gourav-anirudh/Desktop/Mosip/FaceLiveliness-Mosip-Decode/mosip && export JAVA_HOME=/usr/lib/jvm/java-11-openjdk-amd64 PATH=/usr/lib/jvm/java-11-openjdk-amd64/bin:$PATH && (cd registration-client/registration && mvn clean install -Dgpg.skip=true -DskipTests=true -Dmaven.javadoc.skip=true) && scripts/start-services.sh && (nohup scripts/run-webcam-device.sh > ../.run/webcam.log 2>&1 &) && cd registration-client/registration/registration-client && cp target/registration-client-1.2.0.2.jar target/lib/ && cd target/lib && wget -nc https://repo1.maven.org/maven2/io/mosip/mock/sdk/mock-sdk/1.2.0.2/mock-sdk-1.2.0.2.jar && mkdir -p lib && cp ../../../lib/logback.xml lib/ && java --module-path ../../../../../../extras/javafx-sdk-11.0.2/lib/ --add-modules=javafx.controls,javafx.fxml,javafx.base,javafx.web,javafx.swing,javafx.graphics --add-exports javafx.graphics/com.sun.javafx.application=ALL-UNNAMED -Dmosip.mock.backend=true -Dprism.verbose=true -cp "*" io.mosip.registration.controller.Initialization


```

```
/home/gourav-anirudh/Desktop/Mosip/FaceLiveliness-Mosip-Decode/mosip/scripts/stop-services.sh; pkill -f mockmds_webcam_feeder
```

25864920831241

cd /home/mrtechtroid/mosip/FaceLiveliness-Mosip-Decode/mosip/ && (cd registration-client/registration && mvn clean install -Dgpg.skip=true -DskipTests=true -Dmaven.javadoc.skip=true) && scripts/start-services.sh && (nohup scripts/run-webcam-device.sh > ../.run/webcam.log 2>&1 &) && cd registration-client/registration/registration-client && cp target/registration-client-1.2.0.2.jar target/lib/ && cd target/lib && wget -nc https://repo1.maven.org/maven2/io/mosip/mock/sdk/mock-sdk/1.2.0.2/mock-sdk-1.2.0.2.jar && mkdir -p lib && cp ../../../lib/logback.xml lib/ && java --module-path ../../../../../../extras/javafx-sdk-11.0.2/lib/ --add-modules=javafx.controls,javafx.fxml,javafx.base,javafx.web,javafx.swing,javafx.graphics --add-exports javafx.graphics/com.sun.javafx.application=ALL-UNNAMED -Dmosip.mock.backend=true -Dprism.verbose=true -cp "*" io.mosip.registration.controller.Initialization