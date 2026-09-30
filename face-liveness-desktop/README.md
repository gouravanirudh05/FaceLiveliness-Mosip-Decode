# Face Liveness Desktop Adapter

Desktop-only foundation for a local liveness/PAD component that is compatible
with MOSIP Registration Client without modifying the client repository.

The intended runtime boundary is:

```text
MOSIP Registration Client <-> local MDS/SBI adapter <-> device SDK/camera
                                      |
                                      +-> liveness/PAD engine and companion UI
```

This is deliberately a structure-first project. It contains contracts and
compile-ready integration templates, but no device, camera, liveness model,
PAD model, or active-challenge implementation.

## Technology baseline

The skeleton intentionally follows the desktop Registration Client baseline:

- Java 11 and Maven;
- Spring Framework-style service boundaries (when concrete services are added);
- JavaFX 11 for the optional standalone companion UI;
- standard Java `InputStream`/JPEG frame handling at the MDS boundary.

It has no compile-time dependency on the Registration Client. That is required:
this project communicates with it only through the standard local MDS/SBI
protocol.

## Modules

- `liveness-api` — stable vendor-neutral contracts and data types.
- `liveness-core` — workflow orchestration and policy boundary.
- `mds-adapter` — MOSIP MDS/SBI protocol boundary and device-adapter boundary.
- `desktop-companion-ui` — optional local desktop challenge/status UI boundary.
- `distribution` — executable packaging and deployment configuration.

Android is intentionally out of scope for this project. A later Android client
can reuse the API concepts, but needs an Android-specific camera and UI adapter.

## How to proceed

1. **Choose the MDS protocol target.** Start with the SBI/MDS version required
   by the face device deployed at the registration centre.
2. **Implement one device adapter** in `mds-adapter`. It must expose discovery,
   stream, and capture behaviour using the vendor device SDK.
3. **Select a local model runtime.** Implement `FaceLivenessEngine` using a
   vendor Java SDK, ONNX Runtime Java, or a local native library bridge. Do not
   put model code in the MOSIP client.
4. **Implement policy orchestration** in `liveness-core`: passive decision,
   PAD failure, challenge escalation, timeout, retries, and workflow-specific
   policy.
5. **Connect the capture gate.** The MDS adapter may return a successful final
   capture only when `MdsCaptureGate` reports an accepted session.
6. **Add active guidance only if required.** Use `desktop-companion-ui` for a
   separate JavaFX prompt window. An unchanged MOSIP FXML screen cannot host
   the prompt.
7. **Test with a real device and the unmodified MOSIP client.** Verify stream,
   successful capture, liveness rejection, timeout, disconnect, and offline
   operation.

The templates identify where each step belongs; replace only the marked TODO
boundaries as a device and liveness technology are selected.
