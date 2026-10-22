package io.mosip.registration.controller.device;

import io.mosip.registration.audit.AuditManagerService;

/**
 * Builds the Registration Client's own {@link FaceLivenessGuard} outside Spring, the same way its tests do. Lives
 * in the guard's package because that constructor is package-private; the client code is used unchanged.
 */
public final class DemoGuardFactory {

	private DemoGuardFactory() {
	}

	public static FaceLivenessGuard create(Streamer streamer, AuditManagerService audit) {
		return new FaceLivenessGuard(streamer, audit);
	}
}
