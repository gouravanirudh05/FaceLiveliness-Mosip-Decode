package io.mosip.demo;

import java.awt.image.BufferedImage;
import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.ScheduledFuture;
import java.util.concurrent.TimeUnit;
import java.util.function.Supplier;

import javax.imageio.ImageIO;

import io.mosip.extensions.liveness.api.LivenessWorkflow;
import io.mosip.registration.controller.device.FaceLivenessGuard;
import io.mosip.registration.controller.device.LivenessOverlayPane;
import javafx.application.Platform;
import javafx.concurrent.Task;
import javafx.embed.swing.SwingFXUtils;
import javafx.geometry.Insets;
import javafx.geometry.Pos;
import javafx.scene.control.Button;
import javafx.scene.control.Label;
import javafx.scene.image.Image;
import javafx.scene.image.ImageView;
import javafx.scene.layout.HBox;
import javafx.scene.layout.StackPane;
import javafx.scene.layout.VBox;

/**
 * Face preview with the client's {@link LivenessOverlayPane} on top and a Capture button, as on the client's
 * biometric capture and face authentication screens. Capture runs {@link FaceLivenessGuard#verify} for the given
 * workflow on the live device stream; only when it allows the capture is the face taken, exactly where the patched
 * client calls the guard before rCapture.
 */
public class FaceCapturePane extends VBox {

	/** Called on the JavaFX thread with the captured face once liveness allowed it. */
	public interface Captured {
		void accept(byte[] jpeg, FaceLivenessGuard.Verdict verdict);
	}

	private static final double W = 520;
	private static final double H = 390;

	private final DemoApp app;
	private final LivenessWorkflow workflow;
	private final Supplier<String> subjectId;
	private final Captured onCaptured;

	private final ImageView preview = new ImageView();
	private final LivenessOverlayPane overlay = new LivenessOverlayPane();
	private final Label placeholder = new Label("Starting the face camera…");
	private final Label message = new Label();
	private final Button capture = new Button("Capture");
	private final Button restart = new Button("Restart camera");
	private volatile boolean running;
	private volatile boolean closed;
	private ScheduledFuture<?> refresh;
	private volatile Task<FaceLivenessGuard.Verdict> task;
	private volatile byte[] shown;

	/** Draws the stream: decodes the Streamer's latest frame with ImageIO (see {@link MockMds#startStream()}). */
	private static final ScheduledExecutorService PREVIEW = Executors.newSingleThreadScheduledExecutor(r -> {
		Thread t = new Thread(r, "face-preview-render");
		t.setDaemon(true);
		return t;
	});

	public FaceCapturePane(DemoApp app, LivenessWorkflow workflow, String instruction, Supplier<String> subjectId,
			Captured onCaptured) {
		this.app = app;
		this.workflow = workflow;
		this.subjectId = subjectId;
		this.onCaptured = onCaptured;

		setSpacing(10);
		setAlignment(Pos.TOP_CENTER);

		Label hint = new Label(instruction);
		hint.getStyleClass().add("demo-hint");
		hint.setWrapText(true);

		preview.setFitWidth(W);
		preview.setFitHeight(H);
		preview.setPreserveRatio(true);
		placeholder.getStyleClass().add("demo-placeholder");
		StackPane screen = new StackPane(placeholder, preview, overlay);
		screen.setMinSize(W, H);
		screen.setMaxSize(W, H);
		screen.getStyleClass().add("demo-preview");
		preview.imageProperty().addListener((o, a, b) -> placeholder.setVisible(b == null));

		message.setWrapText(true);
		message.setMaxWidth(W);
		message.getStyleClass().add("demo-message");

		capture.getStyleClass().add("contiuneButton");
		capture.setPrefWidth(160);
		capture.setOnAction(e -> capture());
		restart.getStyleClass().add("backButton");
		restart.setOnAction(e -> startPreview());
		HBox buttons = new HBox(12, restart, capture);
		buttons.setAlignment(Pos.CENTER);

		Label policy = new Label("Liveness policy: " + DemoApp.workflowLabel(workflow));
		policy.getStyleClass().add("demo-small");

		getChildren().addAll(hint, screen, message, buttons, policy);
		setPadding(new Insets(4));
	}

	/** Starts the device preview; call when the screen is shown. */
	public void startPreview() {
		closed = false;
		message.setText("");
		message.getStyleClass().removeAll("demo-error", "demo-ok");
		preview.setImage(null);
		placeholder.setText("Starting the face camera…");
		capture.setDisable(true);
		restart.setDisable(true);
		startRendering();
		app.background("face-preview", () -> {
			try {
				app.getMds().startStream();
				Platform.runLater(() -> capture.setDisable(running));
			} catch (IOException e) {
				Platform.runLater(() -> {
					placeholder.setText("No face camera");
					error("The face camera is not available (" + app.getMds().endpoint() + "). Start MockMDS and the "
							+ "webcam feeder, then press Restart camera.");
				});
			} finally {
				Platform.runLater(() -> restart.setDisable(running));
			}
		});
	}

	/** Cancels a running liveness session and releases the device; call when leaving the screen. */
	public void stop() {
		closed = true;
		stopRendering();
		app.getGuard().cancelActive();
		Task<FaceLivenessGuard.Verdict> session = task;
		app.background("face-stop", () -> {
			// Let the cancelled session finish first: a stream stopped under a running session would be reported
			// (and audited) as a device error. Runs on the device thread, so the next screen's preview starts after.
			if (session != null) {
				try {
					session.get(5, TimeUnit.SECONDS);
				} catch (Exception ignored) {
					// cancelled, failed or slow: stop the device anyway
				}
			}
			app.getMds().stopStream();
		});
	}

	private synchronized void startRendering() {
		if (refresh != null) {
			return;
		}
		refresh = PREVIEW.scheduleWithFixedDelay(() -> {
			byte[] frame = app.getStreamer().getStreamImageBytes();
			if (frame == null || frame == shown) {
				return; // no new frame; a stopped stream keeps showing the last (captured) face
			}
			shown = frame;
			try {
				BufferedImage img = ImageIO.read(new ByteArrayInputStream(frame));
				if (img != null) {
					Image fx = SwingFXUtils.toFXImage(img, null);
					Platform.runLater(() -> preview.setImage(fx));
				}
			} catch (IOException | RuntimeException e) {
				// skip an unreadable frame; the guard reports a stream of invalid frames as a device error
			}
		}, 0, 50, TimeUnit.MILLISECONDS);
	}

	private synchronized void stopRendering() {
		if (refresh != null) {
			refresh.cancel(false);
			refresh = null;
		}
	}

	private void capture() {
		running = true;
		capture.setDisable(true);
		restart.setDisable(true);
		message.setText("");
		message.getStyleClass().removeAll("demo-error", "demo-ok");
		String subject = subjectId.get();
		Task<FaceLivenessGuard.Verdict> task = new Task<FaceLivenessGuard.Verdict>() {
			@Override
			protected FaceLivenessGuard.Verdict call() {
				return app.getGuard().verify(workflow, overlay, () -> {
					try {
						app.getMds().startStream();
					} catch (IOException e) {
						// the guard reports the missing frames as a device error
					}
				}, subject);
			}
		};
		this.task = task;
		task.setOnSucceeded(e -> done(task.getValue(), subject));
		task.setOnFailed(e -> {
			running = false;
			if (closed) {
				return;
			}
			error("Face verification could not be completed. Please try again.");
			capture.setDisable(false);
			restart.setDisable(false);
		});
		Thread t = new Thread(task, "liveness-" + workflow);
		t.setDaemon(true);
		t.start();
	}

	private void done(FaceLivenessGuard.Verdict verdict, String subject) {
		running = false;
		app.background("liveness-result", () -> app.getStore().recordLiveness(workflow, subject, verdict));
		if (closed) {
			return;
		}
		if (verdict.isAllowed()) {
			byte[] face = app.getStreamer().getStreamImageBytes();
			if (face == null) {
				error("No image was received from the face camera. Please try again.");
				capture.setDisable(false);
				restart.setDisable(false);
				return;
			}
			app.background("face-stop", () -> app.getMds().stopStream()); // freeze the preview on the captured face
			ok(verdict.isSkipped() ? "Face captured (liveness disabled for this workflow by configuration)."
					: "Good, face captured successfully.");
			capture.setText("Recapture");
			capture.setOnAction(e -> {
				capture.setText("Capture");
				capture.setOnAction(x -> capture());
				startPreview();
			});
			capture.setDisable(false);
			restart.setDisable(true);
			onCaptured.accept(face, verdict);
			return;
		}
		if (verdict.isBlocked()) {
			error(verdict.getUserMessage());
			capture.setDisable(true);
			restart.setDisable(true);
			return;
		}
		if (verdict.isDeviceError()) {
			error(verdict.getUserMessage());
			app.background("face-stop", () -> app.getMds().stopStream());
			capture.setDisable(true);
			restart.setDisable(false);
			return;
		}
		String text = verdict.getUserMessage();
		error(text != null && text.contains("recovery") ? text
				: text + "  Make sure your face is well lit and fully visible, then press Capture.");
		capture.setText("Try again");
		capture.setDisable(false);
		restart.setDisable(false);
	}

	private void error(String text) {
		message.getStyleClass().removeAll("demo-error", "demo-ok");
		message.getStyleClass().add("demo-error");
		message.setText(text);
	}

	private void ok(String text) {
		message.getStyleClass().removeAll("demo-error", "demo-ok");
		message.getStyleClass().add("demo-ok");
		message.setText(text);
	}
}
