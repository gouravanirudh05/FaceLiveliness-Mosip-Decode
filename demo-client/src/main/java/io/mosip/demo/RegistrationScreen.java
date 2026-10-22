package io.mosip.demo;

import java.io.IOException;
import java.nio.file.Path;
import java.time.LocalDate;
import java.time.Period;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import io.mosip.extensions.liveness.api.LivenessWorkflow;
import io.mosip.extensions.liveness.client.LivenessOutcome;
import io.mosip.registration.controller.device.FaceLivenessGuard;
import javafx.geometry.Insets;
import javafx.geometry.Pos;
import javafx.scene.Node;
import javafx.scene.control.Button;
import javafx.scene.control.CheckBox;
import javafx.scene.control.ComboBox;
import javafx.scene.control.DatePicker;
import javafx.scene.control.Label;
import javafx.scene.control.TextField;
import javafx.scene.image.ImageView;
import javafx.scene.layout.GridPane;
import javafx.scene.layout.HBox;
import javafx.scene.layout.VBox;

/**
 * New Registration: consent, demographics, resident face capture (liveness, resident policy), preview, operator
 * authentication (liveness, operator policy), acknowledgement. The packet is saved locally pending supervisor
 * approval, as the client does before upload.
 */
public class RegistrationScreen {

	private static final String[] STEPS = { "Consent", "Demographics", "Face", "Preview", "Authentication",
			"Acknowledgement" };

	private final DemoApp app;
	private final String rid;
	private final TextField fullName = new TextField();
	private final DatePicker dob = new DatePicker();
	private final ComboBox<String> gender = new ComboBox<>();
	private final TextField phone = new TextField();
	private final TextField email = new TextField();
	private final TextField address = new TextField();
	private byte[] face;
	private FaceLivenessGuard.Verdict faceVerdict;

	public RegistrationScreen(DemoApp app) {
		this.app = app;
		this.rid = app.getStore().nextRid();
		gender.getItems().addAll("Female", "Male", "Others");
		fullName.setPromptText("Full name");
		dob.setPromptText("Date of birth");
		gender.setPromptText("Gender");
		phone.setPromptText("Phone");
		email.setPromptText("Email");
		address.setPromptText("Address");
	}

	public void show() {
		consent();
	}

	private VBox page(int step, Node... content) {
		HBox tracker = new HBox(6);
		for (int i = 0; i < STEPS.length; i++) {
			Label l = new Label((i + 1) + ". " + STEPS[i]);
			l.getStyleClass().add(i == step ? "demo-step-active" : i < step ? "demo-step-done" : "demo-step");
			tracker.getChildren().add(l);
		}
		tracker.setAlignment(Pos.CENTER);
		Label ridLabel = new Label("Application ID: " + rid);
		ridLabel.getStyleClass().add("demo-small");
		VBox c = DemoApp.card(content);
		c.setMaxWidth(760);
		VBox page = new VBox(16, DemoApp.title("New Registration"), tracker, ridLabel, c);
		page.setPadding(new Insets(24));
		page.setAlignment(Pos.TOP_CENTER);
		return page;
	}

	private void consent() {
		CheckBox agree = new CheckBox("I agree to the collection and processing of my demographic and biometric data "
				+ "(face) for registration, including a face liveness check.");
		agree.setWrapText(true);
		Button next = DemoApp.primary("Continue");
		next.disableProperty().bind(agree.selectedProperty().not());
		next.setOnAction(e -> demographics());
		Button cancel = DemoApp.secondary("Cancel");
		cancel.setOnAction(e -> app.showHome());
		app.show(page(0, new Label("Consent"), agree, DemoApp.buttons(cancel, next)), null);
	}

	private void demographics() {
		GridPane g = new GridPane();
		g.setHgap(16);
		g.setVgap(12);
		row(g, 0, "Full name *", fullName);
		row(g, 1, "Date of birth *", dob);
		row(g, 2, "Gender *", gender);
		row(g, 3, "Phone", phone);
		row(g, 4, "Email", email);
		row(g, 5, "Address", address);
		Label error = new Label();
		error.getStyleClass().add("demo-error");
		Button next = DemoApp.primary("Continue");
		next.setOnAction(e -> {
			List<String> missing = new ArrayList<>();
			if (fullName.getText().trim().isEmpty()) {
				missing.add("full name");
			}
			if (dob.getValue() == null || dob.getValue().isAfter(LocalDate.now())) {
				missing.add("a valid date of birth");
			}
			if (gender.getValue() == null) {
				missing.add("gender");
			}
			if (!missing.isEmpty()) {
				error.setText("Please enter " + String.join(", ", missing) + ".");
				return;
			}
			faceStep();
		});
		Button back = DemoApp.secondary("Back");
		back.setOnAction(e -> consent());
		app.show(page(1, g, error, DemoApp.buttons(back, next)), null);
	}

	private static void row(GridPane g, int r, String label, Node field) {
		field.getStyleClass().add("demoGraphicTextField");
		if (field instanceof TextField) {
			((TextField) field).setPrefColumnCount(28);
		}
		g.addRow(r, new Label(label), field);
	}

	private void faceStep() {
		Button next = DemoApp.primary("Continue");
		next.setDisable(face == null);
		FaceCapturePane pane = new FaceCapturePane(app, LivenessWorkflow.RESIDENT_REGISTRATION,
				"Ask the resident to look at the camera, then press Capture. Liveness is checked first (passive); the "
						+ "resident may be asked to perform actions such as blinking or turning the head.",
				() -> rid, (jpeg, verdict) -> {
					face = jpeg;
					faceVerdict = verdict;
					next.setDisable(false);
				});
		next.setOnAction(e -> preview());
		Button back = DemoApp.secondary("Back");
		back.setOnAction(e -> demographics());
		app.show(page(2, pane, DemoApp.buttons(back, next)), pane::stop);
		pane.startPreview();
	}

	private void preview() {
		GridPane g = new GridPane();
		g.setHgap(16);
		g.setVgap(8);
		int r = 0;
		String[] labels = { "Full name", "Date of birth", "Age", "Gender", "Phone", "Email", "Address" };
		for (Object value : demographicsMap().values()) {
			Label k = new Label(labels[r]);
			k.getStyleClass().add("demo-tile-title");
			g.addRow(r++, k, new Label(String.valueOf(value)));
		}
		ImageView photo = new ImageView(DemoApp.jpeg(face));
		photo.setFitWidth(220);
		photo.setPreserveRatio(true);
		Label live = new Label(livenessSummary());
		live.getStyleClass().add("demo-ok");
		live.setWrapText(true);
		HBox body = new HBox(30, g, new VBox(8, photo, live));
		Button next = DemoApp.primary("Continue");
		next.setOnAction(e -> authentication());
		Button back = DemoApp.secondary("Back");
		back.setOnAction(e -> faceStep());
		app.show(page(3, new Label("Preview"), body, DemoApp.buttons(back, next)), null);
	}

	private String livenessSummary() {
		if (faceVerdict == null || faceVerdict.isSkipped()) {
			return "Face liveness: disabled by configuration";
		}
		LivenessOutcome o = faceVerdict.getOutcome();
		return "Face liveness: PASSED" + (o == null ? "" : " (session " + o.getSessionId() + ")");
	}

	private void authentication() {
		AuthPane auth = new AuthPane(app, LivenessWorkflow.OPERATOR_AUTHENTICATION, app.getUser().id, u -> save());
		Button back = DemoApp.secondary("Back");
		back.setOnAction(e -> preview());
		app.show(page(4, auth, DemoApp.buttons(back)), auth::stop);
	}

	private void save() {
		LivenessOutcome o = faceVerdict == null ? null : faceVerdict.getOutcome();
		String sessionId = o == null ? null : o.getSessionId();
		String livenessStatus = o != null ? o.getStatus().name()
				: faceVerdict != null && faceVerdict.isSkipped() ? "SKIPPED" : "UNKNOWN";
		Path dir;
		try {
			dir = app.getStore().savePacket(rid, demographicsMap(), face, sessionId, livenessStatus, app.getUser().id);
			app.getAudit().note("PACKET_CREATED", rid, "REGISTRATION_ID");
		} catch (IOException | DemoStore.StoreException e) {
			Label err = new Label("Saving the registration failed: " + e.getMessage());
			err.getStyleClass().add("demo-error");
			app.show(page(4, err), null);
			return;
		}
		acknowledgement(dir);
	}

	private void acknowledgement(Path dir) {
		Label ok = new Label("Registration saved. It is pending supervisor approval.");
		ok.getStyleClass().add("demo-ok");
		Label id = new Label("Application ID: " + rid);
		id.getStyleClass().add("demo-tile-title");
		Label where = new Label("Saved in the local database (REG.REGISTRATION); face image in " + dir
				+ "\n(the real client would upload the encrypted packet to the MOSIP server after approval)");
		where.getStyleClass().add("demo-small");
		Button another = DemoApp.secondary("New Registration");
		another.setOnAction(e -> new RegistrationScreen(app).show());
		Button home = DemoApp.primary("Home");
		home.setOnAction(e -> app.showHome());
		app.show(page(5, ok, id, where, DemoApp.buttons(another, home)), null);
	}

	private Map<String, Object> demographicsMap() {
		Map<String, Object> m = new LinkedHashMap<>();
		m.put("fullName", fullName.getText().trim());
		m.put("dateOfBirth", String.valueOf(dob.getValue()));
		m.put("age", dob.getValue() == null ? "" : Period.between(dob.getValue(), LocalDate.now()).getYears());
		m.put("gender", gender.getValue());
		m.put("phone", phone.getText().trim());
		m.put("email", email.getText().trim());
		m.put("address", address.getText().trim());
		return m;
	}
}
