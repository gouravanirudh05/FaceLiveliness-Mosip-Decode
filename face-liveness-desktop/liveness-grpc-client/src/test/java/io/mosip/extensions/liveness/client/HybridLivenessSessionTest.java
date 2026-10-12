package io.mosip.extensions.liveness.client;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import io.grpc.ManagedChannel;
import io.grpc.Server;
import io.grpc.inprocess.InProcessChannelBuilder;
import io.grpc.inprocess.InProcessServerBuilder;
import io.grpc.stub.StreamObserver;
import io.mosip.extensions.liveness.active.grpc.ChallengePrompt;
import io.mosip.extensions.liveness.active.grpc.FrameEncoding;
import io.mosip.extensions.liveness.active.grpc.RetryAvailable;
import io.mosip.extensions.liveness.active.grpc.ServerMessage;
import io.mosip.extensions.liveness.active.grpc.Workflow;
import io.mosip.extensions.liveness.api.LivenessWorkflow;
import io.mosip.extensions.liveness.passive.grpc.GetInfoRequest;
import io.mosip.extensions.liveness.passive.grpc.HybridClientMessage;
import io.mosip.extensions.liveness.passive.grpc.HybridDecision;
import io.mosip.extensions.liveness.passive.grpc.HybridReason;
import io.mosip.extensions.liveness.passive.grpc.HybridServerMessage;
import io.mosip.extensions.liveness.passive.grpc.HybridStarted;
import io.mosip.extensions.liveness.passive.grpc.HybridStatus;
import io.mosip.extensions.liveness.passive.grpc.NextStep;
import io.mosip.extensions.liveness.passive.grpc.NonResponseReason;
import io.mosip.extensions.liveness.passive.grpc.PassiveLivenessServiceGrpc;
import io.mosip.extensions.liveness.passive.grpc.PassiveProgress;
import io.mosip.extensions.liveness.passive.grpc.PassiveVerdict;
import io.mosip.extensions.liveness.passive.grpc.Quality;
import io.mosip.extensions.liveness.passive.grpc.ServiceInfo;
import io.mosip.extensions.liveness.passive.grpc.StreamResult;
import java.time.Duration;
import java.util.Arrays;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.function.BiConsumer;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;

/** Protocol tests against an in-process fake of the passive service's HybridSession RPC. */
class HybridLivenessSessionTest {

    private static final byte[] JPEG = {(byte) 0xFF, (byte) 0xD8, 1, 2, 3, (byte) 0xFF, (byte) 0xD9};

    /** Scripted fake: the handler sees every client message and may answer through the observer. */
    private static final class FakeService extends PassiveLivenessServiceGrpc.PassiveLivenessServiceImplBase {
        final List<HybridClientMessage> received = new CopyOnWriteArrayList<>();
        final CountDownLatch closed = new CountDownLatch(1);
        volatile boolean cancelledByClient;
        BiConsumer<HybridClientMessage, StreamObserver<HybridServerMessage>> handler = (m, o) -> { };

        @Override
        public StreamObserver<HybridClientMessage> hybridSession(StreamObserver<HybridServerMessage> out) {
            return new StreamObserver<HybridClientMessage>() {
                @Override public void onNext(HybridClientMessage m) { received.add(m); handler.accept(m, out); }
                @Override public void onError(Throwable t) { cancelledByClient = true; closed.countDown(); }
                @Override public void onCompleted() { closed.countDown(); }
            };
        }

        @Override
        public void getInfo(GetInfoRequest request, StreamObserver<ServiceInfo> out) {
            out.onNext(ServiceInfo.newBuilder().setJson("{\"ok\":true}").build());
            out.onCompleted();
        }

        long count(HybridClientMessage.PayloadCase kind) {
            return received.stream().filter(m -> m.getPayloadCase() == kind).count();
        }
    }

    private final FakeService fake = new FakeService();
    private Server server;
    private ManagedChannel channel;

    private FaceLivenessClient client(LivenessClientConfig.Builder config) throws Exception {
        String name = UUID.randomUUID().toString();
        server = InProcessServerBuilder.forName(name).directExecutor().addService(fake).build().start();
        channel = InProcessChannelBuilder.forName(name).directExecutor().build();
        return new FaceLivenessClient(config.build(), channel);
    }

    @AfterEach
    void tearDown() {
        if (channel != null) channel.shutdownNow();
        if (server != null) server.shutdownNow();
    }

    private static HybridServerMessage decision(HybridStatus status, HybridReason reason, String message, float score) {
        return HybridServerMessage.newBuilder().setDecision(HybridDecision.newBuilder()
                .setStatus(status).setReason(reason).setMessage(message).setPassiveScore(score)).build();
    }

    private static HybridServerMessage active(ServerMessage m) {
        return HybridServerMessage.newBuilder().setActive(m).build();
    }

    @Test
    void passivePassAcceptsAndSendsStartWithWorkflow() throws Exception {
        fake.handler = (m, out) -> {
            if (m.hasStart()) {
                out.onNext(HybridServerMessage.newBuilder().setStarted(HybridStarted.newBuilder()
                        .setSessionId("s-1").setWorkflow(m.getStart().getWorkflow()).setFramesRequired(2)).build());
            } else if (m.hasFrame() && fake.count(HybridClientMessage.PayloadCase.FRAME) == 2) {
                out.onNext(HybridServerMessage.newBuilder().setPassiveVerdict(PassiveVerdict.newBuilder()
                        .setResult(StreamResult.newBuilder().setBonafideProbability(0.91f))
                        .setNextStep(NextStep.NEXT_STEP_ACCEPT)).build());
                out.onNext(decision(HybridStatus.HYBRID_PASSED, HybridReason.HYBRID_REASON_PASSIVE_BONAFIDE,
                        "Face liveness verified.", 0.91f));
                // the call stays open here, so the test can observe the client's half-close
            }
        };
        List<LivenessUpdate> updates = new CopyOnWriteArrayList<>();
        try (FaceLivenessClient c = client(LivenessClientConfig.builder().maxFramesPerSecond(1000));
             HybridLivenessSession s = c.startHybrid(LivenessWorkflow.OPERATOR_AUTHENTICATION, updates::add)) {
            for (int i = 0; i < 50 && !s.isDone(); i++) {
                s.offerFrame(JPEG);
                Thread.sleep(5);
            }
            LivenessOutcome o = s.awaitOutcome(Duration.ofSeconds(5));
            assertEquals(LivenessOutcome.Status.PASSED, o.getStatus());
            assertEquals(0.91f, o.getPassiveScore().orElse(-1f), 1e-6);
            assertEquals("s-1", o.getSessionId());
            assertEquals("HYBRID_REASON_PASSIVE_BONAFIDE", o.getReason());
            assertFalse(o.isAttackDetected());
        }
        assertEquals(Workflow.WORKFLOW_OPERATOR, fake.received.get(0).getStart().getWorkflow());
        assertEquals(LivenessUpdate.Kind.CHECKING, updates.get(0).getKind());
        assertEquals(LivenessUpdate.Kind.DONE, updates.get(updates.size() - 1).getKind());
        assertTrue(fake.closed.await(2, TimeUnit.SECONDS), "client half-closes after the decision");
    }

    @Test
    void framesAreJpegWithStrictlyIncreasingTimestampsAndRateLimited() throws Exception {
        try (FaceLivenessClient c = client(LivenessClientConfig.builder().maxFramesPerSecond(5));
             HybridLivenessSession s = c.startHybrid(LivenessWorkflow.RESIDENT_REGISTRATION, null)) {
            long accepted = 0;
            long end = System.nanoTime() + TimeUnit.MILLISECONDS.toNanos(1000);
            while (System.nanoTime() < end) {
                if (s.offerFrame(JPEG)) accepted++;
                Thread.sleep(2);
            }
            Thread.sleep(100);
            long sent = fake.count(HybridClientMessage.PayloadCase.FRAME);
            assertEquals(accepted, sent);
            assertTrue(sent >= 4 && sent <= 6, "about 5 frames in 1 s at 5 fps, got " + sent);
            long last = -1;
            for (HybridClientMessage m : fake.received) {
                if (!m.hasFrame()) continue;
                assertEquals(FrameEncoding.FRAME_ENCODING_JPEG, m.getFrame().getEncoding());
                assertTrue(Arrays.equals(JPEG, m.getFrame().getData().toByteArray()));
                assertTrue(m.getFrame().getTimestampMs() > last);
                last = m.getFrame().getTimestampMs();
            }
        }
    }

    @Test
    void activeFlowRelaysPromptsAutoRetriesAndReportsAttackOnlyForAudit() throws Exception {
        fake.handler = (m, out) -> {
            if (m.hasStart()) {
                out.onNext(active(ServerMessage.newBuilder().setChallengePrompt(ChallengePrompt.newBuilder()
                        .setPrompt("Please blink").setTimeoutMs(8000)).build()));
                out.onNext(active(ServerMessage.newBuilder().setRetryAvailable(RetryAvailable.newBuilder()
                        .setMessage("We could not verify face liveness. Please try again.")
                        .addGuidance("Follow the prompted action.").setRetriesRemaining(2)).build()));
            } else if (m.hasRetry()) {
                out.onNext(decision(HybridStatus.HYBRID_FAILED,
                        HybridReason.HYBRID_REASON_ATTACK_DETECTED_DURING_ACTIVE,
                        "Face verification could not be completed. Please try again.", 0.55f));
                out.onCompleted();
            }
        };
        List<LivenessUpdate> updates = new CopyOnWriteArrayList<>();
        try (FaceLivenessClient c = client(LivenessClientConfig.builder().autoRetryDelay(Duration.ofMillis(50)));
             HybridLivenessSession s = c.startHybrid(LivenessWorkflow.SUPERVISOR_AUTHENTICATION, updates::add)) {
            LivenessOutcome o = s.awaitOutcome(Duration.ofSeconds(5));
            assertEquals(LivenessOutcome.Status.FAILED, o.getStatus());
            assertTrue(o.isAttackDetected());
            assertFalse(o.getUserMessage().toLowerCase().contains("attack"), "UI text must not expose PAD details");
        }
        assertEquals(1, fake.count(HybridClientMessage.PayloadCase.RETRY));
        LivenessUpdate challenge = updates.stream().filter(u -> u.getKind() == LivenessUpdate.Kind.CHALLENGE)
                .findFirst().orElseThrow(AssertionError::new);
        assertEquals("Please blink", challenge.getText());
        assertEquals(8000, challenge.getTimeoutMs());
        LivenessUpdate retry = updates.stream().filter(u -> u.getKind() == LivenessUpdate.Kind.RETRY)
                .findFirst().orElseThrow(AssertionError::new);
        assertEquals(2, retry.getRetriesRemaining());
        assertEquals(List.of("Follow the prompted action."), retry.getGuidance());
    }

    @Test
    void manualRetryWhenAutoRetryIsOff() throws Exception {
        CountDownLatch offered = new CountDownLatch(1);
        fake.handler = (m, out) -> {
            if (m.hasStart()) {
                out.onNext(active(ServerMessage.newBuilder().setRetryAvailable(RetryAvailable.newBuilder()
                        .setMessage("again").setRetriesRemaining(1)).build()));
            } else if (m.hasRetry()) {
                out.onNext(decision(HybridStatus.HYBRID_PASSED, HybridReason.HYBRID_REASON_ACTIVE_PASSED, "", 0.6f));
                out.onCompleted();
            }
        };
        try (FaceLivenessClient c = client(LivenessClientConfig.builder().autoRetryDelay(null));
             HybridLivenessSession s = c.startHybrid(LivenessWorkflow.RESIDENT_REGISTRATION, u -> {
                 if (u.getKind() == LivenessUpdate.Kind.RETRY) offered.countDown();
             })) {
            assertTrue(offered.await(2, TimeUnit.SECONDS));
            Thread.sleep(200);
            assertEquals(0, fake.count(HybridClientMessage.PayloadCase.RETRY), "no automatic retry");
            s.retry();
            assertEquals(LivenessOutcome.Status.PASSED, s.awaitOutcome(Duration.ofSeconds(5)).getStatus());
        }
    }

    @Test
    void cancelSendsCancelAndEndsCancelled() throws Exception {
        fake.handler = (m, out) -> {
            if (m.hasCancel()) {
                out.onNext(decision(HybridStatus.HYBRID_CANCELLED, HybridReason.HYBRID_REASON_CANCELLED, "", 0f));
                out.onCompleted();
            }
        };
        try (FaceLivenessClient c = client(LivenessClientConfig.builder());
             HybridLivenessSession s = c.startHybrid(LivenessWorkflow.RESIDENT_REGISTRATION, null)) {
            s.cancel();
            assertEquals(LivenessOutcome.Status.CANCELLED, s.awaitOutcome(Duration.ofSeconds(5)).getStatus());
            assertFalse(s.offerFrame(JPEG), "no frames after the session ended");
        }
        assertEquals(1, fake.count(HybridClientMessage.PayloadCase.CANCEL));
    }

    @Test
    void sessionTimeoutEndsTimedOutAndClosesTheCall() throws Exception {
        try (FaceLivenessClient c = client(LivenessClientConfig.builder().sessionTimeout(Duration.ofMillis(300)));
             HybridLivenessSession s = c.startHybrid(LivenessWorkflow.RESIDENT_REGISTRATION, null)) {
            LivenessOutcome o = s.awaitOutcome(Duration.ofSeconds(5));
            assertEquals(LivenessOutcome.Status.TIMED_OUT, o.getStatus());
            assertEquals(LivenessOutcome.GENERIC_FAILURE_MESSAGE, o.getUserMessage());
        }
        assertTrue(fake.closed.await(2, TimeUnit.SECONDS));
        assertTrue(fake.cancelledByClient);
    }

    @Test
    void streamEndingWithoutDecisionIsAnEngineError() throws Exception {
        fake.handler = (m, out) -> { if (m.hasStart()) out.onCompleted(); };
        try (FaceLivenessClient c = client(LivenessClientConfig.builder());
             HybridLivenessSession s = c.startHybrid(LivenessWorkflow.RESIDENT_REGISTRATION, null)) {
            LivenessOutcome o = s.awaitOutcome(Duration.ofSeconds(5));
            assertEquals(LivenessOutcome.Status.ENGINE_ERROR, o.getStatus());
            assertFalse(o.isPassed());
        }
    }

    @Test
    void unreachableServiceIsAnEngineErrorAndNotAvailable() throws Exception {
        LivenessClientConfig config = LivenessClientConfig.builder().host("127.0.0.1").port(1)
                .connectTimeout(Duration.ofMillis(500)).build();
        try (FaceLivenessClient c = new FaceLivenessClient(config);
             HybridLivenessSession s = c.startHybrid(LivenessWorkflow.RESIDENT_REGISTRATION, null)) {
            assertFalse(c.isAvailable());
            LivenessOutcome o = s.awaitOutcome(Duration.ofSeconds(10));
            assertEquals(LivenessOutcome.Status.ENGINE_ERROR, o.getStatus());
            assertTrue(o.getReason().startsWith("GRPC_UNAVAILABLE"), o.getReason());
        }
    }

    @Test
    void availabilityCheckUsesGetInfo() throws Exception {
        try (FaceLivenessClient c = client(LivenessClientConfig.builder())) {
            assertTrue(c.isAvailable());
            assertEquals("{\"ok\":true}", c.getServiceInfoJson());
        }
    }

    @Test
    void passiveQualityReasonsBecomeSpecGuidance() {
        List<String> g = HybridLivenessSession.guidance(Arrays.asList(NonResponseReason.NON_RESPONSE_NO_FACE,
                NonResponseReason.NON_RESPONSE_FACE_CUT_OFF, NonResponseReason.NON_RESPONSE_TOO_DARK));
        assertEquals(List.of("Keep your face within the capture area.", "Improve lighting."), g);
    }

    @Test
    void progressUpdatesCarryQualityGuidance() throws Exception {
        fake.handler = (m, out) -> {
            if (m.hasStart()) {
                out.onNext(HybridServerMessage.newBuilder().setPassiveProgress(PassiveProgress.newBuilder()
                        .setFramesUsed(1).setFramesRequired(4).setQuality(Quality.newBuilder().setPassed(false)
                                .addReasons(NonResponseReason.NON_RESPONSE_FACE_TOO_SMALL))).build());
            }
        };
        List<LivenessUpdate> updates = new CopyOnWriteArrayList<>();
        try (FaceLivenessClient c = client(LivenessClientConfig.builder());
             HybridLivenessSession s = c.startHybrid(LivenessWorkflow.RESIDENT_REGISTRATION, updates::add)) {
            Thread.sleep(200);
            LivenessUpdate u = updates.stream().filter(x -> !x.getGuidance().isEmpty()).findFirst()
                    .orElseThrow(AssertionError::new);
            assertEquals(LivenessUpdate.Kind.CHECKING, u.getKind());
            assertEquals(0.25, u.getProgress(), 1e-9);
            assertEquals(List.of("Move closer to the camera."), u.getGuidance());
        }
    }

    @Test
    void workflowMapping() {
        assertEquals(Workflow.WORKFLOW_RESIDENT, HybridLivenessSession.toProto(LivenessWorkflow.RESIDENT_REGISTRATION));
        assertEquals(Workflow.WORKFLOW_OPERATOR, HybridLivenessSession.toProto(LivenessWorkflow.OPERATOR_AUTHENTICATION));
        assertEquals(Workflow.WORKFLOW_SUPERVISOR,
                HybridLivenessSession.toProto(LivenessWorkflow.SUPERVISOR_AUTHENTICATION));
    }

    @Test
    void policyIsSentWithStartAndDefaultsSendNone() throws Exception {
        LivenessPolicy policy = LivenessPolicy.builder().acceptThreshold(0.9f).rejectThreshold(0.3f)
                .activeEnabled(true).minChallenges(4).challengeTypes(List.of("blink", "smile"))
                .compoundChallenges(false).maxRetries(1).stepTimeoutsSeconds(List.of(10f, 6f))
                .failOnPassiveNoResponse(true).build();
        fake.handler = (m, out) -> {
            if (m.hasStart()) {
                out.onNext(HybridServerMessage.newBuilder().setStarted(HybridStarted.newBuilder()
                        .setSessionId("p").setPolicyJson("{\"accept_threshold\": 0.9}")).build());
            }
        };
        try (FaceLivenessClient c = client(LivenessClientConfig.builder());
             HybridLivenessSession s = c.startHybrid(LivenessWorkflow.RESIDENT_REGISTRATION, policy, null)) {
            Thread.sleep(200);
            assertEquals("{\"accept_threshold\": 0.9}", s.getEffectivePolicyJson());
        }
        io.mosip.extensions.liveness.passive.grpc.SessionPolicy sent = fake.received.get(0).getStart().getPolicy();
        assertTrue(fake.received.get(0).getStart().hasPolicy());
        assertEquals(0.9f, sent.getAcceptThreshold(), 1e-6);
        assertEquals(0.3f, sent.getRejectThreshold(), 1e-6);
        assertTrue(sent.getActiveEnabled() && sent.getFailOnPassiveNoResponse() && !sent.getCompoundChallenges());
        assertEquals(4, sent.getMinChallenges());
        assertEquals(1, sent.getMaxRetries());
        assertEquals(List.of("blink", "smile"), sent.getChallengePoolList());
        assertEquals(List.of(10f, 6f), sent.getStepTimeoutSList());
    }

    @Test
    void defaultPolicyLeavesTheServiceConfigured() throws Exception {
        try (FaceLivenessClient c = client(LivenessClientConfig.builder());
             HybridLivenessSession s = c.startHybrid(LivenessWorkflow.RESIDENT_REGISTRATION, null)) {
            Thread.sleep(100);
        }
        assertFalse(fake.received.get(0).getStart().hasPolicy());
    }

    @Test
    void invalidPoliciesAreRejectedLocally() {
        org.junit.jupiter.api.Assertions.assertThrows(IllegalArgumentException.class,
                () -> LivenessPolicy.builder().acceptThreshold(0.3f).rejectThreshold(0.5f).build());
        org.junit.jupiter.api.Assertions.assertThrows(IllegalArgumentException.class,
                () -> LivenessPolicy.builder().challengeTypes(List.of("jump")).build());
        org.junit.jupiter.api.Assertions.assertThrows(IllegalArgumentException.class,
                () -> LivenessPolicy.builder().minChallenges(0).build());
        org.junit.jupiter.api.Assertions.assertThrows(IllegalArgumentException.class,
                () -> LivenessPolicy.builder().stepTimeoutsSeconds(List.of(0f)).build());
    }

    @Test
    void serverRejectionIsReportedAsEngineErrorWithItsReason() throws Exception {
        fake.handler = (m, out) -> {
            if (m.hasStart()) {
                out.onNext(HybridServerMessage.newBuilder().setError(
                        io.mosip.extensions.liveness.passive.grpc.Error.newBuilder()
                                .setCode(io.mosip.extensions.liveness.passive.grpc.ErrorCode.ERROR_INVALID_REQUEST)
                                .setMessage("invalid policy: x")).build());
                out.onCompleted();
            }
        };
        try (FaceLivenessClient c = client(LivenessClientConfig.builder());
             HybridLivenessSession s = c.startHybrid(LivenessWorkflow.RESIDENT_REGISTRATION, null)) {
            LivenessOutcome o = s.awaitOutcome(Duration.ofSeconds(5));
            assertEquals(LivenessOutcome.Status.ENGINE_ERROR, o.getStatus());
            assertTrue(o.getReason().contains("invalid policy: x"), o.getReason());
        }
    }
}
