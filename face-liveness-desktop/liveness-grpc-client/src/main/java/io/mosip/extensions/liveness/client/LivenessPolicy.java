package io.mosip.extensions.liveness.client;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Objects;

/**
 * Per-session liveness policy sent to the service (spec "Configuration": threshold, active enablement,
 * challenge types, minimum count, timeout, retries, per workflow). Unset values keep the service's
 * configured defaults. Immutable; use {@link #builder()}.
 */
public final class LivenessPolicy {

    /** Challenge names understood by the service. */
    public static final List<String> CHALLENGE_TYPES = Collections.unmodifiableList(java.util.Arrays.asList(
            "blink", "smile", "open_mouth", "turn_left", "turn_right", "look_up", "look_down", "nod",
            "gaze_left", "gaze_right", "gaze_up", "gaze_down"));

    private static final LivenessPolicy DEFAULTS = builder().build();

    private final Float acceptThreshold;
    private final Float rejectThreshold;
    private final Boolean failOnPassiveNoResponse;
    private final Boolean activeEnabled;
    private final Integer minChallenges;
    private final List<String> challengeTypes;
    private final Boolean compoundChallenges;
    private final Integer maxRetries;
    private final List<Float> stepTimeoutsSeconds;

    private LivenessPolicy(Builder b) {
        this.acceptThreshold = b.acceptThreshold;
        this.rejectThreshold = b.rejectThreshold;
        this.failOnPassiveNoResponse = b.failOnPassiveNoResponse;
        this.activeEnabled = b.activeEnabled;
        this.minChallenges = b.minChallenges;
        this.challengeTypes = Collections.unmodifiableList(new ArrayList<>(b.challengeTypes));
        this.compoundChallenges = b.compoundChallenges;
        this.maxRetries = b.maxRetries;
        this.stepTimeoutsSeconds = Collections.unmodifiableList(new ArrayList<>(b.stepTimeoutsSeconds));
        check(acceptThreshold == null || acceptThreshold >= 0 && acceptThreshold <= 1, "acceptThreshold in [0,1]");
        check(rejectThreshold == null || rejectThreshold >= 0 && rejectThreshold <= 1, "rejectThreshold in [0,1]");
        check(acceptThreshold == null || rejectThreshold == null || rejectThreshold <= acceptThreshold,
                "rejectThreshold <= acceptThreshold");
        check(minChallenges == null || minChallenges >= 1, "minChallenges >= 1");
        check(maxRetries == null || maxRetries >= 0, "maxRetries >= 0");
        for (String c : challengeTypes) {
            check(CHALLENGE_TYPES.contains(c), "unknown challenge type '" + c + "', valid: " + CHALLENGE_TYPES);
        }
        check(challengeTypes.stream().distinct().count() == challengeTypes.size(), "duplicate challenge types");
        for (Float t : stepTimeoutsSeconds) {
            check(t != null && t > 0, "step timeouts must be > 0");
        }
    }

    private static void check(boolean ok, String message) {
        if (!ok) throw new IllegalArgumentException("liveness policy: " + message);
    }

    public static Builder builder() { return new Builder(); }

    /** No overrides: the service's configuration applies. */
    public static LivenessPolicy defaults() { return DEFAULTS; }

    public Float getAcceptThreshold() { return acceptThreshold; }
    public Float getRejectThreshold() { return rejectThreshold; }
    public Boolean getFailOnPassiveNoResponse() { return failOnPassiveNoResponse; }
    public Boolean getActiveEnabled() { return activeEnabled; }
    public Integer getMinChallenges() { return minChallenges; }
    public List<String> getChallengeTypes() { return challengeTypes; }
    public Boolean getCompoundChallenges() { return compoundChallenges; }
    public Integer getMaxRetries() { return maxRetries; }
    public List<Float> getStepTimeoutsSeconds() { return stepTimeoutsSeconds; }

    @Override
    public boolean equals(Object o) {
        if (!(o instanceof LivenessPolicy)) return false;
        LivenessPolicy p = (LivenessPolicy) o;
        return Objects.equals(acceptThreshold, p.acceptThreshold) && Objects.equals(rejectThreshold, p.rejectThreshold)
                && Objects.equals(failOnPassiveNoResponse, p.failOnPassiveNoResponse)
                && Objects.equals(activeEnabled, p.activeEnabled) && Objects.equals(minChallenges, p.minChallenges)
                && challengeTypes.equals(p.challengeTypes) && Objects.equals(compoundChallenges, p.compoundChallenges)
                && Objects.equals(maxRetries, p.maxRetries) && stepTimeoutsSeconds.equals(p.stepTimeoutsSeconds);
    }

    @Override
    public int hashCode() {
        return Objects.hash(acceptThreshold, rejectThreshold, failOnPassiveNoResponse, activeEnabled, minChallenges,
                challengeTypes, compoundChallenges, maxRetries, stepTimeoutsSeconds);
    }

    @Override
    public String toString() {
        return "LivenessPolicy{accept=" + acceptThreshold + ", reject=" + rejectThreshold + ", failOnNoResponse="
                + failOnPassiveNoResponse + ", active=" + activeEnabled + ", minChallenges=" + minChallenges
                + ", types=" + challengeTypes + ", compound=" + compoundChallenges + ", maxRetries=" + maxRetries
                + ", timeouts=" + stepTimeoutsSeconds + "}";
    }

    public static final class Builder {
        private Float acceptThreshold;
        private Float rejectThreshold;
        private Boolean failOnPassiveNoResponse;
        private Boolean activeEnabled;
        private Integer minChallenges;
        private List<String> challengeTypes = new ArrayList<>();
        private Boolean compoundChallenges;
        private Integer maxRetries;
        private List<Float> stepTimeoutsSeconds = new ArrayList<>();

        public Builder acceptThreshold(Float v) { acceptThreshold = v; return this; }
        public Builder rejectThreshold(Float v) { rejectThreshold = v; return this; }
        public Builder failOnPassiveNoResponse(Boolean v) { failOnPassiveNoResponse = v; return this; }
        public Builder activeEnabled(Boolean v) { activeEnabled = v; return this; }
        public Builder minChallenges(Integer v) { minChallenges = v; return this; }
        public Builder challengeTypes(List<String> v) { challengeTypes = v == null ? new ArrayList<>() : new ArrayList<>(v); return this; }
        public Builder compoundChallenges(Boolean v) { compoundChallenges = v; return this; }
        public Builder maxRetries(Integer v) { maxRetries = v; return this; }
        public Builder stepTimeoutsSeconds(List<Float> v) { stepTimeoutsSeconds = v == null ? new ArrayList<>() : new ArrayList<>(v); return this; }
        public LivenessPolicy build() { return new LivenessPolicy(this); }
    }
}
