package io.mosip.extensions.liveness.client;

import java.util.Collections;
import java.util.List;
import java.util.Objects;

/**
 * A user-facing progress event of a hybrid session, for the capture screen.
 * The text never contains model or attack details (spec 10.6: PAD details only in audit/diagnostics).
 */
public final class LivenessUpdate {

    public enum Kind {
        /** Passive check running ("Checking face liveness…"); {@link #getGuidance()} has positioning hints. */
        CHECKING,
        /** An active challenge to perform now; {@link #getTimeoutMs()} is its time limit. */
        CHALLENGE,
        /** Real-time guidance during a challenge ("Please continue", "Action detected", ...). */
        FEEDBACK,
        /** A challenge step ended; {@link #isPassed()} says how. */
        CHALLENGE_RESULT,
        /** The attempt failed and a retry is available; {@link #getGuidance()} says what to improve. */
        RETRY,
        /** Final: the session is over, see {@link HybridLivenessSession#awaitOutcome}. */
        DONE
    }

    private final Kind kind;
    private final String text;
    private final double progress;
    private final List<String> guidance;
    private final long timeoutMs;
    private final int retriesRemaining;
    private final boolean passed;
    private int step;
    private int totalSteps;
    private int attempt;

    LivenessUpdate(Kind kind, String text, double progress, List<String> guidance, long timeoutMs,
                   int retriesRemaining) {
        this(kind, text, progress, guidance, timeoutMs, retriesRemaining, false);
    }

    LivenessUpdate(Kind kind, String text, double progress, List<String> guidance, long timeoutMs,
                   int retriesRemaining, boolean passed) {
        this.kind = Objects.requireNonNull(kind, "kind");
        this.text = text == null ? "" : text;
        this.progress = progress;
        this.guidance = guidance == null ? Collections.emptyList() : Collections.unmodifiableList(guidance);
        this.timeoutMs = timeoutMs;
        this.retriesRemaining = retriesRemaining;
        this.passed = passed;
    }

    /** For {@link Kind#CHALLENGE_RESULT}: whether the step was passed. */
    public boolean isPassed() { return passed; }

    public Kind getKind() { return kind; }
    public String getText() { return text; }
    /** 0..1 progress of the current passive collection or challenge step. */
    public double getProgress() { return progress; }
    public List<String> getGuidance() { return guidance; }
    /** Challenge time limit in ms; 0 when not a challenge. */
    public long getTimeoutMs() { return timeoutMs; }
    /** Retries left after this one; -1 when not a retry event. */
    public int getRetriesRemaining() { return retriesRemaining; }
    /** For {@link Kind#CHALLENGE}: 1-based step number; 0 when not a challenge. */
    public int getStep() { return step; }
    /** For {@link Kind#CHALLENGE}: number of steps in this attempt (may grow by escalation); 0 when not a challenge. */
    public int getTotalSteps() { return totalSteps; }
    /** For {@link Kind#CHALLENGE}: 1-based attempt number; 0 when not a challenge. */
    public int getAttempt() { return attempt; }

    LivenessUpdate withSteps(int step, int totalSteps, int attempt) {
        this.step = step;
        this.totalSteps = totalSteps;
        this.attempt = attempt;
        return this;
    }

    @Override
    public String toString() {
        return kind + ": " + text + (guidance.isEmpty() ? "" : " " + guidance);
    }
}
