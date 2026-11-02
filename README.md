# FaceLiveliness-Mosip-Decode

Face liveness detection for the MOSIP Registration Client. By Team DeLeetCode

## Repository layout

| Directory | Description |
|---|---|
| `face-liveness-active/` | Active liveness using challenge-response with MediaPipe. gRPC service on port `50051`. |
| `face-liveness-passive/` | Passive liveness (PAD) using FSFM models, plus hybrid passive + active. gRPC service on port `50052`. |
| `face-liveness-desktop/` | Java modules. `liveness-grpc-client` is the Java client used by the Registration Client. |
| `mosip/` | MOSIP integration: Desktop and Android Registration Clients and MockMDS (git submodules), patches, scripts and tools. |
| `docs/TECHNICAL_DESIGN.md` | Architecture, flows, configuration, interfaces, security and ISO/IEC 30107 notes. |
| `docs/DESKTOP_REGISTRATION_SETUP.md` | Instructions for setting up the Desktop Registration Client (for Linux and Windows) |