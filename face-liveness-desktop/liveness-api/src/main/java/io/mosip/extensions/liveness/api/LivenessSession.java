package io.mosip.extensions.liveness.api;

import java.util.Objects;
import java.util.UUID;

/** Context retained locally for one capture/authentication attempt. */
public final class LivenessSession {
    private final String id;
    private final LivenessWorkflow workflow;

    public LivenessSession(LivenessWorkflow workflow) {
        this(UUID.randomUUID().toString(), workflow);
    }

    public LivenessSession(String id, LivenessWorkflow workflow) {
        this.id = Objects.requireNonNull(id, "id");
        this.workflow = Objects.requireNonNull(workflow, "workflow");
    }

    public String getId() { return id; }
    public LivenessWorkflow getWorkflow() { return workflow; }
}
