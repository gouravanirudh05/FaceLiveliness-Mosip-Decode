#!/usr/bin/env bash
# Runs the look-alike Registration Client: the client's own face liveness code (FaceLivenessGuard, Streamer,
# LivenessOverlayPane) in resident / operator / supervisor flows, without a MOSIP server.
# Start mosip/scripts/start-services.sh (engine + MockMDS) and, for a live camera, mosip/scripts/run-webcam-device.sh.
#
# Data: the Derby database and face images go to demo-client/data (override with DEMO_DATA=DIR; delete the folder
# to start over). Extra JVM options, e.g. -Ddemo.mds.port=PORT, go in JAVA_OPTS.
set -euo pipefail
DEMO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$DEMO_DIR/../mosip/scripts/env.sh"
use_jdk11

CLIENT_DIR="$RC_DIR/registration-client"
CLIENT_JAR="$CLIENT_DIR/target/registration-client-1.2.0.2.jar"
DEMO_JAR="$DEMO_DIR/target/liveness-demo-client-0.1.0-SNAPSHOT.jar"
DATA_DIR="${DEMO_DATA:-$DEMO_DIR/data}"
[ -f "$CLIENT_JAR" ] || { echo "$CLIENT_JAR not found; run mosip/scripts/setup.sh first" >&2; exit 1; }

port_open "$LIVENESS_PORT" || echo "WARNING: liveness engine not listening on $LIVENESS_PORT (start-services.sh)" >&2
port_open "$MDS_PORT" || echo "WARNING: MockMDS not listening on $MDS_PORT (start-services.sh)" >&2

# The demo compiles against the patched client jar; make sure ~/.m2 has that one, then build if sources changed.
M2_JAR="$HOME/.m2/repository/io/mosip/registration/registration-client/1.2.0.2/registration-client-1.2.0.2.jar"
if ! cmp -s "$CLIENT_JAR" "$M2_JAR"; then
  (cd "$CLIENT_DIR" && mvn -B -q -o install:install-file -Dfile="$CLIENT_JAR" -DpomFile=pom.xml)
fi
if [ ! -f "$DEMO_JAR" ] || [ -n "$(find "$DEMO_DIR/src" "$DEMO_DIR/pom.xml" -newer "$DEMO_JAR" -print -quit)" ]; then
  (cd "$DEMO_DIR" && mvn -B -q -o package)
fi

mkdir -p "$DATA_DIR"
FX="$(ls "$CLIENT_DIR"/target/lib/javafx-*-11.0.2-linux.jar | tr '\n' ':')"
# shellcheck disable=SC2086
exec java "-Ddemo.data=$DATA_DIR" ${JAVA_OPTS:-} --module-path "$FX" \
  --add-modules=javafx.controls,javafx.fxml,javafx.base,javafx.web,javafx.swing,javafx.graphics \
  -cp "$DEMO_JAR:$CLIENT_JAR:$CLIENT_DIR/target/lib/*" io.mosip.demo.DemoApp "$@"
