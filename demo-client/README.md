# Demo client: face liveness in Registration Client flows, without a MOSIP server

A small JavaFX app that copies the MOSIP Desktop Registration Client's flows so the face liveness integration can
be shown end to end without a MOSIP backend. It is compiled against the patched `registration-client` jar and
runs on its classpath, so every face step uses the client's own classes unchanged:

- `FaceLivenessGuard.verify(...)`, built through `DemoGuardFactory` (the same constructor the client's tests use)
- `Streamer` on the MockMDS SBI `STREAM`
- `LivenessOverlayPane` for prompts, progress and results
- the `mosip.registration.face.liveness.*` global parameters, read from `ApplicationContext`
- the audit events `REG-EVT-104…109`

## Run

```bash
mosip/scripts/start-services.sh     # liveness engine (gRPC 50052) + MockMDS (SBI 4501)
mosip/scripts/run-webcam-device.sh  # optional: your webcam instead of MockMDS's still photo
demo-client/run.sh                  # builds on the first run
```

| User | Password | Role |
|---|---|---|
| `110011` | `mosip123` | Registration officer |
| `110012` | `mosip123` | Supervisor (also an officer) |

## Architecture

```
demo-client (JavaFX)  ── gRPC :50052 ──▶  liveness engine (Python: FSFM PAD + MediaPipe challenges)
        │             ── SBI  :4501  ──▶  MockMDS (mock face device; webcam feeder optional)
        ▼
demo-client/data/
  db/                 embedded Apache Derby database, schema REG (the client's own database engine)
  operators/<id>/     onboarded operators' face images
  packets/<RID>/      registration face images
  derby.log
```

There is no server. The records are in the database, and the face images are files whose paths are stored in the
tables. The real client also keeps biometrics in packet files on disk rather than in its database.

| Table | Contents |
|---|---|
| `REG.USER_DETAIL` | Users, roles, password hash (PBKDF2-SHA256 with salt), onboarding status and face path. Seeded from `src/main/resources/demo-users.json` when the database is first created |
| `REG.REGISTRATION` | One row per registration: demographics, centre, machine, officer, face path, liveness session and result, status (`PENDING_APPROVAL` / `APPROVED` / `REJECTED`), reviewer |
| `REG.LIVENESS_RESULT` | Every liveness decision: workflow, subject, session ID, status, reason. No images or scores |
| `REG.AUDIT_LOG` | Liveness audit events from the guard (REG-EVT-104…109) and the demo's own events (login, onboarding, packet created, approved/rejected) |
| `REG.GLOBAL_PARAM` | Liveness policy. Seeded from `src/main/resources/demo.properties` (missing keys only); **Apply & save** on the Settings screen writes here |

The default data folder is `demo-client/data`, which is gitignored. Set `DEMO_DATA=/some/dir` to use another
folder. Delete the folder to start over (onboarding, registrations, saved settings). Without `run.sh`, for
example from an IDE, the data folder is `~/.mosip-demo` unless `-Ddemo.data` is given.

To look at the tables, use Derby's `ij` tool. The jars are in the client's `target/lib`. Close the app first:
embedded Derby allows only one process at a time.

```bash
L="mosip/registration-client/registration/registration-client/target/lib"
java -cp "$L/derby-10.13.1.1.jar:$L/derbytools-10.13.1.1.jar" org.apache.derby.tools.ij
ij> connect 'jdbc:derby:demo-client/data/db';
ij> select RID, FULL_NAME, STATUS, LIVENESS_STATUS from REG.REGISTRATION;
```

## Screens

| Screen | Liveness workflow (policy) |
|---|---|
| Login: password, then face. A user new to the machine is onboarded first (face captured) | `OPERATOR_AUTHENTICATION` |
| New Registration: consent, demographics, **resident face**, preview | `RESIDENT_REGISTRATION` |
| Registration: operator authentication (password + face), then the registration is saved | `OPERATOR_AUTHENTICATION` |
| Pending Approval: approve/reject, then **supervisor authentication** (supervisor role required) | `SUPERVISOR_AUTHENTICATION` |
| Settings & Diagnostics: per-workflow policy (Apply takes effect from the next session) and the guard's diagnostics report | – |
| Audit Log: `REG.AUDIT_LOG` | – |

The default policy sets fewer challenges for operators and a stricter supervisor threshold (0.90).

## Mocked

These are mocked because MOSIP's server would normally provide or receive them:

- Users are seeded locally instead of synced from the server.
- The 1:1 face match against the onboarded face is mocked (always a match). Liveness is real.
- Registrations are not packaged, encrypted or uploaded.

## Note on the camera preview

The preview is decoded with ImageIO, not by the Streamer's ImageView. On Linux desktops where GTK has already
loaded the system libjpeg-turbo, JavaFX 11.0.2's own JPEG decoder fails ("Wrong JPEG library version: library is
80, caller expects 90"). The real client's preview would be blank in the same way on such a machine.

## Layout

| Path | What |
|---|---|
| `run.sh` | Build (when sources changed) and run |
| `src/main/java/io/mosip/demo/` | `DemoApp` (window, login, home), `RegistrationScreen`, `ApprovalScreen`, `SettingsScreen`, `AuditScreen`, `AuthPane`, `FaceCapturePane`, `MockMds`, `DemoDb` (Derby), `DemoStore`, `DemoAudit` |
| `src/main/java/io/mosip/registration/controller/device/DemoGuardFactory.java` | Creates the client's `FaceLivenessGuard` outside Spring |
| `src/main/resources/` | `demo.properties` (default policy), `demo-users.json` (seed users), `demo.css` |
