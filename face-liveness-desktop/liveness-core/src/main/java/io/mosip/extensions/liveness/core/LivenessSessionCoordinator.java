package io.mosip.extensions.liveness.core;

import io.mosip.extensions.liveness.api.FaceFrame;
import io.mosip.extensions.liveness.api.FaceLivenessEngine;
import io.mosip.extensions.liveness.api.LivenessDecision;
import io.mosip.extensions.liveness.api.LivenessSession;
import java.util.Objects;

/**
 * Template orchestration point. Add policy, retry, audit, and challenge
 * lifecycle here; keep model-specific code in a FaceLivenessEngine adapter.
 */
public final class LivenessSessionCoordinator {
    private final FaceLivenessEngine engine;

    public LivenessSessionCoordinator(FaceLivenessEngine engine) {
        this.engine = Objects.requireNonNull(engine, "engine");
    }

    public LivenessDecision onFrame(FaceFrame frame, LivenessSession session) {
        return engine.analyse(frame, session);
    }
}
