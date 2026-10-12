package io.mosip.extensions.liveness.client;

import com.google.protobuf.ByteString;
import io.grpc.Status;
import io.grpc.stub.ClientCallStreamObserver;
import io.grpc.stub.ClientResponseObserver;
import io.mosip.extensions.liveness.active.grpc.Cancel;
import io.mosip.extensions.liveness.active.grpc.ChallengePrompt;
import io.mosip.extensions.liveness.active.grpc.Feedback;
import io.mosip.extensions.liveness.active.grpc.Frame;
import io.mosip.extensions.liveness.active.grpc.FrameEncoding;
import io.mosip.extensions.liveness.active.grpc.Retry;
import io.mosip.extensions.liveness.active.grpc.RetryAvailable;
import io.mosip.extensions.liveness.active.grpc.ServerMessage;
import io.mosip.extensions.liveness.active.grpc.Workflow;
import io.mosip.extensions.liveness.api.LivenessWorkflow;
import io.mosip.extensions.liveness.passive.grpc.HybridClientMessage;
import io.mosip.extensions.liveness.passive.grpc.HybridDecision;
import io.mosip.extensions.liveness.passive.grpc.HybridReason;
import io.mosip.extensions.liveness.passive.grpc.HybridServerMessage;
import io.mosip.extensions.liveness.passive.grpc.HybridStart;
import io.mosip.extensions.liveness.passive.grpc.HybridStatus;
import io.mosip.extensions.liveness.passive.grpc.NonResponseReason;
import io.mosip.extensions.liveness.passive.grpc.PassiveLivenessServiceGrpc;
import io.mosip.extensions.liveness.passive.grpc.PassiveProgress;
import io.mosip.extensions.liveness.passive.grpc.SessionPolicy;
import java.time.Duration;
import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Objects;
import java.util.Set;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.ScheduledThreadPoolExecutor;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.function.Consumer;
import java.util.logging.Level;
import java.util.logging.Logger;

/**
 * One hybrid (passive first, active when needed) liveness session over the {@code HybridSession} RPC.
 *
 * <p>Feed it the device's JPEG frames with {@link #offerFrame(byte[])} from any thread (the call never
 * blocks; frames are dropped above the configured rate or while the transport is busy) and wait for the
 * result with {@link #awaitOutcome(Duration)}. Progress for the UI arrives on the listener, on a gRPC
 * thread. Retries offered by the server are accepted automatically after
 * {@link LivenessClientConfig#getAutoRetryDelay()}, or explicitly with {@link #retry()}.
 */
public final class HybridLivenessSession implements AutoCloseable {

    private static final Logger LOG = Logger.getLogger(HybridLivenessSession.class.getName());
    static final String CHECKING_TEXT = "Checking face liveness…";

    private final LivenessClientConfig config;
    private final Consumer<LivenessUpdate> listener;
    private final ScheduledExecutorService sender;
    private final CompletableFuture<LivenessOutcome> outcome = new CompletableFuture<>();
    private final AtomicBoolean framePending = new AtomicBoolean();
    private final AtomicBoolean cancelRequested = new AtomicBoolean();
    private final long minFrameIntervalNanos;

    private volatile ClientCallStreamObserver<HybridClientMessage> requests;
    private volatile String sessionId = "";
    private volatile Float passiveScore;
    private volatile boolean retryOffered;
    private volatile String effectivePolicyJson = "";
    private volatile String lastServerError;
    private long lastFrameNanos;
    private long lastTimestampMs;

    HybridLivenessSession(PassiveLivenessServiceGrpc.PassiveLivenessServiceStub stub, LivenessClientConfig config,
                          LivenessWorkflow workflow, LivenessPolicy policy, Consumer<LivenessUpdate> listener) {
        this.config = Objects.requireNonNull(config, "config");
        this.listener = listener == null ? u -> { } : listener;
        this.minFrameIntervalNanos = TimeUnit.SECONDS.toNanos(1) / config.getMaxFramesPerSecond();
        ScheduledThreadPoolExecutor executor = new ScheduledThreadPoolExecutor(1, r -> {
            Thread t = new Thread(r, "liveness-session-sender");
            t.setDaemon(true);
            return t;
        });
        // Pending timers (session timeout, auto retry) must not outlive the session.
        executor.setExecuteExistingDelayedTasksAfterShutdownPolicy(false);
        this.sender = executor;
        outcome.whenComplete((o, e) -> finish());

        // Order matters: the call can fail (e.g. engine unreachable) and finish the session at once, so the
        // first update and the session timer come before the call is opened.
        emit(new LivenessUpdate(LivenessUpdate.Kind.CHECKING, CHECKING_TEXT, 0, null, 0, -1));
        sender.schedule(() -> complete(LivenessOutcome.Status.TIMED_OUT, "SESSION_TIMEOUT", null, false),
                config.getSessionTimeout().toMillis(), TimeUnit.MILLISECONDS);
        stub.hybridSession(new ResponseObserver());
        HybridStart.Builder start = HybridStart.newBuilder().setWorkflow(toProto(workflow));
        if (policy != null && !policy.equals(LivenessPolicy.defaults())) {
            start.setPolicy(toProto(policy));
        }
        send(HybridClientMessage.newBuilder().setStart(start).build());
    }

    static Workflow toProto(LivenessWorkflow workflow) {
        switch (Objects.requireNonNull(workflow, "workflow")) {
            case RESIDENT_REGISTRATION: return Workflow.WORKFLOW_RESIDENT;
            case OPERATOR_AUTHENTICATION: return Workflow.WORKFLOW_OPERATOR;
            case SUPERVISOR_AUTHENTICATION: return Workflow.WORKFLOW_SUPERVISOR;
            default: throw new IllegalArgumentException("unknown workflow " + workflow);
        }
    }

    static SessionPolicy toProto(LivenessPolicy p) {
        SessionPolicy.Builder b = SessionPolicy.newBuilder();
        if (p.getAcceptThreshold() != null) b.setAcceptThreshold(p.getAcceptThreshold());
        if (p.getRejectThreshold() != null) b.setRejectThreshold(p.getRejectThreshold());
        if (p.getFailOnPassiveNoResponse() != null) b.setFailOnPassiveNoResponse(p.getFailOnPassiveNoResponse());
        if (p.getActiveEnabled() != null) b.setActiveEnabled(p.getActiveEnabled());
        if (p.getMinChallenges() != null) b.setMinChallenges(p.getMinChallenges());
        b.addAllChallengePool(p.getChallengeTypes());
        if (p.getCompoundChallenges() != null) b.setCompoundChallenges(p.getCompoundChallenges());
        if (p.getMaxRetries() != null) b.setMaxRetries(p.getMaxRetries());
        b.addAllStepTimeoutS(p.getStepTimeoutsSeconds());
        return b.build();
    }

    /** The policy the service runs this session with (JSON, available once started); for audit. */
    public String getEffectivePolicyJson() { return effectivePolicyJson; }

    /**
     * Offers one encoded JPEG frame. Returns {@code true} if it was queued for sending; {@code false} if it
     * was dropped (rate limit, transport busy, or the session is over). Never blocks.
     */
    public boolean offerFrame(byte[] jpeg) {
        if (jpeg == null || jpeg.length == 0 || outcome.isDone() || cancelRequested.get()) return false;
        ClientCallStreamObserver<HybridClientMessage> call = requests;
        if (call == null || !call.isReady()) return false;
        long now = System.nanoTime();
        synchronized (this) {
            if (lastFrameNanos != 0 && now - lastFrameNanos < minFrameIntervalNanos) return false;
            if (!framePending.compareAndSet(false, true)) return false;
            lastFrameNanos = now;
        }
        byte[] copy = jpeg.clone();
        try {
            sender.execute(() -> {
                try {
                    if (outcome.isDone()) return;
                    long ts = Math.max(System.currentTimeMillis(), lastTimestampMs + 1);
                    lastTimestampMs = ts;
                    sendNow(HybridClientMessage.newBuilder().setFrame(Frame.newBuilder()
                            .setData(ByteString.copyFrom(copy))
                            .setEncoding(FrameEncoding.FRAME_ENCODING_JPEG)
                            .setTimestampMs(ts)).build());
                } finally {
                    framePending.set(false);
                }
            });
            return true;
        } catch (java.util.concurrent.RejectedExecutionException e) {
            framePending.set(false);
            return false;
        }
    }

    /** Accepts a retry the server offered. Does nothing if none is pending. */
    public void retry() {
        if (!retryOffered || outcome.isDone()) return;
        retryOffered = false;
        send(HybridClientMessage.newBuilder().setRetry(Retry.getDefaultInstance()).build());
    }

    /** Asks the server to cancel; the outcome becomes CANCELLED unless a decision already arrived. */
    public void cancel() {
        if (outcome.isDone() || !cancelRequested.compareAndSet(false, true)) return;
        send(HybridClientMessage.newBuilder().setCancel(Cancel.getDefaultInstance()).build());
        // The server answers a Cancel with a CANCELLED decision; do not wait for it forever.
        try {
            sender.schedule(() -> complete(LivenessOutcome.Status.CANCELLED, "CANCELLED", null, false),
                    2, TimeUnit.SECONDS);
        } catch (java.util.concurrent.RejectedExecutionException ignored) {
            complete(LivenessOutcome.Status.CANCELLED, "CANCELLED", null, false);
        }
    }

    public boolean isDone() { return outcome.isDone(); }

    public String getSessionId() { return sessionId; }

    /**
     * Waits for the decision. On timeout the session is cancelled and a {@code TIMED_OUT} outcome is returned.
     */
    public LivenessOutcome awaitOutcome(Duration timeout) throws InterruptedException {
        try {
            return outcome.get(timeout.toMillis(), TimeUnit.MILLISECONDS);
        } catch (TimeoutException e) {
            complete(LivenessOutcome.Status.TIMED_OUT, "AWAIT_TIMEOUT", null, false);
            return outcome.getNow(null);
        } catch (ExecutionException e) {
            throw new IllegalStateException("liveness outcome failed", e.getCause());
        }
    }

    /** The outcome future, for callers that prefer asynchronous handling. */
    public CompletableFuture<LivenessOutcome> outcome() { return outcome; }

    @Override
    public void close() {
        if (!outcome.isDone()) {
            cancel();
            complete(LivenessOutcome.Status.CANCELLED, "CLOSED", null, false);
        }
    }

    // ------------------------------------------------------------------ internals

    private void send(HybridClientMessage message) {
        try {
            sender.execute(() -> sendNow(message));
        } catch (java.util.concurrent.RejectedExecutionException ignored) {
            // session already finished
        }
    }

    /** Must run on the sender thread: StreamObserver is not thread-safe. */
    private void sendNow(HybridClientMessage message) {
        ClientCallStreamObserver<HybridClientMessage> call = requests;
        if (call == null || outcome.isDone()) return;
        try {
            call.onNext(message);
        } catch (RuntimeException e) {
            LOG.log(Level.WARNING, "liveness: send failed", e);
            complete(LivenessOutcome.Status.ENGINE_ERROR, "SEND_FAILED: " + e.getMessage(), null, false);
        }
    }

    private void complete(LivenessOutcome.Status status, String reason, String message, boolean attack) {
        outcome.complete(new LivenessOutcome(status, reason, message, passiveScore, sessionId, attack));
    }

    private void finish() {
        LivenessOutcome o = outcome.getNow(null);
        emit(new LivenessUpdate(LivenessUpdate.Kind.DONE, o == null ? "" : o.getUserMessage(),
                o != null && o.isPassed() ? 1 : 0, null, 0, -1));
        try {
            sender.execute(() -> {
                ClientCallStreamObserver<HybridClientMessage> call = requests;
                if (call == null) return;
                try {
                    if (o != null && o.getStatus() == LivenessOutcome.Status.PASSED
                            || o != null && o.getStatus() == LivenessOutcome.Status.FAILED) {
                        call.onCompleted();
                    } else {
                        call.cancel("liveness session ended: " + (o == null ? "?" : o.getStatus()), null);
                    }
                } catch (RuntimeException ignored) {
                    // call already closed
                }
            });
        } catch (java.util.concurrent.RejectedExecutionException ignored) {
            // already shut down
        }
        sender.shutdown();
    }

    private void emit(LivenessUpdate update) {
        try {
            listener.accept(update);
        } catch (RuntimeException e) {
            LOG.log(Level.WARNING, "liveness: listener failed", e);
        }
    }

    private void onServerMessage(HybridServerMessage m) {
        switch (m.getPayloadCase()) {
            case STARTED:
                sessionId = m.getStarted().getSessionId();
                effectivePolicyJson = m.getStarted().getPolicyJson();
                break;
            case PASSIVE_PROGRESS: {
                PassiveProgress p = m.getPassiveProgress();
                double progress = p.getFramesRequired() > 0 ? (double) p.getFramesUsed() / p.getFramesRequired() : 0;
                List<String> hints = p.getQuality().getPassed() ? null : guidance(p.getQuality().getReasonsList());
                emit(new LivenessUpdate(LivenessUpdate.Kind.CHECKING, CHECKING_TEXT, progress, hints, 0, -1));
                break;
            }
            case PASSIVE_VERDICT:
                if (m.getPassiveVerdict().getResult().hasBonafideProbability())
                    passiveScore = m.getPassiveVerdict().getResult().getBonafideProbability();
                break;
            case ACTIVE:
                onActive(m.getActive());
                break;
            case MONITOR:
                break; // diagnostics only
            case DECISION:
                onDecision(m.getDecision());
                break;
            case ERROR:
                lastServerError = m.getError().getCode() + ": " + m.getError().getMessage();
                LOG.warning("liveness: server error " + lastServerError);
                break;
            default:
                break;
        }
    }

    private void onActive(ServerMessage a) {
        switch (a.getPayloadCase()) {
            case CHALLENGE_PROMPT: {
                ChallengePrompt p = a.getChallengePrompt();
                emit(new LivenessUpdate(LivenessUpdate.Kind.CHALLENGE, p.getPrompt(), 0, null, p.getTimeoutMs(), -1)
                        .withSteps(p.getStepIndex() + 1, p.getTotalSteps(), p.getAttempt()));
                break;
            }
            case FEEDBACK: {
                Feedback f = a.getFeedback();
                emit(new LivenessUpdate(LivenessUpdate.Kind.FEEDBACK, f.getMessage(), f.getProgress(), null, 0, -1));
                break;
            }
            case CHALLENGE_RESULT:
                emit(new LivenessUpdate(LivenessUpdate.Kind.CHALLENGE_RESULT,
                        a.getChallengeResult().getPassed() ? "Action detected" : a.getChallengeResult().getReason().name(),
                        a.getChallengeResult().getPassed() ? 1 : 0, null, 0, -1, a.getChallengeResult().getPassed()));
                break;
            case RETRY_AVAILABLE: {
                RetryAvailable r = a.getRetryAvailable();
                retryOffered = true;
                emit(new LivenessUpdate(LivenessUpdate.Kind.RETRY, r.getMessage(), 0,
                        new ArrayList<>(r.getGuidanceList()), 0, r.getRetriesRemaining()));
                Duration delay = config.getAutoRetryDelay();
                if (delay != null) {
                    try {
                        sender.schedule(this::retry, delay.toMillis(), TimeUnit.MILLISECONDS);
                    } catch (java.util.concurrent.RejectedExecutionException ignored) {
                        // finished meanwhile
                    }
                }
                break;
            }
            case ERROR:
                LOG.fine("liveness: active error " + a.getError().getCode() + " " + a.getError().getMessage());
                break;
            default:
                break; // session_started, active decision: the hybrid decision follows
        }
    }

    private void onDecision(HybridDecision d) {
        if (d.hasPassiveScore()) passiveScore = d.getPassiveScore();
        boolean attack = d.getReason() == HybridReason.HYBRID_REASON_ATTACK_DETECTED
                || d.getReason() == HybridReason.HYBRID_REASON_ATTACK_DETECTED_DURING_ACTIVE;
        LivenessOutcome.Status status;
        if (d.getStatus() == HybridStatus.HYBRID_PASSED) status = LivenessOutcome.Status.PASSED;
        else if (d.getStatus() == HybridStatus.HYBRID_CANCELLED) status = LivenessOutcome.Status.CANCELLED;
        else status = LivenessOutcome.Status.FAILED;
        complete(status, d.getReason().name(), d.getMessage(), attack);
    }

    /** Positioning hints from spec 10.5 for the passive quality reasons. */
    static List<String> guidance(List<NonResponseReason> reasons) {
        Set<String> out = new LinkedHashSet<>();
        for (NonResponseReason r : reasons) {
            switch (r) {
                case NON_RESPONSE_NO_FACE:
                case NON_RESPONSE_FACE_CUT_OFF:
                    out.add("Keep your face within the capture area.");
                    break;
                case NON_RESPONSE_FACE_TOO_SMALL:
                    out.add("Move closer to the camera.");
                    break;
                case NON_RESPONSE_TOO_DARK:
                case NON_RESPONSE_TOO_BRIGHT:
                    out.add("Improve lighting.");
                    break;
                case NON_RESPONSE_TOO_BLURRY:
                    out.add("Hold still.");
                    break;
                case NON_RESPONSE_POSE_OUT_OF_RANGE:
                    out.add("Look directly at the camera.");
                    break;
                case NON_RESPONSE_MULTIPLE_FACES:
                    out.add("Only one person should be in front of the camera.");
                    break;
                default:
                    out.add("Ensure your face is clearly visible.");
            }
        }
        return new ArrayList<>(out);
    }

    private final class ResponseObserver implements ClientResponseObserver<HybridClientMessage, HybridServerMessage> {
        @Override
        public void beforeStart(ClientCallStreamObserver<HybridClientMessage> call) {
            requests = call;
        }

        @Override
        public void onNext(HybridServerMessage message) {
            try {
                onServerMessage(message);
            } catch (RuntimeException e) {
                LOG.log(Level.WARNING, "liveness: bad server message", e);
            }
        }

        @Override
        public void onError(Throwable t) {
            if (outcome.isDone()) return;
            Status s = Status.fromThrowable(t);
            if (cancelRequested.get() && s.getCode() == Status.Code.CANCELLED) {
                complete(LivenessOutcome.Status.CANCELLED, "CANCELLED", null, false);
            } else {
                LOG.warning("liveness: service error " + s.getCode() + " " + s.getDescription());
                complete(LivenessOutcome.Status.ENGINE_ERROR, "GRPC_" + s.getCode(), null, false);
            }
        }

        @Override
        public void onCompleted() {
            String error = lastServerError;
            complete(LivenessOutcome.Status.ENGINE_ERROR,
                    error == null ? "STREAM_ENDED_WITHOUT_DECISION" : "SERVER_ERROR " + error, null, false);
        }
    }
}
