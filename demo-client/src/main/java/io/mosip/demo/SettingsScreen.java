package io.mosip.demo;

import java.sql.SQLException;
import java.util.LinkedHashMap;
import java.util.Map;

import io.mosip.registration.context.ApplicationContext;
import javafx.application.Platform;
import javafx.geometry.Insets;
import javafx.geometry.Pos;
import javafx.scene.control.Button;
import javafx.scene.control.Label;
import javafx.scene.control.TextField;
import javafx.scene.layout.ColumnConstraints;
import javafx.scene.layout.GridPane;
import javafx.scene.layout.HBox;
import javafx.scene.layout.Region;
import javafx.scene.layout.VBox;

/**
 * Liveness policy editor and diagnostics. In MOSIP these values are global parameters synced from the server; here
 * Apply writes them into the client's {@link ApplicationContext} map (the guard applies them from the next liveness
 * session) and Save also stores them in REG.GLOBAL_PARAM. Diagnostics are the guard's own report (device discovery over SBI, engine capabilities and
 * model hashes, effective policies, anonymised metrics).
 */
public class SettingsScreen {

	private static final String[] WORKFLOWS = { "", "resident", "operator", "supervisor" };
	private static final String[] WORKFLOW_NAMES = { "All workflows", "Resident", "Operator", "Supervisor" };
	private static final String[][] POLICY_KEYS = {
			{ "enable", "Liveness enabled (Y/N)" },
			{ "passive.threshold", "Passive accept threshold (0-1)" },
			{ "passive.reject.threshold", "PAD attack threshold (0-1)" },
			{ "passive.no.response.action", "No usable face in passive (ACTIVE/FAIL)" },
			{ "active.enable", "Active challenges (Y/N)" },
			{ "active.min.challenges", "Minimum challenges" },
			{ "active.challenge.types", "Challenge types" },
			{ "active.compound.challenges", "Compound challenges (Y/N)" },
			{ "active.challenge.timeout.seconds", "Step timeouts (s, comma list)" },
			{ "active.max.retries", "Max retries per session" },
			{ "repeated.failure.max.sessions", "Failed sessions before action" },
			{ "repeated.failure.action", "On repeated failure (BLOCK/CONTINUE)" } };
	private static final String[][] GLOBAL_KEYS = {
			{ "engine.error.policy", "Engine error policy (DENY/ALLOW)" },
			{ "session.timeout.seconds", "Session timeout (s)" },
			{ "max.fps", "Frames per second sent" },
			{ "retry.delay.ms", "Retry guidance delay (ms)" },
			{ "device.frame.timeout.seconds", "No-frame device timeout (s)" },
			{ "service.host", "Engine host" },
			{ "service.port", "Engine port" } };

	private final DemoApp app;
	private final Map<String, TextField> fields = new LinkedHashMap<>();
	private final VBox diagnostics = new VBox(6);

	public SettingsScreen(DemoApp app) {
		this.app = app;
	}

	public void show() {
		GridPane policy = new GridPane();
		policy.getColumnConstraints().add(labelColumn());
		policy.setHgap(10);
		policy.setVgap(6);
		for (int c = 0; c < WORKFLOW_NAMES.length; c++) {
			Label h = new Label(WORKFLOW_NAMES[c]);
			h.getStyleClass().add("demo-tile-title");
			policy.add(h, c + 1, 0);
		}
		int r = 1;
		for (String[] k : POLICY_KEYS) {
			policy.add(new Label(k[1]), 0, r);
			for (int c = 0; c < WORKFLOWS.length; c++) {
				policy.add(field(key(WORKFLOWS[c], k[0]), c == 0 ? "" : "(shared)"), c + 1, r);
			}
			r++;
		}
		GridPane global = new GridPane();
		global.getColumnConstraints().add(labelColumn());
		global.setHgap(10);
		global.setVgap(6);
		r = 0;
		for (String[] k : GLOBAL_KEYS) {
			global.addRow(r++, new Label(k[1]), field(key("", k[0]), "(default)"));
		}

		Label status = new Label();
		status.getStyleClass().add("demo-ok");
		Button apply = DemoApp.primary("Apply");
		apply.setOnAction(e -> {
			apply();
			status.setText("Applied. Takes effect from the next liveness session.");
		});
		Button save = DemoApp.secondary("Apply & save");
		save.setOnAction(e -> {
			apply();
			try {
				save();
				status.setText("Saved to REG.GLOBAL_PARAM; kept across restarts.");
			} catch (SQLException ex) {
				status.setText("Save failed: " + ex.getMessage());
			}
		});
		Button run = DemoApp.secondary("Run diagnostics");
		run.setOnAction(e -> runDiagnostics());

		VBox policyCard = DemoApp.card(DemoApp.title("Face liveness policy"),
				new Label("Empty = use the shared value (or the engine default). Keys: "
						+ DemoApp.PREFIX + "[resident|operator|supervisor.]<key>"),
				policy, new Label("Engine and device"), global, DemoApp.buttons(status, save, apply));
		VBox diagCard = DemoApp.card(DemoApp.title("Diagnostics"), DemoApp.buttons(run), diagnostics);
		VBox page = new VBox(20, policyCard, diagCard);
		page.setPadding(new Insets(24));
		page.setAlignment(Pos.TOP_CENTER);
		page.setMaxWidth(1100);
		HBox wrap = new HBox(page);
		wrap.setAlignment(Pos.TOP_CENTER);
		app.show(wrap, null);
		runDiagnostics();
	}

	private static ColumnConstraints labelColumn() {
		ColumnConstraints c = new ColumnConstraints();
		c.setMinWidth(Region.USE_PREF_SIZE);
		return c;
	}

	private static String key(String workflow, String name) {
		return DemoApp.PREFIX + (workflow.isEmpty() ? "" : workflow + ".") + name;
	}

	private TextField field(String key, String prompt) {
		TextField f = new TextField();
		Object v = ApplicationContext.map().get(key);
		f.setText(v == null ? "" : String.valueOf(v));
		f.setPromptText(prompt);
		f.setPrefColumnCount(key.endsWith("challenge.types") ? 22 : 9);
		fields.put(key, f);
		return f;
	}

	private void apply() {
		Map<String, Object> map = ApplicationContext.map();
		fields.forEach((k, f) -> {
			String v = f.getText().trim();
			if (v.isEmpty()) {
				map.remove(k);
			} else {
				map.put(k, v);
			}
		});
	}

	/** Stores the edited liveness parameters in REG.GLOBAL_PARAM (replacing the previous liveness rows). */
	private void save() throws SQLException {
		Map<String, String> values = new LinkedHashMap<>();
		fields.forEach((k, f) -> values.put(k, f.getText().trim()));
		app.getDb().replaceParams(DemoApp.PREFIX, values);
	}

	private void runDiagnostics() {
		diagnostics.getChildren().setAll(new Label("Running diagnostics…"));
		app.background("diagnostics", () -> {
			Map<String, String> report = app.getGuard().diagnosticsReport(app.getMds().discoverFace());
			Platform.runLater(() -> {
				GridPane g = new GridPane();
				g.setHgap(16);
				g.setVgap(6);
				int r = 0;
				for (Map.Entry<String, String> e : report.entrySet()) {
					Label k = new Label(e.getKey());
					k.getStyleClass().add("demo-tile-title");
					Label v = new Label(e.getValue());
					v.setWrapText(true);
					v.setMaxWidth(780);
					g.addRow(r++, k, v);
				}
				diagnostics.getChildren().setAll(g);
			});
		});
	}
}
