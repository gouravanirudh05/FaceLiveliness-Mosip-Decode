package io.mosip.extensions.liveness.client;

import java.util.Objects;
import java.util.Optional;

/** Final result of one hybrid liveness session. Only {@link Status#PASSED} permits the capture. */
public final class LivenessOutcome {

    public enum Status {
        PASSED,
        /** Liveness could not be established or an attack was detected. */
        FAILED,
        CANCELLED,
        /** No decision within the session timeout. */
        TIMED_OUT,
        /** The liveness service was unreachable or broke the protocol. */
        ENGINE_ERROR
    }

    /** Generic text from spec 10.6, also used for engine errors and timeouts. */
    public static final String GENERIC_FAILURE_MESSAGE = "Face verification could not be completed. Please try again.";

    private final Status status;
    private final String reason;
    private final String userMessage;
    private final Float passiveScore;
    private final String sessionId;
    private final boolean attackDetected;

    LivenessOutcome(Status status, String reason, String userMessage, Float passiveScore, String sessionId,
                    boolean attackDetected) {
        this.status = Objects.requireNonNull(status, "status");
        this.reason = reason == null ? "" : reason;
        this.userMessage = userMessage == null || userMessage.isEmpty() ? defaultMessage(status) : userMessage;
        this.passiveScore = passiveScore;
        this.sessionId = sessionId == null ? "" : sessionId;
        this.attackDetected = attackDetected;
    }

    private static String defaultMessage(Status status) {
        return status == Status.PASSED ? "Face liveness verified." : GENERIC_FAILURE_MESSAGE;
    }

    public Status getStatus() { return status; }
    public boolean isPassed() { return status == Status.PASSED; }
    /** Machine-readable reason (e.g. {@code HYBRID_REASON_ACTIVE_FAILED}); for audit logs only. */
    public String getReason() { return reason; }
    /** Text that may be shown to the user. */
    public String getUserMessage() { return userMessage; }
    public Optional<Float> getPassiveScore() { return Optional.ofNullable(passiveScore); }
    public String getSessionId() { return sessionId; }
    /** True when PAD reported an attack; for audit logs only, never for the UI. */
    public boolean isAttackDetected() { return attackDetected; }

    @Override
    public String toString() {
        return "LivenessOutcome{" + status + ", reason=" + reason + ", passiveScore=" + passiveScore
                + ", attack=" + attackDetected + ", session=" + sessionId + "}";
    }
}
