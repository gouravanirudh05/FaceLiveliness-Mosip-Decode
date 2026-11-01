
#!/usr/bin/env python3
"""
Browser Webcam Streaming Server

Run:
    pip install flask flask-sock opencv-python numpy

    python webcam_server.py

Open:
    http://localhost:5000

For another device on your LAN, use:
    http://<server-ip>:5000

Note: Browser webcam access requires HTTPS except on localhost.
"""

from __future__ import annotations

import argparse
import threading
import time
from pathlib import Path

import cv2
import numpy as np
from flask import Flask, Response, jsonify, render_template_string
from flask_sock import Sock

app = Flask(__name__)
sock = Sock(app)

latest_frame = None
latest_jpeg = None
frame_lock = threading.Lock()

frame_count = 0
last_frame_time = 0.0
recording = False
writer = None

REPO = Path(__file__).resolve().parents[2]
DEFAULT_TARGET = REPO / "mosip/mosip-mock-services/MockMDS/target/Biometric Devices/Face/Stream Image/0.jpeg"

JPEG_OUTPUT_PATH = Path(DEFAULT_TARGET)
# Temporary file in the SAME directory (required for atomic replacement)
JPEG_TEMP_PATH = JPEG_OUTPUT_PATH.with_name(
    JPEG_OUTPUT_PATH.stem + ".tmp.jpg"
)
def save_jpeg_atomic(frame):
    """
    Save JPEG atomically.

    Readers will see either the previous complete image
    or the new complete image.
    """
    success = cv2.imwrite(
        str(JPEG_TEMP_PATH),
        frame,
        [cv2.IMWRITE_JPEG_QUALITY, 90]
    )

    if not success:
        raise IOError("Failed to encode JPEG")

    # Atomic replacement on the same filesystem
    JPEG_TEMP_PATH.replace(JPEG_OUTPUT_PATH)

HTML = r"""
<!DOCTYPE html>
<html>
<head>
    <title>Webcam Streaming Server</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body {
            font-family: Arial, sans-serif;
            background: #111827;
            color: white;
            text-align: center;
            padding: 25px;
        }
        .container {
            max-width: 800px;
            margin: auto;
        }
        video {
            width: 100%;
            background: black;
            border-radius: 12px;
        }
        button {
            padding: 12px 22px;
            margin: 8px;
            border: 0;
            border-radius: 8px;
            cursor: pointer;
            font-size: 15px;
        }
        .start { background: #16a34a; color: white; }
        .stop { background: #dc2626; color: white; }
        .status {
            margin: 18px;
            color: #9ca3af;
        }
    </style>
</head>
<body>
<div class="container">
    <h2>Browser Webcam Server</h2>

    <video id="video" autoplay playsinline muted></video>

    <div>
        <button class="start" onclick="startCamera()">Start Camera</button>
        <button class="stop" onclick="stopCamera()">Stop Camera</button>
    </div>

    <div class="status" id="status">Disconnected</div>
    <div id="stats"></div>
</div>

<script>
let stream = null;
let socket = null;
let running = false;

const video = document.getElementById("video");
const statusText = document.getElementById("status");
const stats = document.getElementById("stats");

async function startCamera() {
    try {
        stream = await navigator.mediaDevices.getUserMedia({
            video: {
                width: { ideal: 640 },
                height: { ideal: 480 },
                frameRate: { ideal: 25 }
            },
            audio: false
        });

        video.srcObject = stream;
        await video.play();

        const protocol = location.protocol === "https:" ? "wss:" : "ws:";
        socket = new WebSocket(
            protocol + "//" + location.host + "/stream"
        );

        socket.binaryType = "arraybuffer";

        socket.onopen = () => {
            running = true;
            statusText.textContent = "Connected - Streaming";
            sendFrames();
        };

        socket.onclose = () => {
            running = false;
            statusText.textContent = "Disconnected";
        };

        socket.onerror = () => {
            statusText.textContent = "WebSocket error";
        };

    } catch (err) {
        statusText.textContent = "Camera error: " + err.message;
    }
}

async function sendFrames() {
    const canvas = document.createElement("canvas");
    const ctx = canvas.getContext("2d");

    canvas.width = 640;
    canvas.height = 480;

    while (running && socket && socket.readyState === WebSocket.OPEN) {
        if (video.readyState >= 2 && socket.bufferedAmount < 500000) {
            ctx.drawImage(video, 0, 0, 640, 480);

            const blob = await new Promise(resolve =>
                canvas.toBlob(resolve, "image/jpeg", 0.85)
            );

            if (blob && running && socket.readyState === WebSocket.OPEN) {
                socket.send(await blob.arrayBuffer());
            }
        }

        await new Promise(resolve => setTimeout(resolve, 40));
    }
}

function stopCamera() {
    running = false;

    if (socket) {
        socket.close();
        socket = null;
    }

    if (stream) {
        stream.getTracks().forEach(track => track.stop());
        stream = null;
    }

    video.srcObject = null;
    statusText.textContent = "Stopped";
}

window.addEventListener("beforeunload", stopCamera);
</script>
</body>
</html>
"""


@app.route("/")
def index():
    return render_template_string(HTML)


@app.route("/snapshot")
def snapshot():
    with frame_lock:
        data = latest_jpeg

    if data is None:
        return "No frame received", 404

    return Response(data, mimetype="image/jpeg")


@app.route("/stats")
def stats_endpoint():
    with frame_lock:
        return jsonify({
            "frames": frame_count,
            "last_frame_time": last_frame_time,
            "recording": recording,
        })


@sock.route("/stream")
def stream(ws):
    global latest_frame, latest_jpeg
    global frame_count, last_frame_time

    while True:
        data = ws.receive()

        if data is None:
            break

        if not isinstance(data, bytes):
            continue

        arr = np.frombuffer(data, dtype=np.uint8)
        frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)

        if frame is None:
            continue

        # Update latest frame in memory
        with frame_lock:
            latest_frame = frame
            latest_jpeg = data
            frame_count += 1
            last_frame_time = time.time()

        try:
            save_jpeg_atomic(frame)
        except Exception as exc:
            print(f"JPEG save error: {exc}")

        # Existing recording functionality
        if recording and writer is not None:
            writer.write(frame)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=5000)
    args = parser.parse_args()

    print(f"Webcam server: http://localhost:{args.port}")
    print("Open the address in your browser and click Start Camera.")

    app.run(
        host=args.host,
        port=args.port,
        threaded=True,
        debug=False,
    )


if __name__ == "__main__":
    main()
