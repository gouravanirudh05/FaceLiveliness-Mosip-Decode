package io.mosip.demo;

import java.nio.file.Path;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.security.SecureRandom;
import java.security.spec.InvalidKeySpecException;
import java.sql.Connection;
import java.sql.DatabaseMetaData;
import java.sql.DriverManager;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Statement;
import java.sql.Timestamp;
import java.util.ArrayList;
import java.util.Base64;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import javax.crypto.SecretKeyFactory;
import javax.crypto.spec.PBEKeySpec;

/**
 * Embedded Apache Derby database of the demo client, the same engine the Registration Client uses for its local
 * {@code REG} schema. Records live here (users, registrations, liveness results, audit trail, global parameters);
 * face images stay as files and the tables hold their paths, as the client keeps packets on disk.
 *
 * <p>One connection, used one statement at a time ({@code synchronized}); the demo is a single-user desktop app.
 */
public class DemoDb implements AutoCloseable {

	private static final String SCHEMA = "REG";

	private static final String[] DDL = {
			"CREATE SCHEMA REG",
			"CREATE TABLE REG.USER_DETAIL ("
					+ " ID VARCHAR(64) NOT NULL PRIMARY KEY,"
					+ " NAME VARCHAR(256) NOT NULL,"
					+ " PWD_HASH VARCHAR(256) NOT NULL,"
					+ " PWD_SALT VARCHAR(64) NOT NULL,"
					+ " ROLES VARCHAR(256) NOT NULL,"
					+ " IS_ONBOARDED BOOLEAN NOT NULL DEFAULT FALSE,"
					+ " FACE_PATH VARCHAR(1024),"
					+ " ONBOARDED_DTIMES TIMESTAMP,"
					+ " CR_DTIMES TIMESTAMP NOT NULL)",
			"CREATE TABLE REG.REGISTRATION ("
					+ " RID VARCHAR(64) NOT NULL PRIMARY KEY,"
					+ " FULL_NAME VARCHAR(256) NOT NULL,"
					+ " DOB DATE,"
					+ " GENDER VARCHAR(32),"
					+ " PHONE VARCHAR(32),"
					+ " EMAIL VARCHAR(256),"
					+ " ADDRESS VARCHAR(1024),"
					+ " CENTER_ID VARCHAR(16) NOT NULL,"
					+ " MACHINE_ID VARCHAR(16) NOT NULL,"
					+ " OFFICER_ID VARCHAR(64) NOT NULL,"
					+ " FACE_PATH VARCHAR(1024) NOT NULL,"
					+ " LIVENESS_SESSION_ID VARCHAR(64),"
					+ " LIVENESS_STATUS VARCHAR(32),"
					+ " STATUS VARCHAR(32) NOT NULL,"
					+ " REVIEWED_BY VARCHAR(64),"
					+ " REVIEWED_DTIMES TIMESTAMP,"
					+ " REVIEW_COMMENT VARCHAR(1024),"
					+ " CR_DTIMES TIMESTAMP NOT NULL)",
			"CREATE INDEX REG.IDX_REGISTRATION_STATUS ON REG.REGISTRATION (STATUS)",
			"CREATE TABLE REG.LIVENESS_RESULT ("
					+ " ID BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,"
					+ " WORKFLOW VARCHAR(64) NOT NULL,"
					+ " REF_ID VARCHAR(64) NOT NULL,"
					+ " REF_ID_TYPE VARCHAR(32) NOT NULL,"
					+ " SESSION_ID VARCHAR(64),"
					+ " STATUS VARCHAR(32) NOT NULL,"
					+ " REASON VARCHAR(128),"
					+ " CR_DTIMES TIMESTAMP NOT NULL)",
			"CREATE TABLE REG.AUDIT_LOG ("
					+ " ID BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,"
					+ " CR_DTIMES TIMESTAMP NOT NULL,"
					+ " EVENT_ID VARCHAR(64) NOT NULL,"
					+ " EVENT_NAME VARCHAR(128) NOT NULL,"
					+ " MODULE_NAME VARCHAR(128) NOT NULL,"
					+ " REF_ID VARCHAR(64),"
					+ " REF_ID_TYPE VARCHAR(32))",
			"CREATE TABLE REG.GLOBAL_PARAM ("
					+ " NAME VARCHAR(256) NOT NULL PRIMARY KEY,"
					+ " VAL VARCHAR(1024) NOT NULL,"
					+ " UPD_DTIMES TIMESTAMP NOT NULL)" };

	/** A user row (no password data leaves this class). */
	public static final class UserRow {
		public final String id;
		public final String name;
		public final List<String> roles;
		public final boolean onboarded;
		public final String facePath;

		UserRow(String id, String name, List<String> roles, boolean onboarded, String facePath) {
			this.id = id;
			this.name = name;
			this.roles = roles;
			this.onboarded = onboarded;
			this.facePath = facePath;
		}
	}

	private final Path dir;
	private final String url;
	private final Connection connection;

	/** Opens (and on first use creates) the database in {@code dir}. */
	public DemoDb(Path dir) throws SQLException {
		this.dir = dir;
		System.setProperty("derby.stream.error.file", dir.resolveSibling("derby.log").toString());
		this.url = "jdbc:derby:" + dir.toAbsolutePath();
		this.connection = DriverManager.getConnection(url + ";create=true");
		createSchemaIfMissing();
	}

	public Path getDir() {
		return dir;
	}

	private void createSchemaIfMissing() throws SQLException {
		DatabaseMetaData meta = connection.getMetaData();
		try (ResultSet rs = meta.getTables(null, SCHEMA, "AUDIT_LOG", null)) {
			if (rs.next()) {
				return;
			}
		}
		connection.setAutoCommit(false);
		try (Statement st = connection.createStatement()) {
			for (String sql : DDL) {
				st.execute(sql);
			}
			connection.commit();
		} catch (SQLException e) {
			connection.rollback();
			throw e;
		} finally {
			connection.setAutoCommit(true);
		}
	}

	// ------------------------------------------------------------------ users

	/** Adds the user unless the ID exists (seed data); the password is stored as a salted PBKDF2 hash. */
	public synchronized void insertUserIfMissing(String id, String name, String password, List<String> roles)
			throws SQLException {
		try (PreparedStatement ps = connection.prepareStatement("SELECT 1 FROM REG.USER_DETAIL WHERE ID = ?")) {
			ps.setString(1, id);
			try (ResultSet rs = ps.executeQuery()) {
				if (rs.next()) {
					return;
				}
			}
		}
		byte[] salt = new byte[16];
		new SecureRandom().nextBytes(salt);
		try (PreparedStatement ps = connection.prepareStatement("INSERT INTO REG.USER_DETAIL "
				+ "(ID, NAME, PWD_HASH, PWD_SALT, ROLES, IS_ONBOARDED, CR_DTIMES) VALUES (?, ?, ?, ?, ?, FALSE, ?)")) {
			ps.setString(1, id);
			ps.setString(2, name);
			ps.setString(3, hash(password, salt));
			ps.setString(4, Base64.getEncoder().encodeToString(salt));
			ps.setString(5, String.join(",", roles));
			ps.setTimestamp(6, now());
			ps.executeUpdate();
		}
	}

	/** The user if the ID exists and the password matches, else null. */
	public synchronized UserRow authenticate(String id, String password) throws SQLException {
		try (PreparedStatement ps = connection.prepareStatement(
				"SELECT PWD_HASH, PWD_SALT FROM REG.USER_DETAIL WHERE ID = ?")) {
			ps.setString(1, id);
			try (ResultSet rs = ps.executeQuery()) {
				if (!rs.next()) {
					return null;
				}
				byte[] expected = rs.getString(1).getBytes();
				byte[] actual = hash(password, Base64.getDecoder().decode(rs.getString(2))).getBytes();
				if (!MessageDigest.isEqual(expected, actual)) {
					return null;
				}
			}
		}
		return user(id);
	}

	public synchronized UserRow user(String id) throws SQLException {
		try (PreparedStatement ps = connection.prepareStatement(
				"SELECT ID, NAME, ROLES, IS_ONBOARDED, FACE_PATH FROM REG.USER_DETAIL WHERE ID = ?")) {
			ps.setString(1, id);
			try (ResultSet rs = ps.executeQuery()) {
				return rs.next() ? userRow(rs) : null;
			}
		}
	}

	public synchronized List<UserRow> users() throws SQLException {
		List<UserRow> out = new ArrayList<>();
		try (Statement st = connection.createStatement();
				ResultSet rs = st.executeQuery(
						"SELECT ID, NAME, ROLES, IS_ONBOARDED, FACE_PATH FROM REG.USER_DETAIL ORDER BY ID")) {
			while (rs.next()) {
				out.add(userRow(rs));
			}
		}
		return out;
	}

	public synchronized void setOnboarded(String id, String facePath) throws SQLException {
		try (PreparedStatement ps = connection.prepareStatement("UPDATE REG.USER_DETAIL "
				+ "SET IS_ONBOARDED = TRUE, FACE_PATH = ?, ONBOARDED_DTIMES = ? WHERE ID = ?")) {
			ps.setString(1, facePath);
			ps.setTimestamp(2, now());
			ps.setString(3, id);
			ps.executeUpdate();
		}
	}

	private static UserRow userRow(ResultSet rs) throws SQLException {
		List<String> roles = new ArrayList<>();
		for (String r : rs.getString(3).split(",")) {
			if (!r.trim().isEmpty()) {
				roles.add(r.trim());
			}
		}
		return new UserRow(rs.getString(1), rs.getString(2), roles, rs.getBoolean(4), rs.getString(5));
	}

	private static String hash(String password, byte[] salt) {
		try {
			PBEKeySpec spec = new PBEKeySpec(password.toCharArray(), salt, 65536, 256);
			byte[] key = SecretKeyFactory.getInstance("PBKDF2WithHmacSHA256").generateSecret(spec).getEncoded();
			spec.clearPassword();
			return Base64.getEncoder().encodeToString(key);
		} catch (NoSuchAlgorithmException | InvalidKeySpecException e) {
			throw new IllegalStateException("PBKDF2 not available", e);
		}
	}

	// ------------------------------------------------------------------ registrations

	public synchronized int registrationCount() throws SQLException {
		try (Statement st = connection.createStatement();
				ResultSet rs = st.executeQuery("SELECT COUNT(*) FROM REG.REGISTRATION")) {
			rs.next();
			return rs.getInt(1);
		}
	}

	public synchronized void insertRegistration(String rid, Map<String, Object> demographics, String centerId,
			String machineId, String officerId, String facePath, String livenessSessionId, String livenessStatus,
			String status) throws SQLException {
		try (PreparedStatement ps = connection.prepareStatement("INSERT INTO REG.REGISTRATION (RID, FULL_NAME, "
				+ "DOB, GENDER, PHONE, EMAIL, ADDRESS, CENTER_ID, MACHINE_ID, OFFICER_ID, FACE_PATH, "
				+ "LIVENESS_SESSION_ID, LIVENESS_STATUS, STATUS, CR_DTIMES) "
				+ "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)")) {
			ps.setString(1, rid);
			ps.setString(2, str(demographics.get("fullName")));
			Object dob = demographics.get("dateOfBirth");
			ps.setDate(3, dob == null || "null".equals(dob) ? null : java.sql.Date.valueOf(String.valueOf(dob)));
			ps.setString(4, str(demographics.get("gender")));
			ps.setString(5, str(demographics.get("phone")));
			ps.setString(6, str(demographics.get("email")));
			ps.setString(7, str(demographics.get("address")));
			ps.setString(8, centerId);
			ps.setString(9, machineId);
			ps.setString(10, officerId);
			ps.setString(11, facePath);
			ps.setString(12, livenessSessionId);
			ps.setString(13, livenessStatus);
			ps.setString(14, status);
			ps.setTimestamp(15, now());
			ps.executeUpdate();
		}
	}

	/** Registrations, newest first, as column-name maps for the approval table. */
	public synchronized List<Map<String, Object>> registrations() throws SQLException {
		List<Map<String, Object>> out = new ArrayList<>();
		try (Statement st = connection.createStatement();
				ResultSet rs = st.executeQuery("SELECT RID, FULL_NAME, OFFICER_ID, CR_DTIMES, STATUS, FACE_PATH, "
						+ "LIVENESS_STATUS, REVIEWED_BY FROM REG.REGISTRATION ORDER BY CR_DTIMES DESC")) {
			while (rs.next()) {
				Map<String, Object> m = new LinkedHashMap<>();
				m.put("rid", rs.getString(1));
				m.put("name", rs.getString(2));
				m.put("officerId", rs.getString(3));
				m.put("createdAt", rs.getTimestamp(4).toLocalDateTime().withNano(0).toString().replace('T', ' '));
				m.put("status", rs.getString(5));
				m.put("facePath", rs.getString(6));
				m.put("livenessStatus", rs.getString(7));
				m.put("reviewedBy", rs.getString(8));
				out.add(m);
			}
		}
		return out;
	}

	public synchronized void updateRegistrationStatus(String rid, String status, String reviewedBy, String comment)
			throws SQLException {
		try (PreparedStatement ps = connection.prepareStatement("UPDATE REG.REGISTRATION "
				+ "SET STATUS = ?, REVIEWED_BY = ?, REVIEWED_DTIMES = ?, REVIEW_COMMENT = ? WHERE RID = ?")) {
			ps.setString(1, status);
			ps.setString(2, reviewedBy);
			ps.setTimestamp(3, now());
			ps.setString(4, comment);
			ps.setString(5, rid);
			ps.executeUpdate();
		}
	}

	// ------------------------------------------------------------------ liveness results

	/** One liveness decision: workflow, who, session and outcome. No images or scores are stored. */
	public synchronized void insertLivenessResult(String workflow, String refId, String refIdType, String sessionId,
			String status, String reason) throws SQLException {
		try (PreparedStatement ps = connection.prepareStatement("INSERT INTO REG.LIVENESS_RESULT "
				+ "(WORKFLOW, REF_ID, REF_ID_TYPE, SESSION_ID, STATUS, REASON, CR_DTIMES) VALUES (?, ?, ?, ?, ?, ?, ?)")) {
			ps.setString(1, workflow);
			ps.setString(2, refId);
			ps.setString(3, refIdType);
			ps.setString(4, sessionId);
			ps.setString(5, status);
			ps.setString(6, reason);
			ps.setTimestamp(7, now());
			ps.executeUpdate();
		}
	}

	// ------------------------------------------------------------------ audit

	public synchronized void insertAudit(Timestamp time, String eventId, String eventName, String module,
			String refId, String refIdType) throws SQLException {
		try (PreparedStatement ps = connection.prepareStatement("INSERT INTO REG.AUDIT_LOG "
				+ "(CR_DTIMES, EVENT_ID, EVENT_NAME, MODULE_NAME, REF_ID, REF_ID_TYPE) VALUES (?, ?, ?, ?, ?, ?)")) {
			ps.setTimestamp(1, time);
			ps.setString(2, eventId);
			ps.setString(3, eventName);
			ps.setString(4, module);
			ps.setString(5, refId);
			ps.setString(6, refIdType);
			ps.executeUpdate();
		}
	}

	/** Audit rows, newest first: time, event ID, event name, module, reference ID, reference type. */
	public synchronized List<String[]> audit(int limit) throws SQLException {
		List<String[]> out = new ArrayList<>();
		try (Statement st = connection.createStatement()) {
			st.setMaxRows(limit);
			try (ResultSet rs = st.executeQuery("SELECT CR_DTIMES, EVENT_ID, EVENT_NAME, MODULE_NAME, REF_ID, "
					+ "REF_ID_TYPE FROM REG.AUDIT_LOG ORDER BY ID DESC")) {
				while (rs.next()) {
					out.add(new String[] { rs.getTimestamp(1).toLocalDateTime().withNano(0).toString().replace('T', ' '),
							rs.getString(2), rs.getString(3), rs.getString(4), rs.getString(5), rs.getString(6) });
				}
			}
		}
		return out;
	}

	// ------------------------------------------------------------------ global parameters

	/** Adds the parameter unless it exists (defaults; values changed in the app are kept). */
	public synchronized void insertParamIfMissing(String name, String value) throws SQLException {
		try (PreparedStatement ps = connection.prepareStatement("SELECT 1 FROM REG.GLOBAL_PARAM WHERE NAME = ?")) {
			ps.setString(1, name);
			try (ResultSet rs = ps.executeQuery()) {
				if (rs.next()) {
					return;
				}
			}
		}
		try (PreparedStatement ps = connection.prepareStatement(
				"INSERT INTO REG.GLOBAL_PARAM (NAME, VAL, UPD_DTIMES) VALUES (?, ?, ?)")) {
			ps.setString(1, name);
			ps.setString(2, value);
			ps.setTimestamp(3, now());
			ps.executeUpdate();
		}
	}

	public synchronized Map<String, String> params() throws SQLException {
		Map<String, String> out = new LinkedHashMap<>();
		try (Statement st = connection.createStatement();
				ResultSet rs = st.executeQuery("SELECT NAME, VAL FROM REG.GLOBAL_PARAM ORDER BY NAME")) {
			while (rs.next()) {
				out.put(rs.getString(1), rs.getString(2));
			}
		}
		return out;
	}

	/** Replaces every parameter starting with {@code prefix} by {@code values} (empty values are dropped). */
	public synchronized void replaceParams(String prefix, Map<String, String> values) throws SQLException {
		connection.setAutoCommit(false);
		try (PreparedStatement del = connection.prepareStatement("DELETE FROM REG.GLOBAL_PARAM WHERE NAME LIKE ?");
				PreparedStatement ins = connection.prepareStatement(
						"INSERT INTO REG.GLOBAL_PARAM (NAME, VAL, UPD_DTIMES) VALUES (?, ?, ?)")) {
			del.setString(1, prefix + "%");
			del.executeUpdate();
			Timestamp now = now();
			for (Map.Entry<String, String> e : values.entrySet()) {
				if (e.getValue() != null && !e.getValue().trim().isEmpty()) {
					ins.setString(1, e.getKey());
					ins.setString(2, e.getValue().trim());
					ins.setTimestamp(3, now);
					ins.addBatch();
				}
			}
			ins.executeBatch();
			connection.commit();
		} catch (SQLException e) {
			connection.rollback();
			throw e;
		} finally {
			connection.setAutoCommit(true);
		}
	}

	// ------------------------------------------------------------------ misc

	private static Timestamp now() {
		return new Timestamp(System.currentTimeMillis());
	}

	private static String str(Object o) {
		return o == null ? null : String.valueOf(o);
	}

	/** Closes the connection and shuts the embedded database down cleanly. */
	@Override
	public synchronized void close() {
		try {
			connection.close();
		} catch (SQLException ignored) {
			// shutting down anyway
		}
		try {
			DriverManager.getConnection(url + ";shutdown=true").close();
		} catch (SQLException expected) {
			// Derby reports a successful shutdown as SQLState 08006
		}
	}
}
