package io.mosip.extensions.liveness.mds;

import io.mosip.extensions.liveness.api.FaceFrame;

/**
 * Device-vendor boundary. Implement this using the selected L0/L1 device SDK.
 * The MDS endpoint can stream the same JPEG data to MOSIP and liveness-core.
 */
public interface DeviceFrameSource {
    void start(FrameConsumer consumer) throws DeviceAdapterException;
    void stop();

    interface FrameConsumer {
        void onFrame(FaceFrame frame);
        void onDeviceError(Exception error);
    }
}
