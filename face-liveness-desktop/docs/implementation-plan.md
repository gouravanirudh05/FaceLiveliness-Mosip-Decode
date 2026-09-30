# Desktop implementation plan

## Runtime placement

Run one local desktop process alongside MOSIP Registration Client. The process
implements an MDS/SBI-compatible face device endpoint and talks to either a
physical device SDK or a local camera adapter.

```text
MOSIP client -- MDS/SBI --> mds-adapter --> device SDK/camera
                                  |
                                  +--> liveness-core --> local vision runtime
                                  +--> optional JavaFX companion UI
```

MOSIP remains unchanged. It sees a normal face MDS device and accepts or
rejects the standard capture response it receives.

## Module ownership

| Concern | Module | Replace/implement later |
| --- | --- | --- |
| Frame, decision, challenge contracts | `liveness-api` | Never vendor-specific |
| Passive/active workflow and retry policy | `liveness-core` | `FaceLivenessEngine` implementation |
| Device SDK and MDS/SBI HTTP protocol | `mds-adapter` | `DeviceFrameSource`, endpoints, DTO mapping |
| Local active-challenge prompt | `desktop-companion-ui` | JavaFX presenter/view |
| Configuration and installer | `distribution` | profile, models, certificates, service launcher |

## Frame-to-capture sequence

1. MOSIP opens the configured face stream endpoint.
2. `mds-adapter` obtains JPEG frames from the device and supplies the stream.
3. It also forwards each frame to `LivenessSessionCoordinator`.
4. The coordinator calls the selected `FaceLivenessEngine` locally.
5. A passive pass permits capture; insufficient confidence can request an
   `ActiveChallenge`; PAD failure denies the session.
6. On the final MDS capture call, `MdsCaptureGate` returns the current decision.
   Only `ACCEPTED` may produce a normal biometric response.

## First implementation milestone

Build a passive-only, offline proof of integration first:

1. one device vendor;
2. one MDS/SBI protocol version;
3. a local model that returns accept/reject;
4. no active challenge UI;
5. standard MDS error response on rejection.

After this works against the unmodified client, add active challenges and the
companion JavaFX UI.
