package io.mosip.demo;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.function.Function;

import io.mosip.extensions.liveness.api.LivenessWorkflow;
import javafx.beans.property.SimpleStringProperty;
import javafx.collections.FXCollections;
import javafx.collections.ObservableList;
import javafx.geometry.Insets;
import javafx.geometry.Pos;
import javafx.scene.control.Button;
import javafx.scene.control.Label;
import javafx.scene.control.TableColumn;
import javafx.scene.control.TableView;
import javafx.scene.image.ImageView;
import javafx.scene.layout.HBox;
import javafx.scene.layout.Priority;
import javafx.scene.layout.VBox;

/**
 * Pending Approval (the client's end-of-day approval): the supervisor marks registrations approved or rejected and
 * submits; submitting needs supervisor authentication with face liveness (supervisor policy).
 */
public class ApprovalScreen {

	private final DemoApp app;
	private final ObservableList<Map<String, Object>> rows = FXCollections.observableArrayList();
	private final Map<String, String> decisions = new LinkedHashMap<>();
	private final TableView<Map<String, Object>> table = new TableView<>(rows);
	private final ImageView photo = new ImageView();

	public ApprovalScreen(DemoApp app) {
		this.app = app;
	}

	public void show() {
		load();
		table.getColumns().add(column("Application ID", m -> m.get("rid"), 260));
		table.getColumns().add(column("Name", m -> m.get("name"), 160));
		table.getColumns().add(column("Officer", m -> m.get("officerId"), 80));
		table.getColumns().add(column("Created", m -> m.get("createdAt"), 150));
		table.getColumns().add(column("Liveness", m -> m.get("livenessStatus"), 90));
		table.getColumns().add(column("Status", m -> m.get("status"), 140));
		table.getColumns().add(column("Decision", m -> decisions.getOrDefault(String.valueOf(m.get("rid")), ""), 100));
		table.setColumnResizePolicy(TableView.CONSTRAINED_RESIZE_POLICY);
		table.getColumns().get(0).setMinWidth(250);
		table.setPrefHeight(320);
		table.getSelectionModel().selectedItemProperty().addListener((o, a, b) -> showPhoto(b));
		photo.setFitWidth(200);
		photo.setPreserveRatio(true);

		Button approve = DemoApp.secondary("Approve");
		approve.setOnAction(e -> decide(DemoStore.APPROVED));
		Button reject = DemoApp.secondary("Reject");
		reject.setOnAction(e -> decide(DemoStore.REJECTED));
		Button submit = DemoApp.primary("Submit");
		Label info = new Label();
		info.getStyleClass().add("demo-small");
		submit.setOnAction(e -> {
			if (decisions.isEmpty()) {
				info.setText("Approve or reject at least one pending registration first.");
				return;
			}
			authenticate();
		});
		Label hint = new Label("Select a pending registration, choose Approve or Reject, then Submit. Submitting "
				+ "requires supervisor authentication with face liveness.");
		hint.setWrapText(true);
		VBox card = DemoApp.card(DemoApp.title("Pending Approval"), hint, tableAndPhoto(),
				DemoApp.buttons(info, approve, reject, submit));
		card.setMaxWidth(1060);
		VBox page = new VBox(card);
		page.setPadding(new Insets(24));
		page.setAlignment(Pos.TOP_CENTER);
		app.show(page, null);
	}

	private HBox tableAndPhoto() {
		HBox.setHgrow(table, Priority.ALWAYS);
		return new HBox(20, table, photo);
	}

	private void load() {
		try {
			rows.setAll(app.getStore().registrations());
		} catch (DemoStore.StoreException e) {
			rows.clear();
			System.err.println(e.getMessage());
		}
	}

	private void decide(String status) {
		Map<String, Object> m = table.getSelectionModel().getSelectedItem();
		if (m == null || !DemoStore.PENDING.equals(m.get("status"))) {
			return;
		}
		decisions.put(String.valueOf(m.get("rid")), status);
		table.refresh();
	}

	private void showPhoto(Map<String, Object> m) {
		photo.setImage(null);
		if (m == null) {
			return;
		}
		try {
			photo.setImage(DemoApp.jpeg(Files.readAllBytes(Paths.get(String.valueOf(m.get("facePath"))))));
		} catch (IOException ignored) {
			// no photo
		}
	}

	private void authenticate() {
		AuthPane[] auth = new AuthPane[1];
		auth[0] = new AuthPane(app, LivenessWorkflow.SUPERVISOR_AUTHENTICATION,
				app.getUser().isSupervisor() ? app.getUser().id : null, supervisor -> {
					for (Map.Entry<String, String> d : decisions.entrySet()) {
						try {
							app.getStore().setStatus(d.getKey(), d.getValue(), supervisor.id, null);
							app.getAudit().note("PACKET_" + d.getValue(), d.getKey(), "REGISTRATION_ID");
						} catch (DemoStore.StoreException e) {
							System.err.println(e.getMessage());
						}
					}
					done(decisions.size(), supervisor);
				});
		Button cancel = DemoApp.secondary("Cancel");
		cancel.setOnAction(e -> show());
		VBox card = DemoApp.card(auth[0], DemoApp.buttons(cancel));
		card.setMaxWidth(760);
		app.show(DemoApp.center(card), auth[0]::stop);
	}

	private void done(int count, DemoStore.User supervisor) {
		Label ok = new Label(count + " registration(s) processed by " + supervisor.name + ".");
		ok.getStyleClass().add("demo-ok");
		Button back = DemoApp.primary("Back to Pending Approval");
		back.setOnAction(e -> new ApprovalScreen(app).show());
		Button home = DemoApp.secondary("Home");
		home.setOnAction(e -> app.showHome());
		VBox card = DemoApp.card(DemoApp.title("Approval submitted"), ok, DemoApp.buttons(home, back));
		card.setMaxWidth(600);
		app.show(DemoApp.center(card), null);
	}

	private static TableColumn<Map<String, Object>, String> column(String name,
			Function<Map<String, Object>, Object> value, double width) {
		TableColumn<Map<String, Object>, String> c = new TableColumn<>(name);
		c.setCellValueFactory(cd -> {
			Object v = value.apply(cd.getValue());
			return new SimpleStringProperty(v == null ? "" : String.valueOf(v));
		});
		c.setPrefWidth(width);
		return c;
	}
}
