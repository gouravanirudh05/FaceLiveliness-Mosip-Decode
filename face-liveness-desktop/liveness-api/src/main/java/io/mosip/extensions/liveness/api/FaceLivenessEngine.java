package io.mosip.extensions.liveness.api;

/**
 * Vendor-neutral boundary for local vision-model inference.
 * Implement with a vendor SDK, ONNX Runtime Java, or a native-library bridge.
 */
public interface FaceLivenessEngine {
    LivenessDecision analyse(FaceFrame frame, LivenessSession session);
}
