# Configuration plan

Future configuration belongs in the local adapter deployment, not in MOSIP
source code. Reserve configuration for:

- enablement and workflow policies;
- passive/active liveness thresholds;
- retry and challenge time limits;
- liveness-engine model location/version;
- device vendor/connection settings;
- MDS/SBI specification version and local port;
- audit and diagnostic log controls.

## Model location

For development, place the selected ONNX model beside the deployment module:

```text
distribution/models/face-liveness.onnx
```

The file is intentionally ignored by Git. Production installation should copy
the signed, approved model to the application's installed `models/` directory
and set `liveness.model.path` to that local absolute path when necessary.
The model must remain local so passive liveness and PAD work offline.
