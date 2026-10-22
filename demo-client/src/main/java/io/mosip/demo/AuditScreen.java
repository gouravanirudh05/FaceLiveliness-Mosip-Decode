package io.mosip.demo;

import java.util.function.Function;

import javafx.beans.property.SimpleStringProperty;
import javafx.geometry.Insets;
import javafx.geometry.Pos;
import javafx.scene.control.Label;
import javafx.scene.control.TableColumn;
import javafx.scene.control.TableView;
import javafx.scene.layout.VBox;

/** The audit trail of this run: liveness events from the guard plus the demo's own login / packet events. */
public class AuditScreen {

	private final DemoApp app;

	public AuditScreen(DemoApp app) {
		this.app = app;
	}

	public void show() {
		TableView<DemoAudit.Entry> table = new TableView<>(app.getAudit().getEntries());
		table.getColumns().add(column("Time", e -> e.time, 130));
		table.getColumns().add(column("Event ID", e -> e.eventId, 80));
		table.getColumns().add(column("Event", e -> e.eventName, 320));
		table.getColumns().add(column("Module", e -> e.component, 220));
		table.getColumns().add(column("Reference ID", e -> e.refId, 240));
		table.getColumns().add(column("Reference type", e -> e.refIdType, 120));
		table.setColumnResizePolicy(TableView.CONSTRAINED_RESIZE_POLICY);
		table.setPrefHeight(520);
		table.setPlaceholder(new Label("No audit events yet."));
		Label file = new Label("Table REG.AUDIT_LOG in the demo database (" + app.getDb().getDir()
				+ "). Events record the decision only: no face images or scores.");
		file.getStyleClass().add("demo-small");
		VBox card = DemoApp.card(DemoApp.title("Audit Log"), table, file);
		card.setMaxWidth(1140);
		VBox page = new VBox(card);
		page.setPadding(new Insets(24));
		page.setAlignment(Pos.TOP_CENTER);
		app.show(page, null);
	}

	private static TableColumn<DemoAudit.Entry, String> column(String name, Function<DemoAudit.Entry, String> value,
			double width) {
		TableColumn<DemoAudit.Entry, String> c = new TableColumn<>(name);
		c.setCellValueFactory(cd -> new SimpleStringProperty(value.apply(cd.getValue())));
		c.setPrefWidth(width);
		return c;
	}
}
