package io.mosip.extensions.liveness.client;

import io.grpc.ManagedChannel;
import io.grpc.StatusRuntimeException;
import io.grpc.okhttp.OkHttpChannelBuilder;
import io.mosip.extensions.liveness.api.LivenessWorkflow;
import io.mosip.extensions.liveness.passive.grpc.GetInfoRequest;
import io.mosip.extensions.liveness.passive.grpc.PassiveLivenessServiceGrpc;
import java.util.Objects;
import java.util.concurrent.TimeUnit;
import java.util.function.Consumer;

/**
 * Entry point: one gRPC channel to the local liveness service, shared by all sessions. Thread-safe.
 * The service runs on the same machine (offline operation), so the channel is plaintext.
 */
public final class FaceLivenessClient implements AutoCloseable {

    private final LivenessClientConfig config;
    private final ManagedChannel channel;
    private final boolean ownsChannel;

    public FaceLivenessClient(LivenessClientConfig config) {
        this(config, OkHttpChannelBuilder.forAddress(config.getHost(), config.getPort())
                .usePlaintext()
                .maxInboundMessageSize(64 * 1024 * 1024)
                .build(), true);
    }

    /** For tests: use an existing channel (not closed by {@link #close()}). */
    public FaceLivenessClient(LivenessClientConfig config, ManagedChannel channel) {
        this(config, channel, false);
    }

    private FaceLivenessClient(LivenessClientConfig config, ManagedChannel channel, boolean ownsChannel) {
        this.config = Objects.requireNonNull(config, "config");
        this.channel = Objects.requireNonNull(channel, "channel");
        this.ownsChannel = ownsChannel;
    }

    public LivenessClientConfig getConfig() { return config; }

    /** True if the service answers {@code GetInfo} within the connect timeout. */
    public boolean isAvailable() {
        try {
            PassiveLivenessServiceGrpc.newBlockingStub(channel)
                    .withDeadlineAfter(config.getConnectTimeout().toMillis(), TimeUnit.MILLISECONDS)
                    .getInfo(GetInfoRequest.getDefaultInstance());
            return true;
        } catch (StatusRuntimeException e) {
            return false;
        }
    }

    /** The service's models, thresholds and configuration as JSON (diagnostics). */
    public String getServiceInfoJson() {
        return PassiveLivenessServiceGrpc.newBlockingStub(channel)
                .withDeadlineAfter(config.getConnectTimeout().toMillis(), TimeUnit.MILLISECONDS)
                .getInfo(GetInfoRequest.getDefaultInstance()).getJson();
    }

    /** Starts a hybrid session (passive check, then active challenges when the passive score is insufficient). */
    public HybridLivenessSession startHybrid(LivenessWorkflow workflow, Consumer<LivenessUpdate> listener) {
        return startHybrid(workflow, LivenessPolicy.defaults(), listener);
    }

    /** As {@link #startHybrid(LivenessWorkflow, Consumer)}, with a per-session policy (e.g. from client config). */
    public HybridLivenessSession startHybrid(LivenessWorkflow workflow, LivenessPolicy policy,
                                             Consumer<LivenessUpdate> listener) {
        return new HybridLivenessSession(PassiveLivenessServiceGrpc.newStub(channel), config, workflow, policy,
                listener);
    }

    @Override
    public void close() {
        if (!ownsChannel) return;
        channel.shutdown();
        try {
            if (!channel.awaitTermination(2, TimeUnit.SECONDS)) channel.shutdownNow();
        } catch (InterruptedException e) {
            channel.shutdownNow();
            Thread.currentThread().interrupt();
        }
    }
}
