package io.mosip.extensions.liveness.mds;

/** Exception raised when the configured camera/device adapter cannot supply frames. */
public class DeviceAdapterException extends Exception {
    public DeviceAdapterException(String message, Throwable cause) {
        super(message, cause);
    }
}
