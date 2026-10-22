package io.mosip.demo;

import java.io.IOException;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.sql.SQLException;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicInteger;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;

import io.mosip.extensions.liveness.api.LivenessWorkflow;
import io.mosip.extensions.liveness.client.LivenessOutcome;
import io.mosip.registration.controller.device.FaceLivenessGuard;

/**
 * What the real client would get from the MOSIP server (users, roles, centre, machine) or upload to it (packets),
 * kept locally: records in the Derby database ({@link DemoDb}), face images as files under the data folder. Users
 * are seeded from {@code demo-users.json} the first time the database is created.
 */
public class DemoStore {

	public static final String ROLE_OFFICER = "REGISTRATION_OFFICER";
	public static final String ROLE_SUPERVISOR = "REGISTRATION_SUPERVISOR";
	public static final String CENTER_ID = "10011";
	public static final String MACHINE_ID = "10002";

	public static final String PENDING = "PENDING_APPROVAL";
	public static final String APPROVED = "APPROVED";
	public static final String REJECTED = "REJECTED";

	/** A registration officer or supervisor (in MOSIP: synced user details). */
	public static final class User {
		public final String id;
		public final String name;
		public final List<String> roles;

		User(DemoDb.UserRow row) {
			this.id = row.id;
			this.name = row.name;
			this.roles = row.roles;
		}

		public boolean isSupervisor() {
			return roles.contains(ROLE_SUPERVISOR);
		}
	}

	/** A record of {@code demo-users.json}; only used to seed the database and for the login hint. */
	public static final class Seed {
		public String id;
		public String name;
		public String password;
		public List<String> roles = new ArrayList<>();
	}

	/** A database failure; shown to the user as an error. */
	public static class StoreException extends RuntimeException {
		private static final long serialVersionUID = 1L;

		StoreException(String message, Throwable cause) {
			super(message + ": " + cause.getMessage(), cause);
		}
	}

	private static final DateTimeFormatter RID_TIME = DateTimeFormatter.ofPattern("yyyyMMddHHmmss");

	private final Path dir;
	private final DemoDb db;
	private final List<Seed> seeds;
	private final AtomicInteger sequence;

	public DemoStore(Path dir, DemoDb db) throws IOException, SQLException {
		this.dir = dir;
		this.db = db;
		Files.createDirectories(dir.resolve("packets"));
		Files.createDirectories(dir.resolve("operators"));
		try (InputStream in = DemoStore.class.getResourceAsStream("/demo-users.json")) {
			seeds = new ObjectMapper().readValue(in, new TypeReference<List<Seed>>() {
			});
		}
		for (Seed s : seeds) {
			db.insertUserIfMissing(s.id, s.name, s.password, s.roles);
		}
		sequence = new AtomicInteger(db.registrationCount());
	}

	public Path getDir() {
		return dir;
	}

	public DemoDb getDb() {
		return db;
	}

	/** The demo users with their seed passwords, for the login screen hint. */
	public List<Seed> seeds() {
		return seeds;
	}

	/** The user when the ID and password match, else null. */
	public User authenticate(String id, String password) {
		try {
			DemoDb.UserRow row = db.authenticate(id == null ? "" : id.trim(), password == null ? "" : password);
			return row == null ? null : new User(row);
		} catch (SQLException e) {
			throw new StoreException("Reading the user failed", e);
		}
	}

	// ------------------------------------------------------------------ operator onboarding

	/** In MOSIP an operator must be onboarded (own biometrics captured on this machine) before biometric login. */
	public boolean isOnboarded(String userId) {
		try {
			DemoDb.UserRow row = db.user(userId);
			return row != null && row.onboarded;
		} catch (SQLException e) {
			throw new StoreException("Reading the user failed", e);
		}
	}

	public void onboard(String userId, byte[] faceJpeg) throws IOException {
		Path face = dir.resolve("operators").resolve(userId).resolve("face.jpg");
		Files.createDirectories(face.getParent());
		Files.write(face, faceJpeg);
		try {
			db.setOnboarded(userId, face.toString());
		} catch (SQLException e) {
			throw new StoreException("Saving the onboarding failed", e);
		}
	}

	// ------------------------------------------------------------------ registrations

	/** Registration ID in the MOSIP format: centre (5) + machine (5) + sequence (5) + timestamp (14) = 29 digits. */
	public String nextRid() {
		return CENTER_ID + MACHINE_ID + String.format("%05d", sequence.incrementAndGet() % 100000)
				+ LocalDateTime.now().format(RID_TIME);
	}

	/**
	 * Saves a registration as the client does before upload: the face image in the packet folder, the record
	 * (demographics, officer, liveness session and result) in REG.REGISTRATION, pending supervisor approval.
	 */
	public Path savePacket(String rid, Map<String, Object> demographics, byte[] faceJpeg, String livenessSessionId,
			String livenessStatus, String officerId) throws IOException {
		Path p = dir.resolve("packets").resolve(rid);
		Files.createDirectories(p);
		Path face = p.resolve("face.jpg");
		Files.write(face, faceJpeg);
		try {
			db.insertRegistration(rid, demographics, CENTER_ID, MACHINE_ID, officerId, face.toString(),
					livenessSessionId, livenessStatus, PENDING);
		} catch (SQLException e) {
			throw new StoreException("Saving the registration failed", e);
		}
		return p;
	}

	/** All registrations, newest first. */
	public List<Map<String, Object>> registrations() {
		try {
			return db.registrations();
		} catch (SQLException e) {
			throw new StoreException("Reading the registrations failed", e);
		}
	}

	public void setStatus(String rid, String status, String supervisorId, String comment) {
		try {
			db.updateRegistrationStatus(rid, status, supervisorId, comment);
		} catch (SQLException e) {
			throw new StoreException("Updating the registration failed", e);
		}
	}

	// ------------------------------------------------------------------ liveness results

	/** Records one liveness decision in REG.LIVENESS_RESULT (no images or scores). */
	public void recordLiveness(LivenessWorkflow workflow, String subjectId, FaceLivenessGuard.Verdict verdict) {
		LivenessOutcome o = verdict.getOutcome();
		String status = verdict.isSkipped() ? "SKIPPED" : verdict.isBlocked() ? "BLOCKED"
				: verdict.isDeviceError() ? "DEVICE_ERROR" : o == null ? "FAILED" : o.getStatus().name();
		String refType = workflow == LivenessWorkflow.RESIDENT_REGISTRATION ? "APPLICATION_ID" : "USER_ID";
		try {
			db.insertLivenessResult(workflow.name(), subjectId == null ? "" : subjectId, refType,
					o == null ? null : o.getSessionId(), status, o == null ? null : o.getReason());
		} catch (SQLException e) {
			System.err.println("liveness result not stored: " + e.getMessage());
		}
	}
}
