package io.mosip.extensions.liveness.api;

/** Workflows that require independently configurable liveness policies. */
public enum LivenessWorkflow {
    RESIDENT_REGISTRATION,
    OPERATOR_AUTHENTICATION,
    SUPERVISOR_AUTHENTICATION
}
