package io.mosip.extensions.liveness.api;

import java.util.Optional;

/** Result returned by a local liveness engine after analysing one or more frames. */
public final class LivenessDecision {
    private final LivenessStatus status;
    private final double confidence;
    private final boolean presentationAttackDetected;
    private final ActiveChallenge challenge;

    public LivenessDecision(LivenessStatus status, double confidence,
                            boolean presentationAttackDetected, ActiveChallenge challenge) {
        this.status = status;
        this.confidence = confidence;
        this.presentationAttackDetected = presentationAttackDetected;
        this.challenge = challenge;
    }

    public LivenessStatus getStatus() { return status; }
    public double getConfidence() { return confidence; }
    public boolean isPresentationAttackDetected() { return presentationAttackDetected; }
    public Optional<ActiveChallenge> getChallenge() { return Optional.ofNullable(challenge); }
}
