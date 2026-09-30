package io.mosip.extensions.liveness.api;

/** Current decision for one face liveness session. */
public enum LivenessStatus {
    COLLECTING,
    ACTIVE_CHALLENGE_REQUIRED,
    ACCEPTED,
    REJECTED,
    TIMED_OUT
}
