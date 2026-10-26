#!/usr/bin/env bash
# Starts the local liveness service (127.0.0.1:50052; it runs passive, active and hybrid sessions)
# and MockMDS (127.0.0.1:4501, purpose Registration). Logs and PIDs go to .run/.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/env.sh"
mkdir -p "$RUN_DIR"

if port_open "$LIVENESS_PORT"; then
  echo "liveness service: port $LIVENESS_PORT already in use, not starting another"
else
  [ -x "$PASSIVE_PY" ] || { echo "conda env face-liveness-passive not found ($PASSIVE_PY)" >&2; exit 1; }
  # exec: the recorded PID is the server itself, not a wrapper shell
  (cd "$REPO/face-liveness-passive" && exec nohup "$PASSIVE_PY" -m passive_liveness.server) > "$RUN_DIR/passive.log" 2>&1 &
  echo $! > "$RUN_DIR/passive.pid"
fi

if port_open "$MDS_PORT"; then
  echo "MockMDS: port $MDS_PORT already in use, not starting another"
else
  use_jdk11
  JAR="$(ls "$MOCKMDS_DIR"/target/mock-mds-*.jar | grep -v -e sources -e javadoc | head -1)"
  # Run from target/: MockMDS resolves "Biometric Devices/..." and "Profile/..." against its working directory.
  (cd "$MOCKMDS_DIR/target" && exec nohup java -cp "$JAR:lib/*" io.mosip.mock.sbi.test.TestMockSBI \
      "mosip.mock.sbi.device.purpose=${MDS_PURPOSE:-Registration}" "mosip.mock.sbi.biometric.type=Biometric Device") \
      > "$RUN_DIR/mockmds.log" 2>&1 &
  echo $! > "$RUN_DIR/mockmds.pid"
fi

for _ in $(seq 1 60); do
  port_open "$LIVENESS_PORT" && port_open "$MDS_PORT" && break
  sleep 1
done
port_open "$LIVENESS_PORT" && echo "liveness service: up on 127.0.0.1:$LIVENESS_PORT" || { echo "liveness service did not start, see $RUN_DIR/passive.log"; exit 1; }
port_open "$MDS_PORT" && echo "MockMDS:          up on 127.0.0.1:$MDS_PORT" || { echo "MockMDS did not start, see $RUN_DIR/mockmds.log"; exit 1; }

# MockMDS ships with mosip.mock.sbi.quality.score=44, below the client's thresholds (iris 60, face 90).
# Raise it for every modality through MockMDS's own admin API.
curl -sf -X POST "http://127.0.0.1:$MDS_PORT/admin/score" -H 'Content-Type: application/json' \
  -d "{\"type\":\"Biometric Device\",\"qualityScore\":\"${MDS_QUALITY_SCORE:-95}\",\"fromIso\":false}" > /dev/null \
  && echo "MockMDS:          quality score set to ${MDS_QUALITY_SCORE:-95}" \
  || echo "MockMDS:          could not set quality score, see $RUN_DIR/mockmds.log"
