package io.mosip.extensions.liveness.mds;

import io.mosip.extensions.liveness.api.LivenessDecision;
import io.mosip.extensions.liveness.api.LivenessStatus;

/**
 * Template used by the MDS capture endpoint before returning a successful
 * biometric response to MOSIP.
 */
public final class MdsCaptureGate {
    public boolean permitsCapture(LivenessDecision decision) {
        return decision != null
                && decision.getStatus() == LivenessStatus.ACCEPTED
                && !decision.isPresentationAttackDetected();
    }
}
