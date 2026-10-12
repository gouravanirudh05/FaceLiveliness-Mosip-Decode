package io.mosip.extensions.liveness.client;

import java.time.Duration;
import java.util.Objects;

/** Connection and session settings for {@link FaceLivenessClient}. Immutable; use {@link #builder()}. */
public final class LivenessClientConfig {
    private final String host;
    private final int port;
    private final Duration connectTimeout;
    private final Duration sessionTimeout;
    private final int maxFramesPerSecond;
    private final Duration autoRetryDelay;

    private LivenessClientConfig(Builder b) {
        this.host = Objects.requireNonNull(b.host, "host");
        if (b.port <= 0 || b.port > 65535) throw new IllegalArgumentException("port out of range: " + b.port);
        if (b.maxFramesPerSecond <= 0) throw new IllegalArgumentException("maxFramesPerSecond must be > 0");
        this.port = b.port;
        this.connectTimeout = positive(b.connectTimeout, "connectTimeout");
        this.sessionTimeout = positive(b.sessionTimeout, "sessionTimeout");
        this.maxFramesPerSecond = b.maxFramesPerSecond;
        this.autoRetryDelay = b.autoRetryDelay;
        if (autoRetryDelay != null && autoRetryDelay.isNegative())
            throw new IllegalArgumentException("autoRetryDelay must not be negative");
    }

    private static Duration positive(Duration d, String name) {
        Objects.requireNonNull(d, name);
        if (d.isZero() || d.isNegative()) throw new IllegalArgumentException(name + " must be > 0");
        return d;
    }

    public static Builder builder() { return new Builder(); }

    /** Host of the passive liveness service, which also runs the hybrid sessions. */
    public String getHost() { return host; }
    public int getPort() { return port; }
    /** Deadline for the availability check ({@link FaceLivenessClient#isAvailable()}). */
    public Duration getConnectTimeout() { return connectTimeout; }
    /** Hard limit for one hybrid session, from start to decision. */
    public Duration getSessionTimeout() { return sessionTimeout; }
    /** Frames above this rate are dropped before they are sent. */
    public int getMaxFramesPerSecond() { return maxFramesPerSecond; }
    /** Delay before a retry offered by the server is accepted automatically; {@code null} = never automatically. */
    public Duration getAutoRetryDelay() { return autoRetryDelay; }

    public static final class Builder {
        private String host = "127.0.0.1";
        private int port = 50052;
        private Duration connectTimeout = Duration.ofSeconds(3);
        private Duration sessionTimeout = Duration.ofSeconds(180);
        private int maxFramesPerSecond = 15;
        private Duration autoRetryDelay = Duration.ofSeconds(3);

        public Builder host(String host) { this.host = host; return this; }
        public Builder port(int port) { this.port = port; return this; }
        public Builder connectTimeout(Duration d) { this.connectTimeout = d; return this; }
        public Builder sessionTimeout(Duration d) { this.sessionTimeout = d; return this; }
        public Builder maxFramesPerSecond(int fps) { this.maxFramesPerSecond = fps; return this; }
        public Builder autoRetryDelay(Duration d) { this.autoRetryDelay = d; return this; }
        public LivenessClientConfig build() { return new LivenessClientConfig(this); }
    }
}
