package io.mosip.demo;

import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.Base64;
import java.util.concurrent.TimeUnit;

import org.apache.http.client.methods.CloseableHttpResponse;
import org.apache.http.client.methods.RequestBuilder;
import org.apache.http.entity.ContentType;
import org.apache.http.entity.StringEntity;
import org.apache.http.impl.client.CloseableHttpClient;
import org.apache.http.impl.client.HttpClients;
import org.apache.http.util.EntityUtils;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

import io.mosip.registration.controller.device.Streamer;
import io.mosip.registration.mdm.dto.MdmBioDevice;
import javafx.scene.image.ImageView;

/**
 * The face device over SBI 0.9.5 (MOSIP MockMDS on 127.0.0.1:4501, fed by the webcam): discovery and the
 * registration preview stream, requested the same way as the client's SBI provider (HTTP method STREAM). The frames
 * go through the client's own {@link Streamer}, which hands them to the face liveness guard.
 */
public class MockMds {

	private static final ObjectMapper JSON = new ObjectMapper();

	private final String host;
	private final int port;
	private final Streamer streamer;
	private CloseableHttpClient streamClient;

	public MockMds(String host, int port, Streamer streamer) {
		this.host = host;
		this.port = port;
		this.streamer = streamer;
	}

	public String endpoint() {
		return host + ":" + port;
	}

	/**
	 * Starts the face stream unless it is already running. Blocking (waits up to 10 s while the device is still busy
	 * with a previous stream); call it off the JavaFX thread.
	 *
	 * <p>The Streamer also decodes every frame into an ImageView with JavaFX's native JPEG decoder; on Linux
	 * desktops where GTK has already loaded the system libjpeg-turbo, that decoder fails ("Wrong JPEG library
	 * version"), so the Streamer gets a sink view and the preview is drawn by {@link FaceCapturePane} from
	 * {@link Streamer#getStreamImageBytes()}.
	 */
	public synchronized void startStream() throws IOException {
		if (streamer.isStreaming()) {
			return;
		}
		streamer.startStream(openFaceStream(), sink, null);
	}

	private final ImageView sink = new ImageView();

	public synchronized void stopStream() {
		streamer.stop();
		streamer.setUrlStream(null);
		closeQuietly();
	}

	public boolean isStreaming() {
		return streamer.isStreaming();
	}

	/**
	 * MockMDS keeps the device busy after a stream is closed until its next frame write fails, and meanwhile
	 * answers STREAM with a JSON error (111, device busy) instead of a multipart stream: retry until released.
	 */
	private InputStream openFaceStream() throws IOException {
		long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(10);
		while (true) {
			closeQuietly();
			streamClient = HttpClients.createDefault();
			CloseableHttpResponse response = streamClient.execute(RequestBuilder.create("STREAM")
					.setUri("http://" + host + ":" + port + "/stream")
					.setEntity(new StringEntity("{\"deviceId\":\"3\",\"deviceSubId\":\"0\",\"timeout\":\"120000\"}",
							ContentType.APPLICATION_JSON))
					.build());
			String type = response.getFirstHeader("Content-Type") == null ? ""
					: response.getFirstHeader("Content-Type").getValue();
			if (type.startsWith("multipart/")) {
				return response.getEntity().getContent();
			}
			String body = EntityUtils.toString(response.getEntity());
			if (System.nanoTime() > deadline) {
				closeQuietly();
				throw new IOException("Face device did not start streaming: " + body);
			}
			try {
				Thread.sleep(200);
			} catch (InterruptedException e) {
				Thread.currentThread().interrupt();
				throw new IOException("interrupted", e);
			}
		}
	}

	private void closeQuietly() {
		if (streamClient != null) {
			try {
				streamClient.close();
			} catch (IOException ignored) {
				// closing anyway
			}
			streamClient = null;
		}
	}

	/** MOSIPDISC for a face device; null when the SBI service is not reachable or has no face device. */
	public MdmBioDevice discoverFace() {
		try (CloseableHttpClient http = HttpClients.createDefault();
				CloseableHttpResponse response = http.execute(RequestBuilder.create("MOSIPDISC")
						.setUri("http://" + host + ":" + port + "/device")
						.setEntity(new StringEntity("{\"type\":\"Face\"}", ContentType.APPLICATION_JSON))
						.build())) {
			JsonNode devices = JSON.readTree(EntityUtils.toString(response.getEntity()));
			for (JsonNode d : devices) {
				MdmBioDevice device = new MdmBioDevice();
				device.setDeviceId(d.path("deviceId").asText());
				device.setDeviceStatus(d.path("deviceStatus").asText());
				device.setPurpose(d.path("purpose").asText());
				device.setSpecVersion(d.path("specVersion").path(0).asText());
				device.setCertification(d.path("certification").asText());
				device.setPort(port);
				JsonNode digitalId = digitalId(d.path("digitalId").asText());
				device.setDeviceMake(digitalId.path("make").asText("unknown"));
				device.setDeviceModel(digitalId.path("model").asText(""));
				device.setDeviceType(digitalId.path("type").asText("Face"));
				device.setDeviceProviderName(digitalId.path("deviceProvider").asText(""));
				if ("Face".equalsIgnoreCase(device.getDeviceType())) {
					return device;
				}
			}
		} catch (Exception e) {
			return null;
		}
		return null;
	}

	/** The digital ID is a JWT (L1) or plain base64 JSON (L0); either way its payload is JSON. */
	private static JsonNode digitalId(String value) {
		try {
			String[] parts = value.split("\\.");
			String payload = parts.length == 3 ? parts[1] : value;
			return JSON.readTree(new String(Base64.getUrlDecoder().decode(payload.replace('+', '-').replace('/', '_')
					.replace("=", "")), StandardCharsets.UTF_8));
		} catch (Exception e) {
			return JSON.createObjectNode();
		}
	}
}
