# MOSIP integration: face liveness in the Registration Clients

The active and passive liveness modules of this repository are integrated into both MOSIP Registration
Clients. Liveness and PAD run before the face is captured, and the capture proceeds only when liveness passes.

- **Desktop Registration Client 1.2.0.x.** Runs on the face stream from the L0/L1 device in the four face flows:
  resident registration, operator login, operator/supervisor authentication, and supervisor end-of-day (EOD)
  approval.
- **Android Registration Client 1.2.x.** An on-device port of the same engine runs on the CameraX front camera
  before the SBI face capture. It covers resident registration and operator biometric onboarding; upstream
  Android login and supervisor approval are password-only.

| Document | |
|---|---|
| [../command.md](../command.md) | Setup, running, tests, builds |
| [../docs/TECHNICAL_DESIGN.md](../docs/TECHNICAL_DESIGN.md) | Architecture, flows, configuration, interfaces, error handling, security, ISO/IEC 30107 |
| [../docs/MOSIP_Liveness_Tracker.xlsx](../docs/MOSIP_Liveness_Tracker.xlsx) | Open tasks (T01–T31) and the status of every line of the problem statement |

## Layout

| Path | What |
|---|---|
| `registration-client/` | Submodule `mosip/registration-client`, pinned to upstream `release-1.2.0.x`; the integration is on the local branch **`face-liveness`** |
| `android-registration-client/` | Submodule `mosip/android-registration-client`, pinned to upstream `release-1.2.x`; local branch **`face-liveness`** |
| `mosip-mock-services/` | Submodule `mosip/mosip-mock-services` `release-1.2.0.x`; **MockMDS** is MOSIP's mock L0 face device (SBI 0.9.5) |
| `patches/<client>-face-liveness.patch` | The changes to each client. `setup.sh` applies them on a fresh clone; `scripts/make-patches.sh` regenerates them |
| `scripts/` | `setup.sh`, `make-patches.sh`, `start-services.sh`, `stop-services.sh`, `run-webcam-device.sh`, `run-reg-client.sh`, `env.sh` |
| `ANDROID_SETUP.md` | Step-by-step setup of the Android Registration Client on a phone with the mock backend (no MOSIP server) |
| `../demo-client/` | Look-alike Registration Client that runs the client's own liveness code in all three flows without a MOSIP server (see below) |
| `tools/mockmds_webcam_feeder.py` | Turns MockMDS into a live device by feeding it webcam frames |
| `tools/perf_interop.py` | Performance and interoperability tests against the engine and the SBI device |
| `../face-liveness-desktop/liveness-grpc-client/` | Java client for the liveness engine, with gRPC and protobuf shaded in; the desktop client depends on it |

## Desktop: how it fits together

```text
 L0/L1 device (MockMDS :4501, SBI 0.9.5)
   │  STREAM (MJPEG)                          RCAPTURE (only after liveness passed)
   ▼                                                ▲
 Registration Client ── Streamer ──frames──▶ FaceLivenessGuard ──gRPC──▶ liveness engine 127.0.0.1:50052
 (JavaFX)                │                      │                     (started by the client if not running:
                         ▼                      ▼                      passive PAD, then active challenges)
                    face preview  ◀── LivenessOverlayPane: "Checking face liveness…", "Please blink",
                                      "Step 2 of 3 · 6 s", "Retry available …", result
```

1. The client opens the device stream as before. `Streamer` now also passes every JPEG frame to a listener.
2. Before RCAPTURE, `FaceLivenessGuard.verify(workflow, …)` runs a hybrid session on those frames (up to 15
   fps, without blocking the stream). It uses the workflow's policy from the client's global parameters.
3. **Passive** first: a bona fide score at or above the accept threshold passes; an attack fails. Anything
   else starts **active** challenges: chosen at random, escalating, with retries, and with PAD still checked
   during the challenges.
4. PASSED → the face is captured through the unchanged MOSIP code path. Any other result → no capture. The user
   sees only a generic message (spec 10.6).
5. Device problems end the session quickly with a device message instead of a liveness failure:
   - no frames for 10 s;
   - stream closed (unplugged);
   - 30 invalid frames in a row.
6. Audit events: `REG-EVT-104` passed, `105` failed, `106` presentation attack, `107` engine error, `108`
   blocked after repeated failures, `109` device error. Log lines hold the decision, reason, score and session
   ID, never images.
7. **Settings → Device Settings → Face liveness diagnostics** shows:
   - the SBI face device and its capabilities;
   - engine status and capabilities (challenges, attack classes, model integrity);
   - each workflow's effective policy;
   - anonymised metrics.

## Desktop changes (`patches/registration-client-face-liveness.patch`)

| File | Change |
|---|---|
| `registration-client/pom.xml` | + `io.mosip.extensions:liveness-grpc-client` (shaded), + junit (test) |
| `controller/device/Streamer.java` | + `FrameListener` (frame and stream-stopped callbacks), `isStreaming()`. **Fix:** a closed device stream no longer spins forever (`EOFException`) |
| `controller/device/FaceLivenessGuard.java` | **new**: configuration, session, frame hook, device watchdog, decision, audit, repeated-failure block, diagnostics |
| `controller/device/LivenessOverlayPane.java` | **new**: positioning oval plus status, guidance and progress band over the preview (declared in the FXML) |
| `controller/device/LivenessEngineManager.java` | **new**: starts the bundled engine if it isn't running, and stops it on exit |
| `controller/device/LivenessMetrics.java` | **new**: anonymised per-workflow metrics (processing and challenge times, retry and failure rates) |
| `controller/device/GenericBiometricsController.java` | Resident FACE capture: verify before `rCapture` |
| `controller/auth/LoginController.java` | Operator face login: verify before the face match |
| `controller/auth/AuthenticationController.java` | Packet authentication: operator workflow, or supervisor workflow when `isReviewer` |
| `controller/eodapproval/EODAuthenticationController.java` | EOD approval face authentication (supervisor workflow) |
| `controller/settings/impl/DeviceSettingsController.java` | Face liveness diagnostics card |
| `fxml/GenericBiometricFXML.fxml`, `RegistrationLogin.fxml`, `OperatorAuthentication.fxml`, `Authentication.fxml` | The overlay over each face preview |
| `registration-services/.../constants/AuditEvent.java` | + `REG_FACE_LIVENESS_*`, `REG-EVT-104…109` |
| `src/test/.../FaceLivenessGuardTest.java` | 18 tests (the device and engine tests need `start-services.sh`; they are skipped otherwise) |

## Android changes (`patches/android-registration-client-face-liveness.patch`)

| File | Change |
|---|---|
| `android/livenessmanager/` | **new module**:<br>• port of the passive engine (Pillow-exact preprocessing, ONNX Runtime) and the active engine (MediaPipe)<br>• hybrid session<br>• `LivenessActivity` (CameraX)<br>• `ModelStore` (pinned SHA-256)<br>• JVM tests: parity with Python, sessions |
| `android/app/.../BiometricsDetailsApi.java` | FACE: run `LivenessActivity` before the SBI intent, with the policy from global parameters; result handling, audit, repeated-failure block |
| `android/app/.../MainActivity.java` | Routes the liveness result back |
| `android/clientmanager/.../AuditEvent.java` | + `FACE_LIVENESS_*`, `REG-EVT-115…119` |
| `lib/utils/face_liveness.dart` + three capture widgets | Show the liveness message, and skip the capture without consuming a MOSIP capture attempt |
| `android/settings.gradle`, `app/` and `clientmanager/build.gradle`, `gradle.properties` | Module include, protobuf exclusion (clashes with MediaPipe), 4 GB Gradle heap |

## Configuration

Registration Client global parameters (for example `registration-default.properties` in mosip-config), synced
to the client and cached for offline use. The same keys drive Desktop and Android. A per-workflow key
(`…liveness.resident.…`, `operator`, `supervisor`) wins over the shared key; unset keys keep the engine
defaults. The full list is in [TECHNICAL_DESIGN §8](../docs/TECHNICAL_DESIGN.md).

```properties
mosip.registration.face.liveness.enable=Y
mosip.registration.face.liveness.supervisor.passive.threshold=0.90     # accept threshold (default 0.80)
mosip.registration.face.liveness.passive.reject.threshold=0.40         # PAD attack threshold
mosip.registration.face.liveness.active.min.challenges=3
mosip.registration.face.liveness.active.challenge.types=blink,smile,turn_left,turn_right,nod
mosip.registration.face.liveness.active.challenge.timeout.seconds=8,6,5
mosip.registration.face.liveness.active.max.retries=3
mosip.registration.face.liveness.repeated.failure.max.sessions=3
mosip.registration.face.liveness.repeated.failure.action=BLOCK
mosip.registration.face.liveness.engine.error.policy=DENY
```

## Decisions to be aware of

- **Login → operator workflow.** The client has no role constant that tells a supervisor's login apart, so
  every face login uses the *operator* policy. Packet authentication uses *supervisor* when `isReviewer`; EOD
  approval always uses *supervisor*.
- **FACE only (desktop).** The exception photo and the legacy `BiometricsController` (`Biometrics.fxml`,
  operator onboarding) are not gated.
- **Retries** offered by the engine start automatically after `retry.delay.ms`, while the guidance stays on
  screen. After the last retry the user gets the spec's "recovery process" message.
- **Fail closed:** an unreachable engine or an invalid configuration denies the capture.

## Demo client (no MOSIP server)

`../demo-client/` is a look-alike of the Desktop client's flows: login with face, operator onboarding, new
registration with resident face capture, operator authentication and supervisor approval. It runs the client's
own liveness classes unchanged, with no MOSIP server, and keeps its data in an embedded Derby database. Run it with
`demo-client/run.sh`. See `demo-client/README.md`.

## Limitations

- **The real client UI has not been run past login.** Without a MOSIP server the client cannot get past its
  first login (tracker T07–T10). The integration is verified by `FaceLivenessGuardTest` with the real client
  classes, the real engine and MockMDS. It is also shown end to end in the demo client, with the same classes
  and screens copied from the client.
- **Android has not been run on a device yet** (T12, T13). The engine port is verified against Python by
  parity tests.
- MockMDS RCAPTURE returns its profile face, not the camera frame.
- At the default accept threshold (0.80), passive alone accepted MockMDS's static photo (0.866) and a synthetic
  moving printed-photo video (0.827). A synthetic screen replay was rejected as an attack (0.109). Choose the
  threshold from a real evaluation on your devices (T16).
- The FSFM model weights are CC BY-NC 4.0 (non-commercial; T30).
