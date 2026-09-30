package io.mosip.extensions.liveness.api;

import java.time.Duration;
import java.util.Objects;

/** A challenge selected by local policy, never by the resident. */
public final class ActiveChallenge {
    private final String type;
    private final String prompt;
    private final Duration timeout;

    public ActiveChallenge(String type, String prompt, Duration timeout) {
        this.type = Objects.requireNonNull(type, "type");
        this.prompt = Objects.requireNonNull(prompt, "prompt");
        this.timeout = Objects.requireNonNull(timeout, "timeout");
    }

    public String getType() { return type; }
    public String getPrompt() { return prompt; }
    public Duration getTimeout() { return timeout; }
}
