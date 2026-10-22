package io.mosip.demo;

import java.util.function.Consumer;

import io.mosip.extensions.liveness.api.LivenessWorkflow;
import javafx.scene.control.Button;
import javafx.scene.control.Label;
import javafx.scene.control.PasswordField;
import javafx.scene.control.TextField;
import javafx.scene.layout.HBox;
import javafx.scene.layout.VBox;

/**
 * Operator / supervisor authentication, as on the client's Authentication screen: user ID and password, then face
 * with liveness under the workflow's own policy. The supervisor variant only accepts users with the supervisor role
 * (the client's {@code isReviewer} path).
 */
public class AuthPane extends VBox {

	private final DemoApp app;
	private final LivenessWorkflow workflow;
	private final Consumer<DemoStore.User> onAuthenticated;
	private final VBox faceArea = new VBox();
	private final TextField id = new TextField();
	private FaceCapturePane face;

	public AuthPane(DemoApp app, LivenessWorkflow workflow, String fixedUserId, Consumer<DemoStore.User> onAuthenticated) {
		super(12);
		this.app = app;
		this.workflow = workflow;
		this.onAuthenticated = onAuthenticated;
		boolean supervisor = workflow == LivenessWorkflow.SUPERVISOR_AUTHENTICATION;

		Label heading = DemoApp.title(supervisor ? "Supervisor authentication" : "Operator authentication");
		Label info = new Label(supervisor
				? "A supervisor must be physically present: supervisor ID and password, then face with liveness."
				: "Confirm the registration: officer password, then face with liveness.");
		info.setWrapText(true);
		id.setPromptText(supervisor ? "Supervisor ID" : "Officer ID");
		id.getStyleClass().add("demoGraphicTextField");
		if (fixedUserId != null) {
			id.setText(fixedUserId);
			id.setEditable(false);
		}
		PasswordField pwd = new PasswordField();
		pwd.setPromptText("Password");
		pwd.getStyleClass().add("demoGraphicTextField");
		Label error = new Label();
		error.getStyleClass().add("demo-error");
		Button next = DemoApp.primary("Next");
		next.setOnAction(e -> {
			DemoStore.User u = app.getStore().authenticate(id.getText(), pwd.getText());
			if (u == null) {
				error.setText("Invalid user ID or password.");
				return;
			}
			if (supervisor && !u.isSupervisor()) {
				error.setText("User " + u.id + " is not a supervisor.");
				return;
			}
			error.setText("");
			next.setDisable(true);
			id.setEditable(false);
			pwd.setEditable(false);
			showFace(u);
		});
		HBox creds = new HBox(12, id, pwd, next);
		getChildren().addAll(heading, info, creds, error, faceArea);
	}

	private void showFace(DemoStore.User u) {
		face = new FaceCapturePane(app, workflow, u.name + ": look at the camera and press Capture.", () -> u.id,
				(jpeg, verdict) -> {
					// MOSIP matches against the user's onboarded face (BioSDK 1:1); mocked here.
					app.getAudit().note(workflow == LivenessWorkflow.SUPERVISOR_AUTHENTICATION
							? "SUPERVISOR_AUTH_SUCCESS" : "OPERATOR_AUTH_SUCCESS", u.id, "USER_ID");
					onAuthenticated.accept(u);
				});
		faceArea.getChildren().setAll(face);
		face.startPreview();
	}

	/** Releases the camera; call when the page is left. */
	public void stop() {
		if (face != null) {
			face.stop();
		}
	}
}
