# Android Registration Client: setup from scratch

How to build MOSIP's Android Registration Client with our face liveness integration and run it on a phone,
**without a MOSIP server**. A mock backend inside the app answers login and sync, and mock device apps provide
the biometric devices. The face is captured from the phone's real camera and goes through our liveness check.

Tested on Ubuntu with a vivo I2221 (Android 16).

## What you end up with

| On the phone | What it does |
|---|---|
| **Registration Client** (`io.mosip.registration_client`) | MOSIP's Android client + our liveness patch + the mock backend |
| **Face SBI** (`nprime.reg.sbi.face`) | Face device using the phone camera |
| **Mock Android SBI** (`io.mosip.mock.sbi`) | Mock fingerprint and iris devices (sample images), MOSIP's Android counterpart of MockMDS |
| Liveness models in the app's folder | The two ONNX models the on-device liveness check runs |

## 1. Prerequisites (laptop)

- Linux, about 10 GB free disk.
- **JDK 21** for the Android build (`/usr/lib/jvm/java-21-openjdk-amd64`). JDK 11 is still needed for the desktop
  client and MockMDS.
- **Android SDK**: install Android Studio once, or only the command-line tools, into `~/Android/Sdk`. Gradle
  downloads the missing SDK platforms (34 etc.) itself on the first build. Android Studio is otherwise optional.
- **Flutter 3.10.4**. The app needs this exact line; newer Flutter versions do not build it.
  ```bash
  curl -L -o /tmp/flutter.tar.xz https://storage.googleapis.com/flutter_infra_release/releases/stable/linux/flutter_linux_3.10.4-stable.tar.xz
  tar -xf /tmp/flutter.tar.xz -C ~ && rm /tmp/flutter.tar.xz      # -> ~/flutter
  ```
- `adb`: `sudo apt install adb`, or use the one in `~/Android/Sdk/platform-tools`.
- The repo's own setup done once: `mosip/scripts/setup.sh` (see `command.md` section 1). It fetches the submodules,
  applies our liveness patches (including the Android one) and builds MockMDS, which the device keys come from.

## 2. Build the app with the mock backend

Run this in each new terminal used for the Android build:

```bash
export PATH=$HOME/flutter/bin:$PATH ANDROID_HOME=$HOME/Android/Sdk ANDROID_SDK_ROOT=$HOME/Android/Sdk \
       JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64
```

```bash
cd mosip/android-registration-client
git apply ../patches/android-mock-backend.patch        # once, on top of the liveness patch from setup.sh
bash pigeon.sh                                         # once: generates the Dart <-> Java bridge code
ORG_GRADLE_PROJECT_mosipMockBackend=true flutter build apk --debug --no-multidex
# -> build/app/outputs/flutter-apk/app-debug.apk (about 470 MB; the first build takes a few minutes)
```

- Without `pigeon.sh` the build fails with `Error when reading 'lib/pigeon/…'`.
- `pigeon.sh` and `flutter pub get` also modify a few generated files (`pubspec.lock`, iOS/macOS/Windows plugin
  glue). Leave them out of any patch.
- Without `ORG_GRADLE_PROJECT_mosipMockBackend=true` you get the normal app, which needs a real MOSIP server.

## 3. Prepare the phone

1. **Developer options**: Settings → About phone → tap the build or software version number 7 times. On vivo it
   is under About phone → Software information.
2. **USB debugging** on (Developer options). On vivo also turn on **"USB debugging (Security settings)"** and
   **"Install via USB"** if present.
3. Connect by USB, accept **"Allow USB debugging?"** (tick *Always allow*). Check with `adb devices`: the phone
   must show as `device`.

## 4. Install the apps and models

Large APKs are more reliable copied to the phone and installed from there; a streamed `adb install` can drop the
connection.

```bash
# 4a. Registration Client
adb push build/app/outputs/flutter-apk/app-debug.apk /data/local/tmp/regclient.apk
adb shell pm install -r -g /data/local/tmp/regclient.apk && adb shell rm /data/local/tmp/regclient.apk

# 4b. MOSIP's Android device apps: https://github.com/mosip/android-camera-mds/releases (vDP1, camera-mds.zip).
#     The download is a zip inside a zip.
mkdir -p ~/camera-mds && cd ~/camera-mds
curl -L -o camera-mds.zip https://github.com/mosip/android-camera-mds/releases/download/vDP1/camera-mds.zip
unzip -o camera-mds.zip -d outer && unzip -o outer/camera-mds.zip -d app
adb install -r -g app/APKs/FaceRegSBI-v0.9.5.2.apk                                     # Face SBI (camera)
adb install -r -g app/MockAndroidSBI/app/build/outputs/apk/debug/app-debug.apk         # Mock Android SBI
cd -

# 4c. Liveness models: export once on the laptop, then copy to the app's folder (the app checks their SHA-256)
~/miniconda3/envs/face-liveness-passive/bin/pip install onnx onnxruntime          # once
(cd ../../face-liveness-passive && ~/miniconda3/envs/face-liveness-passive/bin/python scripts/export_onnx.py)
adb shell mkdir -p /sdcard/Android/data/io.mosip.registration_client/files/liveness-models
adb push ../../face-liveness-passive/models/onnx/fsfm_unified.onnx ../../face-liveness-passive/models/onnx/fsfm_fas.onnx \
    /sdcard/Android/data/io.mosip.registration_client/files/liveness-models/
```

## 5. Give Mock Android SBI its device keys

Mock Android SBI signs its responses with a device key you import once.

```bash
mosip/scripts/android-sbi-keys.sh      # from the repo root: converts MockMDS's test keys and copies them to Download
```

Then, on the phone, open **Mock Android SBI** → **SETTINGS**:

| | Key Alias | Key Store Password | BROWSE → Download → |
|---|---|---|---|
| **Device Key** | `mosipfingerslap` | `mosipfingerslap` | `mosipfingerslap-android.p12` |
| **FTM Key** | `mosipfingerslapftm` | `mosipfingerslapftm` | `mosipfingerslapftm-android.p12` |

Save. Then, on the main screen, tap **LOAD AND VALIDATE CERTIFICATES**.

Use the `-android.p12` files that the script makes, not MockMDS's originals. The originals use encryption that
current Android cannot read, and the app reports **"Device key validation failed"**.

## 6. First run

1. Open **Registration Client**. Log in with any user ID and password; the mock accepts anything. We use
   `demo-operator` / `demo-operator`.
2. The first sync runs and shows **"Sync Completed Successfully – System will restart…"**.
   If the app does not restart within ~10 s, close it and open it again. The synced data is already saved:
   ```bash
   adb shell am force-stop io.mosip.registration_client
   ```
3. Log in again. You land on **Officer's Biometric Onboarding**. Tap **Scan** for each biometric. If Android asks
   which app to use, choose **Mock Android SBI** for fingerprints and iris, and **Face SBI** for the face.
4. At the face step our liveness check opens first, on the real camera: "Checking face liveness…", possibly a
   prompt such as "Please blink". After it passes, Face SBI captures the face.
5. After onboarding: **New Registration**. The resident's face step runs the liveness check the same way.

To follow what happens, especially the mock backend's answers:

```bash
adb logcat -v time | grep -E 'MockBackend|flutter|MasterDataService|Biometrics'
```

## How the mock backend works (`mosip/patches/android-mock-backend.patch`)

- **One flag**: the Gradle property `mosipMockBackend`, default `false`. It also reaches Flutter as
  `FlutterConfig.get('MOCK_BACKEND')`.
- **`MockBackendInterceptor`** is the first interceptor of the app's only HTTP client (`NetworkModule`). It answers
  every MOSIP server call in-app:
  - login, which accepts any user and returns a token with the officer, supervisor and operator roles;
  - configuration, master data (client settings), user details, ID schema and UI specs;
  - the policy, IDA and CA certificates, and the applicant-type script;
  - operator authentication, packet sync and upload.
- **Responses are encrypted with the phone's own key**, as a real server does for a registered machine, so the
  app's normal sync code stores them unchanged.
- **Sample data** (`clientmanager/src/mockBackend/assets/mock-backend/`) is MOSIP's published sample data, the same
  files as the desktop mock backend (`mock-backend.patch`). It is only packaged when the flag is on.
- **Two Flutter-side checks** contact the server directly (health check and server version, in
  `network_service_impl.dart`). They are answered locally too.
- **Liveness challenges**: the mock config limits the active challenges to blink, smile, open mouth and head
  turns/tilts. The eye-gaze challenges and nod need the head held almost still, which rarely works with a handheld
  phone.
- **Device certificates**: in mock builds the device's signature is still verified, but the certificate chain is
  not (`Biometrics095Service`). No CA list is synced, and the test device apps use vendor test CAs.

Never ship a mock build: it accepts any credentials.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `Error when reading 'lib/pigeon/…'` while building | Run `bash pigeon.sh` first |
| `adb devices` lists nothing, phone only charges | USB debugging is off, or the USB mode is charging only (choose *File transfer*) |
| `adb install` fails / phone goes `offline` | Use the push + `pm install` route from step 4; on vivo, enable *Install via USB* |
| Login does nothing, log shows `Failed host lookup` | The app was built without `ORG_GRADLE_PROJECT_mosipMockBackend=true` |
| Stuck on "Sync Completed Successfully" | Force-stop and reopen the app (step 6.2) |
| Log shows `generateJobServiceId … StringIndexOutOfBounds` | Harmless: the sample data has no sync job definitions, so last-sync times and background jobs are not recorded |
| "No SBI found" on Scan | Mock Android SBI has no device key yet (step 5) or Face SBI is not installed |
| "Device key validation failed" in Mock Android SBI | You imported MockMDS's original `.p12`; use the `-android.p12` files from `android-sbi-keys.sh` |
| Fingerprint or iris onboarding cannot be done | Only the face is real. Fingerprints and iris come from Mock Android SBI's sample images; choose it when Android asks |

## Status

- **Verified on the phone:** build, install, mock login, the full first sync, and reaching Officer's Biometric
  Onboarding.
- **Not yet confirmed on a phone:** the device steps after that, i.e. capture with Mock Android SBI and Face SBI,
  the liveness check during onboarding and New Registration.
