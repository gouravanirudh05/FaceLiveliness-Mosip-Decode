package io.mosip.extensions.liveness.api;

import java.time.Instant;
import java.util.Arrays;
import java.util.Objects;

/** A single camera frame supplied by a device adapter. */
public final class FaceFrame {
    private final byte[] jpeg;
    private final Instant capturedAt;

    public FaceFrame(byte[] jpeg, Instant capturedAt) {
        this.jpeg = Arrays.copyOf(Objects.requireNonNull(jpeg, "jpeg"), jpeg.length);
        this.capturedAt = Objects.requireNonNull(capturedAt, "capturedAt");
    }

    public byte[] getJpeg() { return Arrays.copyOf(jpeg, jpeg.length); }
    public Instant getCapturedAt() { return capturedAt; }
}
