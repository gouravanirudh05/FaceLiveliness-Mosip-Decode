# MOSIP integration: commands

How the integration works and which files changed: [mosip/README.md](mosip/README.md).
Design: [docs/TECHNICAL_DESIGN.md](docs/TECHNICAL_DESIGN.md). What is done and what is still open:
[docs/MOSIP_Liveness_Tracker.xlsx](docs/MOSIP_Liveness_Tracker.xlsx) (task list T01–T31 and a line-by-line
status of the problem statement).

Every command below was run on the development machine (Linux, 15 GB RAM) unless it's marked
**[not run yet]**.

## 0. Prerequisites

| For | You need |
|---|---|
| Liveness engines | conda envs `face-liveness-passive` and `face-liveness-active` (see each module's README), with the models downloaded: `python face-liveness-passive/scripts/download_models.py` |
| Desktop client | Git, Maven 3. JDK 11 is installed by `setup.sh` into `~/jdks/jdk11` if missing; the system JDK is left alone |
| Android client | Flutter **3.10.4** (newer versions do not match the client's `pubspec.lock`), JDK 21, Android SDK 34 (build-tools 34.0.0, NDK 23.1.7779620) |
| Live device demo | a webcam (optional; without it MockMDS streams its built-in photo) |

**Memory.** The liveness engine takes about 2.5 GB, an Android build about 5 GB and the emulator about 3 GB.
On a 15 GB laptop with Chrome and VS Code open, run one of these at a time. VS Code's Java extension also builds
these Maven/Gradle projects in the background, using about 3 GB and racing your builds in `target/`; close VS Code
for builds.

## 1. One-time setup

```bash
git clone --recursive https://github.com/gouravanirudh05/FaceLiveliness-Mosip-Decode.git
cd FaceLiveliness-Mosip-Decode
mosip/scripts/setup.sh
```

`setup.sh`:
1. Initialises the three MOSIP submodules, pinned to upstream commits (`registration-client` and
   `mosip-mock-services` on `release-1.2.0.x`, `android-registration-client` on `release-1.2.x`).
2. Gives each MOSIP client a local branch `face-liveness`. On a fresh clone it creates the branch and applies
   `mosip/patches/<client>-face-liveness.patch`, and copies MediaPipe's `face_landmarker.task` into the Android
   module.
3. Installs JDK 11 if it's missing.
4. Builds `face-liveness-desktop`, which installs `liveness-grpc-client` into `~/.m2`.
5. Builds MockMDS.
6. Builds the Desktop Registration Client.

Logs go to `.build-logs/`. The first client build downloads several hundred MB.

The MOSIP repos belong to MOSIP, so our changes to them travel as the two patch files, not as commits in the
submodules. **After changing either client, run `mosip/scripts/make-patches.sh` and commit the patches.** The
script regenerates both, leaves out tool-generated files (`pubspec.lock`, iOS pigeon output, mocks) and checks
that each patch reproduces your working tree exactly.

## 2. Start the services

```bash
mosip/scripts/start-services.sh     # liveness engine 127.0.0.1:50052 + MockMDS 127.0.0.1:4501
mosip/scripts/stop-services.sh      # stops them again (by PID file)
mosip/scripts/run-webcam-device.sh  # optional: your webcam becomes the MockMDS face stream (Ctrl-C restores it)
```

- Use `MDS_PURPOSE=Auth mosip/scripts/start-services.sh` for authentication-purpose devices.
- `run-webcam-device.sh --source clip.mp4` feeds a video file instead of the webcam.

Check the device by hand:

```bash
curl -s -X MOSIPDISC http://127.0.0.1:4501/device -H 'Content-Type: application/json' -d '{"type":"Face"}'
```

## 3. Tests

```bash
# Python engines (results as of 2026-10-06)
(cd face-liveness-passive && conda run -n face-liveness-passive python -m pytest -q)   # 182 passed
(cd face-liveness-active  && conda run -n face-liveness-active  python -m pytest -q)   # 164 passed

# Java client library (in-process fake server)
source mosip/scripts/env.sh && use_jdk11
(cd face-liveness-desktop && mvn -q -pl liveness-grpc-client install)                  # 16 tests

# Desktop Registration Client integration: real MOSIP classes against the real engine and MockMDS.
# Start the services first (section 2); without them the device/engine tests are skipped.
(cd "$RC_DIR" && mvn -q -pl registration-services install -DskipTests -Dgpg.skip=true \
   && mvn -q -pl registration-client test -Dtest=FaceLivenessGuardTest -Djacoco.skip=true)   # 18 tests

# Android engine (JVM unit tests). The parity tests need the ONNX export first (2 x 343 MB, gitignored):
conda run -n face-liveness-passive python face-liveness-passive/scripts/export_onnx.py
(cd mosip/android-registration-client/android && ./gradlew :livenessmanager:testDebugUnitTest)   # 17 tests
```

`FaceLivenessGuardTest` covers:
- configuration and per-workflow policy;
- engine unreachable, and an engine that fails to start;
- the engine auto-start;
- the device sending no frames, disconnecting, or sending invalid frames;
- the repeated-failure block;
- the diagnostics report;
- an end-to-end session on the MockMDS stream with the overlay.

## 4. Android build

**New to the Android client?** Follow `mosip/ANDROID_SETUP.md`: the full setup from scratch, including the phone,
the device apps, the device keys and troubleshooting. This section is the short version.

Needs Flutter 3.10.4 (installed at `~/flutter`), the Android SDK (`~/Android/Sdk`; Gradle installs missing
platforms itself) and JDK 21. The app is Flutter, so Android Studio is optional: use it for the SDK Manager,
emulators and debugging.

```bash
export PATH=$HOME/flutter/bin:$PATH ANDROID_HOME=$HOME/Android/Sdk JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64
cd mosip/android-registration-client
bash pigeon.sh                                # once: generates the Dart <-> Java bridge (lib/pigeon/, model/)
flutter build apk --debug --no-multidex       # -> build/app/outputs/flutter-apk/app-debug.apk
```

`--no-multidex` is fine because minSdk is 28, where multidex is native. Without the flag, Flutter stops at an
interactive prompt. The Gradle heap is set to 4 GB in `android/gradle.properties`; the upstream 1.5 GB ran out
of memory while dexing. Without `pigeon.sh`, the build fails with "Error when reading 'lib/pigeon/…'".

### 4.1 Without a MOSIP server: the Android mock backend

`mosip/patches/android-mock-backend.patch` (applied on top of the liveness patch) adds a mock backend, the Android
counterpart of the desktop's `mock-backend.patch` (`-Dmosip.mock.backend=true`). When it is enabled at build time,
`MockBackendInterceptor`, the first interceptor of the app's only HTTP client, answers every MOSIP server call
inside the app:
- login accepts any user and password, and returns a token with the officer and supervisor roles;
- sync data (master data, configuration, user details, ID schema and UI specs, certificates, the applicant type
  script) comes from MOSIP's published sample data, the same files as the desktop mock;
- responses are encrypted with the phone's own key, as the server does for a registered machine, so the app's
  normal sync code stores everything.

```bash
cd mosip/android-registration-client
git apply ../patches/android-mock-backend.patch                     # once
ORG_GRADLE_PROJECT_mosipMockBackend=true flutter build apk --debug --no-multidex
```

The flag (`mosipMockBackend`, default `false`) can also be set in `android/gradle.properties`. When it is off,
the app is unchanged and the sample data is not packaged.

### 4.2 On the phone

Android 9 or newer, with USB debugging enabled (Settings > About phone > tap Build number 7 times, then
Developer options > USB debugging).

```bash
adb install -r build/app/outputs/flutter-apk/app-debug.apk
# MOSIP's camera-based face device (SBI 0.9.5), the Android counterpart of MockMDS:
#   https://github.com/mosip/android-camera-mds/releases (vDP1 camera-mds.zip, a zip inside a zip)
adb install -r <camera-mds>/APKs/FaceRegSBI-v0.9.5.2.apk
# liveness models (exported with: python face-liveness-passive/scripts/export_onnx.py; the app checks SHA-256):
adb push face-liveness-passive/models/onnx/fsfm_unified.onnx face-liveness-passive/models/onnx/fsfm_fas.onnx \
    /sdcard/Android/data/io.mosip.registration_client/files/liveness-models/
```

Open the Registration Client, log in with any user ID and password (mock backend), let the first sync finish,
then onboard the operator and start a new registration; the face steps run the liveness check first.

## 5. Performance and interoperability  [not run yet]

```bash
mosip/scripts/start-services.sh
conda run -n face-liveness-passive python mosip/tools/perf_interop.py     # report: .run/perf_interop_report.json
```

The script measures:
- **Performance:** per-frame latency at 480p, 720p and 1080p; hybrid time-to-decision; SBI stream fps.
- **Interoperability:** seven frame encodings; four resolutions; malformed frames; SBI discovery and device
  info; SBI stream frames; a printed-photo replay escalating to a challenge.

Results are to be written up in `docs/PERFORMANCE_INTEROP.md` (tracker T14).

## 6. The real Registration Client on MOSIP Collab  [login works; first sync blocked on Collab's side]

MOSIP Collab (`*.collab.mosip.net`) is MOSIP's hosted test environment. This machine is registered there with its
TPM key; Collab sent the Registration Client credentials and a WireGuard VPN config. Run everything from the repo
root.

### 6.1 Connect to the VPN

Use a phone hotspot or home Wi-Fi: the IIITB campus Wi-Fi blocks WireGuard (handshake never completes).

```bash
sudo wg-quick up collab        # config installed at /etc/wireguard/collab.conf
sudo wg show collab            # must show "latest handshake: … ago" and non-zero "received"
curl -s -o /dev/null -w '%{http_code}\n' https://api-internal.collab.mosip.net/v1/syncdata/actuator/health   # expect 200
```

If it says the interface already exists, run `sudo wg-quick down collab && sudo wg-quick up collab`. The VPN only
routes Collab's private network (`172.31.0.0/16`); other traffic is unaffected. Logins go to the public
`regclient-api.collab.mosip.net`; the sync's file downloads go to `api-internal.collab.mosip.net` and need the VPN.

### 6.2 Start the liveness engine, MockMDS and the webcam

```bash
mosip/scripts/start-services.sh        # wait for "liveness service: up" and "MockMDS: up"
mosip/scripts/run-webcam-device.sh     # separate terminal, keep running; without it MockMDS shows its sample photo
```

### 6.3 Start the Registration Client

```bash
~/mosip-latest/run-client.sh           # log copy: ~/mosip-latest/client.log
```

This is MOSIP's latest stable release (v1.2.0.2, the same build Collab's download page serves) with our liveness
patch. It needs **Java 11**: the system `java` is 21, which fails with "Cannot load configuration class:
io.mosip.registration.config.AppConfig". The launcher calls `/usr/lib/jvm/java-11-openjdk-amd64/bin/java`.

### 6.4 In the client

1. Log in with the Collab user (`sathish`; the password is in the Collab email).
2. The initial sync runs; restart the client when it asks (run 6.3 again).
3. Operator onboarding: the face capture runs the liveness check.
4. New Registration: the face step runs the liveness check before capture.

**Current status (26 Oct 2026):** login works, but the first sync stops with "Client settings / Master data Sync
failed". Collab's server never answers
`GET https://api-internal.collab.mosip.net/v1/syncdata/scripts/applicanttype.mvel?keyindex=…` (read time-out). The
URL comes from Collab's own sync response and matches the syncdata endpoint; in syncdata 1.3.0 that call fetches the
script from the config server and signs it via the key manager, so the hang is server-side. Collab's syncdata is
1.3.0 while its download page serves client 1.2.0.2; we have asked Collab which client to use.

### 6.5 Stop everything

```bash
pkill -f io.mosip.registration.controller.Initialization
pkill -f mockmds_webcam_feeder
mosip/scripts/stop-services.sh
sudo wg-quick down collab
```

### 6.6 How `~/mosip-latest` was set up (to rebuild it)

```bash
git clone --depth 1 --branch v1.2.0.2 https://github.com/mosip/registration-client.git ~/mosip-latest/registration-client
cd ~/mosip-latest/registration-client
git checkout -b face-liveness && git apply <repo>/mosip/patches/registration-client-face-liveness.patch
cd registration && JAVA_HOME=/usr/lib/jvm/java-11-openjdk-amd64 \
  mvn -o package -DskipTests -Dgpg.skip=true -pl registration-services,registration-client -am
```

- `~/mosip-latest/props/props/mosip-application.properties` overrides the built-in file of the same name (it is
  first on the classpath). It is Collab's file from their download, with two changes:
  - `environment=LOCAL`: `PRODUCTION` verifies MOSIP's signature on the jars, which a source build lacks.
  - `mosip.reg.healthcheck.url` points at a URL that returns 200: Collab's own health URL answers 403, which the
    client reads as "No Internet Connection".
- `~/mosip-latest/extra-lib/` holds jars from Collab's package that a source build lacks: `mock-sdk.jar` (mock
  biometric SDK; without it startup fails with "BIO_SDK_007 SDK provider registry is empty"), the ClamAV virus
  scanner and ICU transliteration.
- MOSIP's source default is `mosip.hostname=dev.mosip.net` (MOSIP's own dev server); the override replaces it with
  `regclient-api.collab.mosip.net`. `mosip/scripts/run-reg-client.sh` does the same for the in-repo build with
  `MOSIP_HOST=… MOSIP_HEALTHCHECK_URL=…`.
- Linux notes, already handled: the client uses the TPM through the `tss` group
  (`sudo usermod -aG tss $USER`, then log in again); our patch truncates host names longer than 32 characters in
  the audit log (they made every login fail on Linux).

### Without a server: the demo client

`demo-client/` runs the client's own liveness code in the login, onboarding, new registration, operator
authentication and supervisor approval flows. No MOSIP server or VPN is involved; data goes to an embedded Derby
database in `demo-client/data`. See `demo-client/README.md`.

```bash
mosip/scripts/start-services.sh       # engine (50052) + MockMDS (4501)
mosip/scripts/run-webcam-device.sh    # optional: your webcam instead of MockMDS's still photo
demo-client/run.sh                    # builds on first run; users 110011 (officer) / 110012 (supervisor), password mosip123
```

## 7. Results so far

Measured on 2026-10-05 against the real engine and MockMDS, driving the client's own classes (`Streamer`,
`FaceLivenessGuard`, the overlay). That harness was later removed, so it can't be rerun as-is.

| Device stream | Workflow | Result | Capture |
|---|---|---|---|
| MockMDS built-in photo (static) | resident | PASSED on passive, score 0.866, 4.5 s | captured |
| synthetic head shot, moving (video via feeder) | operator | PASSED on passive, 0.927 | captured |
| same face on a simulated screen (video) | supervisor | FAILED, attack detected, 0.109; audit REG-EVT-106 | **blocked**; generic message |
| synthetic printed photo, moving (video) | resident | PASSED on passive, 0.827 | captured |
| MockMDS photo, accept threshold raised to 0.99 | resident | 4 challenge rounds, 3 auto-retries, FAILED (active); audit REG-EVT-105 | **blocked** |

From the automated tests:
- An unreachable engine denies capture (REG-EVT-107) unless `engine.error.policy=ALLOW`.
- An unplugged device ends the session in about 2.6 s with a device message (REG-EVT-109). Before the
  `Streamer` fix, the client spun forever on the closed stream.
- Device errors don't count towards the repeated-failure block.

**Caution:** at the default accept threshold of 0.80, a static photo and a moving synthetic print both passed
on passive alone, so their active challenges never ran. Choose the threshold from an evaluation on real attack
data captured on your devices (`passive-liveness-eval`; see
`face-liveness-passive/docs/ISO30107_CONFORMANCE.md` and tracker T16).
