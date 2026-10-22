package io.mosip.demo;

import java.sql.SQLException;
import java.sql.Timestamp;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;

import io.mosip.registration.audit.AuditManagerService;
import io.mosip.registration.constants.AuditEvent;
import io.mosip.registration.constants.Components;
import io.mosip.registration.dto.ResponseDTO;
import javafx.application.Platform;
import javafx.collections.FXCollections;
import javafx.collections.ObservableList;

/**
 * Stands in for the client's audit manager: the guard's audit events (REG-EVT-104..109) and the demo's own events
 * go into REG.AUDIT_LOG and are listed on the Audit screen. Only event, module and reference IDs are recorded, as
 * in the client; never images or scores.
 */
public class DemoAudit implements AuditManagerService {

	/** Rows loaded into the Audit screen at start-up. */
	private static final int HISTORY = 500;

	/** One audit row: time, event ID, event name, module, reference ID, reference type. */
	public static final class Entry {
		public final String time;
		public final String eventId;
		public final String eventName;
		public final String component;
		public final String refId;
		public final String refIdType;

		Entry(String time, String eventId, String eventName, String component, String refId, String refIdType) {
			this.time = time;
			this.eventId = eventId;
			this.eventName = eventName;
			this.component = component;
			this.refId = refId;
			this.refIdType = refIdType;
		}
	}

	private static final DateTimeFormatter TIME = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss");

	private final DemoDb db;
	private final ObservableList<Entry> entries = FXCollections.observableArrayList();

	public DemoAudit(DemoDb db) {
		this.db = db;
		try {
			for (String[] r : db.audit(HISTORY)) {
				entries.add(new Entry(r[0], r[1], r[2], r[3], r[4], r[5]));
			}
		} catch (SQLException e) {
			System.err.println("audit read failed: " + e.getMessage());
		}
	}

	public ObservableList<Entry> getEntries() {
		return entries;
	}

	@Override
	public void audit(AuditEvent event, Components component, String refId, String refIdType) {
		add(event.getId(), event.getName(), component.getName(), refId, refIdType);
	}

	/** Records a demo-app event (login, packet saved, approval) that is not a liveness event. */
	public void note(String eventName, String refId, String refIdType) {
		add("DEMO", eventName, "Demo client", refId, refIdType);
	}

	private void add(String eventId, String eventName, String module, String refId, String refIdType) {
		LocalDateTime now = LocalDateTime.now().withNano(0);
		try {
			db.insertAudit(Timestamp.valueOf(now), eventId, eventName, module, refId, refIdType);
		} catch (SQLException e) {
			System.err.println("audit write failed: " + e.getMessage());
		}
		Entry e = new Entry(now.format(TIME), eventId, eventName, module, refId, refIdType);
		Platform.runLater(() -> entries.add(0, e));
	}

	@Override
	public ResponseDTO deleteAuditLogs() {
		return new ResponseDTO();
	}
}
