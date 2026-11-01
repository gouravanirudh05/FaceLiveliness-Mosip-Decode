#!/usr/bin/env bash
# Starts:
#   Active liveness  - configured by ACTIVE_LIVENESS_PORT
#   Passive liveness - configured by LIVENESS_PORT
#   MockMDS          - configured by MDS_PORT
#
# Logs and PIDs are stored in .run/.

set -euo pipefail

# Resolve the repository root from this script's location.
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd -- "$SCRIPT_DIR/../../" && pwd)"
echo "Using repository root: $REPO"
# Runtime files.
RUN_DIR="$REPO/.run"

# Service configuration.
LIVENESS_PORT="${LIVENESS_PORT:-50052}"
ACTIVE_LIVENESS_PORT="${ACTIVE_LIVENESS_PORT:-50051}"
MDS_PORT="${MDS_PORT:-4501}"
MDS_PURPOSE="${MDS_PURPOSE:-Registration}"

# Project directories.
MOCKMDS_DIR="${MOCKMDS_DIR:-$REPO/mosip/mock-mds}"

mkdir -p "$RUN_DIR"

# Check whether a TCP port is accepting connections.
port_open() {
  local port="$1"
  (echo > "/dev/tcp/127.0.0.1/$port") >/dev/null 2>&1
}

use_jdk11() {
  export JAVA_HOME=/usr/lib/jvm/java-11-openjdk-amd64
  export PATH="$JAVA_HOME/bin:$PATH"
}

start_liveness_service() {
  local name="$1"
  local port="$2"
  local module="$3"
  local log="$RUN_DIR/${name}.log"
  local pidfile="$RUN_DIR/${name}.pid"

  if port_open "$port"; then
    echo "$name: port $port already in use, not starting another"
    return
  fi

  command -v uv >/dev/null 2>&1 || {
    echo "uv not found; install uv before starting liveness services" >&2
    exit 1
  }

  [ -f "$REPO/face-liveness-passive/pyproject.toml" ] || {
    echo "UV project not found: $REPO/face-liveness-passive/pyproject.toml" >&2
    exit 1
  }

  (
    cd "$REPO/face-liveness-passive"
    exec nohup uv run --active python -m "$module"
  ) > "$log" 2>&1 &

  echo $! > "$pidfile"
  echo "$name: starting on port $port"
}

# Start active and passive liveness.
# ACTIVE_LIVENESS_PORT must match active_liveness.server configuration.
start_liveness_service \
  "active" "${ACTIVE_LIVENESS_PORT:?Set ACTIVE_LIVENESS_PORT}" \
  "active_liveness.server"

start_liveness_service \
  "passive" "$LIVENESS_PORT" \
  "passive_liveness.server"

# Start MockMDS.
if port_open "$MDS_PORT"; then
  echo "MockMDS: port $MDS_PORT already in use, not starting another"
else
  use_jdk11

  JAR="$(find "$MOCKMDS_DIR/target" -maxdepth 1 \
    -type f -name 'mock-mds-*.jar' \
    ! -name '*-sources.jar' \
    ! -name '*-javadoc.jar' \
    | head -1)"

  if [ -z "$JAR" ]; then
    echo "MockMDS JAR not found in $MOCKMDS_DIR/target" >&2
    echo "Build MockMDS first." >&2
    exit 1
  fi

  (
    cd "$MOCKMDS_DIR/target"
    exec nohup java -cp "$JAR:lib/*" \
      io.mosip.mock.sbi.test.TestMockSBI \
      "mosip.mock.sbi.device.purpose=${MDS_PURPOSE:-Registration}" \
      "mosip.mock.sbi.biometric.type=Biometric Device"
  ) > "$RUN_DIR/mockmds.log" 2>&1 &

  echo $! > "$RUN_DIR/mockmds.pid"
  echo "MockMDS: starting on port $MDS_PORT"
fi

# # Wait for all services to become available.
# for _ in $(seq 1 20); do
#   if port_open "$ACTIVE_LIVENESS_PORT" &&
#      port_open "$LIVENESS_PORT" &&
#      port_open "$MDS_PORT"; then
#     break
#   fi
#   sleep 1
# done

check_service() {
  local name="$1"
  local port="$2"
  local log="$3"

  if port_open "$port"; then
    echo "$name: up on 127.0.0.1:$port"
  else
    echo "$name did not start; check $log"
    return 1
  fi
}

# check_service "Active liveness" "$ACTIVE_LIVENESS_PORT" "$RUN_DIR/active.log"
# check_service "Passive liveness" "$LIVENESS_PORT" "$RUN_DIR/passive.log"
# check_service "MockMDS" "$MDS_PORT" "$RUN_DIR/mockmds.log"