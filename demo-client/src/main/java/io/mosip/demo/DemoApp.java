package io.mosip.demo;

import java.awt.image.BufferedImage;
import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.sql.SQLException;
import java.util.Properties;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

import javax.imageio.ImageIO;

import io.mosip.extensions.liveness.api.LivenessWorkflow;
import io.mosip.registration.context.ApplicationContext;
import io.mosip.registration.controller.device.DemoGuardFactory;
import io.mosip.registration.controller.device.FaceLivenessGuard;
import io.mosip.registration.controller.device.Streamer;
import javafx.application.Application;
import javafx.application.Platform;
import javafx.embed.swing.SwingFXUtils;
import javafx.geometry.Insets;
import javafx.geometry.Pos;
import javafx.scene.Node;
import javafx.scene.Scene;
import javafx.scene.control.Button;
import javafx.scene.control.Label;
import javafx.scene.control.PasswordField;
import javafx.scene.control.ScrollPane;
import javafx.scene.control.TextField;
import javafx.scene.image.Image;
import javafx.scene.image.ImageView;
import javafx.scene.layout.BorderPane;
import javafx.scene.layout.HBox;
import javafx.scene.layout.Priority;
import javafx.scene.layout.Region;
import javafx.scene.layout.StackPane;
import javafx.scene.layout.VBox;
import javafx.stage.Stage;

/**
 * Look-alike of the MOSIP Desktop Registration Client for demonstrating face liveness without a MOSIP server.
 *
 * <p>The screens mirror the client's flows (operator login with face, operator onboarding, new registration with
 * resident face capture, operator authentication, supervisor approval), and every face step runs the client's own
 * face liveness code: {@link FaceLivenessGuard} on the frames of the client's {@link Streamer} from the SBI face
 * device, with the {@code LivenessOverlayPane} prompts, the {@code mosip.registration.face.liveness.*} global
 * parameters and the REG-EVT-104..109 audit events. What MOSIP's server would provide (users, roles, configuration)
 * is local, and packets are saved locally instead of uploaded; the 1:1 face match is mocked.
 */
public class DemoApp extends Application {

	static final String PREFIX = "mosip.registration.face.liveness.";

	private Path dataDir;
	private Streamer streamer;
	private MockMds mds;
	private DemoDb db;
	private DemoAudit audit;
	private DemoStore store;
	private FaceLivenessGuard guard;
	private final ExecutorService device = Executors.newSingleThreadExecutor(r -> {
		Thread t = new Thread(r, "demo-device");
		t.setDaemon(true);
		return t;
	});

	private Stage stage;
	private final BorderPane root = new BorderPane();
	private final Label userLabel = new Label();
	private final HBox headerRight = new HBox(14);
	private DemoStore.User user;
	private Runnable onLeave;

	public static void main(String[] args) {
		launch(args);
	}

	@Override
	public void start(Stage stage) throws Exception {
		this.stage = stage;
		dataDir = Paths.get(System.getProperty("demo.data", System.getProperty("user.home") + "/.mosip-demo"));
		Files.createDirectories(dataDir);

		db = new DemoDb(dataDir.resolve("db"));
		ApplicationContext.getInstance();
		loadConfig();

		streamer = new Streamer();
		audit = new DemoAudit(db);
		store = new DemoStore(dataDir, db);
		guard = DemoGuardFactory.create(streamer, audit);
		mds = new MockMds(System.getProperty("demo.mds.host", "127.0.0.1"),
				Integer.getInteger("demo.mds.port", 4501), streamer);

		root.setTop(header());
		Scene scene = new Scene(root, 1180, 820);
		scene.getStylesheets().add(getClass().getResource("/application.css").toExternalForm());
		scene.getStylesheets().add(getClass().getResource("/demo.css").toExternalForm());
		stage.setTitle("MOSIP Registration Client – Face Liveness (demo, no MOSIP server)");
		stage.setScene(scene);
		stage.show();
		showLogin();
	}

	@Override
	public void stop() {
		if (onLeave != null) {
			onLeave.run();
		}
		guard.destroy();
		mds.stopStream();
		device.shutdownNow();
		db.close();
	}

	// ------------------------------------------------------------------ shared

	public FaceLivenessGuard getGuard() {
		return guard;
	}

	public Streamer getStreamer() {
		return streamer;
	}

	public MockMds getMds() {
		return mds;
	}

	public DemoAudit getAudit() {
		return audit;
	}

	public DemoStore getStore() {
		return store;
	}

	public DemoStore.User getUser() {
		return user;
	}

	public DemoDb getDb() {
		return db;
	}

	public Path getDataDir() {
		return dataDir;
	}

	/** Device and other blocking work, one at a time (the face device serves one stream). */
	public void background(String name, Runnable work) {
		device.execute(() -> {
			try {
				work.run();
			} catch (RuntimeException e) {
				System.err.println(name + " failed: " + e);
			}
		});
	}

	static String workflowLabel(LivenessWorkflow workflow) {
		switch (workflow) {
		case RESIDENT_REGISTRATION:
			return "resident registration";
		case OPERATOR_AUTHENTICATION:
			return "operator authentication";
		default:
			return "supervisor authentication";
		}
	}

	/** Replaces the page; {@code leave} runs when the page is left (stops its camera). */
	public void show(Node page, Runnable leave) {
		if (onLeave != null) {
			onLeave.run();
		}
		onLeave = leave;
		ScrollPane scroll = new ScrollPane(page);
		scroll.setFitToWidth(true);
		scroll.getStyleClass().add("demo-scroll");
		root.setCenter(scroll);
	}

	static Image image(String name) {
		InputStream in = DemoApp.class.getResourceAsStream("/images/" + name);
		return in == null ? null : new Image(in);
	}

	/**
	 * Decodes a JPEG with ImageIO. JavaFX's own JPEG decoder fails in this process on Linux desktops where GTK
	 * loaded the system libjpeg-turbo first ("Wrong JPEG library version"); see {@link MockMds#startStream()}.
	 */
	static Image jpeg(byte[] bytes) {
		try {
			BufferedImage img = ImageIO.read(new ByteArrayInputStream(bytes));
			return img == null ? null : SwingFXUtils.toFXImage(img, null);
		} catch (IOException e) {
			return null;
		}
	}

	static Label title(String text) {
		Label l = new Label(text);
		l.getStyleClass().add("demo-title");
		return l;
	}

	static VBox card(Node... children) {
		VBox box = new VBox(14, children);
		box.getStyleClass().add("demo-card");
		box.setPadding(new Insets(24));
		return box;
	}

	static Button primary(String text) {
		Button b = new Button(text);
		b.getStyleClass().add("contiuneButton");
		b.setMinWidth(140);
		return b;
	}

	static Button secondary(String text) {
		Button b = new Button(text);
		b.getStyleClass().add("backButton");
		b.setMinWidth(120);
		return b;
	}

	/**
	 * Global parameters, as the client keeps them: in REG.GLOBAL_PARAM, loaded into the {@link ApplicationContext}
	 * map that the guard reads. {@code demo.properties} supplies the defaults; a key is only added when missing, so
	 * values saved on the Settings screen are kept across restarts.
	 */
	private void loadConfig() throws IOException, SQLException {
		Properties defaults = new Properties();
		try (InputStream in = getClass().getResourceAsStream("/demo.properties")) {
			if (in != null) {
				defaults.load(in);
			}
		}
		for (String key : defaults.stringPropertyNames()) {
			db.insertParamIfMissing(key, defaults.getProperty(key).trim());
		}
		db.params().forEach((k, v) -> ApplicationContext.map().put(k, v));
	}

	// ------------------------------------------------------------------ header

	private Node header() {
		ImageView logo = new ImageView(image("logo-final.png"));
		logo.setFitHeight(42);
		logo.setPreserveRatio(true);
		Label name = new Label("Registration Client");
		name.getStyleClass().add("demo-app-name");
		Label mode = new Label("OFFLINE DEMO · no MOSIP server");
		mode.setMinWidth(Region.USE_PREF_SIZE);
		name.setMinWidth(Region.USE_PREF_SIZE);
		mode.getStyleClass().add("demo-badge");
		Region grow = new Region();
		HBox.setHgrow(grow, Priority.ALWAYS);
		userLabel.getStyleClass().add("demo-header-text");
		headerRight.setAlignment(Pos.CENTER_RIGHT);
		HBox bar = new HBox(16, logo, name, mode, grow, headerRight);
		bar.setAlignment(Pos.CENTER_LEFT);
		bar.setPadding(new Insets(8, 18, 8, 18));
		bar.getStyleClass().add("headerParentBorder");
		return bar;
	}

	private void refreshHeader() {
		headerRight.getChildren().clear();
		if (user == null) {
			return;
		}
		userLabel.setText(user.name + " · " + user.id + " · " + (user.isSupervisor() ? "Supervisor" : "Officer")
				+ "\nCentre " + DemoStore.CENTER_ID + " · Machine " + DemoStore.MACHINE_ID);
		Button home = new Button("Home");
		home.getStyleClass().add("demo-header-button");
		home.setOnAction(e -> showHome());
		Button logout = new Button("Logout");
		logout.getStyleClass().add("demo-header-button");
		logout.setOnAction(e -> {
			audit.note("LOGOUT", user.id, "USER_ID");
			user = null;
			refreshHeader();
			showLogin();
		});
		home.setMinWidth(Region.USE_PREF_SIZE);
		logout.setMinWidth(Region.USE_PREF_SIZE);
		headerRight.getChildren().addAll(userLabel, home, logout);
	}

	// ------------------------------------------------------------------ login

	void showLogin() {
		TextField id = new TextField();
		id.setPromptText("User ID");
		id.getStyleClass().add("demoGraphicTextField");
		PasswordField pwd = new PasswordField();
		pwd.setPromptText("Password");
		pwd.getStyleClass().add("demoGraphicTextField");
		Label error = new Label();
		error.getStyleClass().add("demo-error");
		Button login = primary("Login");
		login.setDefaultButton(true);
		Label hint = new Label(usersHint());
		hint.getStyleClass().add("demo-small");
		hint.setWrapText(true);

		login.setOnAction(e -> {
			DemoStore.User u = store.authenticate(id.getText(), pwd.getText());
			if (u == null) {
				error.setText("Invalid user ID or password.");
				return;
			}
			if (store.isOnboarded(u.id)) {
				showFaceLogin(u);
			} else {
				showOnboarding(u);
			}
		});
		VBox box = card(title("Login"), new Label("Login with password, then face (with liveness)."), id, pwd, error,
				login, hint);
		box.setMaxWidth(420);
		show(center(box), null);
		Platform.runLater(id::requestFocus);
	}

	private String usersHint() {
		StringBuilder sb = new StringBuilder("Demo users: ");
		for (DemoStore.Seed u : store.seeds()) {
			sb.append(u.id).append(" / ").append(u.password).append(" (")
					.append(u.roles.contains(DemoStore.ROLE_SUPERVISOR) ? "supervisor" : "officer").append(")   ");
		}
		return sb.toString().trim();
	}

	/** MOSIP: a user new to this machine is onboarded first; their face is captured with liveness. */
	private void showOnboarding(DemoStore.User u) {
		FaceCapturePane[] pane = new FaceCapturePane[1];
		Button next = primary("Continue to Home");
		next.setDisable(true);
		pane[0] = new FaceCapturePane(this, LivenessWorkflow.OPERATOR_AUTHENTICATION,
				"Operator onboarding: " + u.name + " is new to this machine. Look at the camera and press Capture; "
						+ "follow the on-screen prompts.",
				() -> u.id, (jpeg, verdict) -> {
					try {
						store.onboard(u.id, jpeg);
						audit.note("OPERATOR_ONBOARDED", u.id, "USER_ID");
						next.setDisable(false);
					} catch (IOException ex) {
						System.err.println("onboarding failed: " + ex);
					}
				});
		next.setOnAction(e -> loggedIn(u));
		Button back = secondary("Back");
		back.setOnAction(e -> showLogin());
		VBox box = card(title("Operator onboarding"), pane[0], buttons(back, next));
		box.setMaxWidth(640);
		show(center(box), pane[0]::stop);
		pane[0].startPreview();
	}

	private void showFaceLogin(DemoStore.User u) {
		Label match = new Label();
		FaceCapturePane[] pane = new FaceCapturePane[1];
		pane[0] = new FaceCapturePane(this, LivenessWorkflow.OPERATOR_AUTHENTICATION,
				"Face login for " + u.name + ". Look at the camera and press Capture; follow the on-screen prompts.",
				() -> u.id, (jpeg, verdict) -> {
					// MOSIP matches against the operator's onboarded face with the BioSDK; mocked here.
					match.setText("Face matched with onboarded operator (mock 1:1 match).");
					match.getStyleClass().add("demo-ok");
					loggedIn(u);
				});
		Button back = secondary("Back");
		back.setOnAction(e -> showLogin());
		VBox box = card(title("Login – face authentication"), pane[0], match, buttons(back));
		box.setMaxWidth(640);
		show(center(box), pane[0]::stop);
		pane[0].startPreview();
	}

	private void loggedIn(DemoStore.User u) {
		user = u;
		audit.note("LOGIN_SUCCESS", u.id, "USER_ID");
		refreshHeader();
		showHome();
	}

	// ------------------------------------------------------------------ home

	void showHome() {
		Node newReg = tile("RegisterIndividual.png", "New Registration", "Register a resident (demographics + face)",
				() -> new RegistrationScreen(this).show());
		Node approval = tile("PendingApproval.png", "Pending Approval", user.isSupervisor()
				? "Review registrations; supervisor face authentication"
				: "Supervisor role required (login as a supervisor)",
				() -> new ApprovalScreen(this).show());
		approval.setDisable(!user.isSupervisor());
		Node settings = tile("globalconfigs.png", "Settings & Diagnostics",
				"Liveness policy per workflow, device and engine diagnostics, metrics", () -> new SettingsScreen(this).show());
		Node auditTile = tile("userdetails.png", "Audit Log", "Face liveness audit events (REG-EVT-104…109)",
				() -> new AuditScreen(this).show());
		HBox row1 = new HBox(24, newReg, approval);
		HBox row2 = new HBox(24, settings, auditTile);
		row1.setAlignment(Pos.CENTER);
		row2.setAlignment(Pos.CENTER);
		VBox page = new VBox(24, title("Home"), row1, row2);
		page.setPadding(new Insets(30));
		page.setAlignment(Pos.TOP_CENTER);
		show(page, null);
	}

	private Node tile(String icon, String name, String description, Runnable action) {
		ImageView iv = new ImageView(image(icon));
		iv.setFitHeight(64);
		iv.setPreserveRatio(true);
		Label n = new Label(name);
		n.getStyleClass().add("demo-tile-title");
		Label d = new Label(description);
		d.setWrapText(true);
		d.getStyleClass().add("demo-small");
		VBox box = new VBox(10, iv, n, d);
		box.setAlignment(Pos.CENTER);
		box.setPrefSize(300, 190);
		box.getStyleClass().add("demo-tile");
		box.setOnMouseClicked(e -> action.run());
		return box;
	}

	static HBox buttons(Node... nodes) {
		HBox box = new HBox(12, nodes);
		box.setAlignment(Pos.CENTER_RIGHT);
		return box;
	}

	static Node center(Node n) {
		StackPane p = new StackPane(n);
		p.setPadding(new Insets(30));
		StackPane.setAlignment(n, Pos.TOP_CENTER);
		return p;
	}
}
