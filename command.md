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

```bash
export PATH=$HOME/flutter/bin:$PATH ANDROID_HOME=$HOME/Android/Sdk JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64
cd mosip/android-registration-client
flutter build apk --debug --no-multidex     # -> build/app/outputs/flutter-apk/app-debug.apk
```

`--no-multidex` is fine because minSdk is 28, where multidex is native. Without the flag, Flutter stops at an
interactive prompt. The Gradle heap is set to 4 GB in `android/gradle.properties`; the upstream 1.5 GB ran out
of memory while dexing.

**[not run yet]** The liveness models are not inside the APK. After installing it, provision them once; the
app verifies their SHA-256 before use:

```bash
adb push face-liveness-passive/models/onnx/fsfm_unified.onnx face-liveness-passive/models/onnx/fsfm_fas.onnx \
    /sdcard/Android/data/io.mosip.registration_client/files/liveness-models/
```

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

## 6. The real Registration Client UI  [not possible yet]

On a fresh install the client needs a MOSIP server: it requires an online password login and an initial sync
of the machine, users, configuration and certificates before any screen past login opens. Until a backend is
available, the integration is exercised by `FaceLivenessGuardTest` with the real client classes (section 3).

The plan is a minimal MOSIP 1.2.0.1 stack in Docker plus machine and user onboarding: tracker tasks T07–T10.
It needs about 6 GB of free RAM. MOSIP Collab, or your own MOSIP 1.2.0 deployment, works too.

Once a server exists:
1. Set `mosip.hostname` in `registration-services/src/main/resources/props/mosip-application.properties`.
2. Keep `start-services.sh` running.
3. Run `io.mosip.registration.controller.Initialization` with:

```text
--module-path <javafx-sdk-11.0.2>/lib
--add-modules=javafx.controls,javafx.fxml,javafx.base,javafx.web,javafx.swing,javafx.graphics
--add-exports javafx.graphics/com.sun.javafx.application=ALL-UNNAMED
```

Without a TPM (Linux development), the client uses local software keys in `~/.mosipkeys`.

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
