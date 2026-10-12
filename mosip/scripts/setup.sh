#!/usr/bin/env bash
# One-time setup of the MOSIP side: submodules + integration patches, JDK 11, and the three Java builds.
#   1. git submodules (registration-client, mosip-mock-services: release-1.2.0.x; android-registration-client:
#      release-1.2.x). Each MOSIP client gets a local branch face-liveness; on a fresh clone it is created from
#      mosip/patches/<client>-face-liveness.patch (the MOSIP repos are upstream, so the changes travel as patches)
#   2. JDK 11 (Temurin) into ~/jdks/jdk11 if missing; the system JDK is not touched
#   3. face-liveness-desktop  -> installs liveness-grpc-client into ~/.m2
#   4. MockMDS                -> mosip/mosip-mock-services/MockMDS/target
#   5. registration-client    -> the modified Desktop Registration Client
# The Android client is patched here but not built (that needs Flutter 3.10.4 + JDK 21; see command.md).
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/env.sh"
LOGS="$REPO/.build-logs"; mkdir -p "$LOGS"
if port_open "$MDS_PORT"; then
  echo "MockMDS is running from the build folder; run mosip/scripts/stop-services.sh first" >&2
  exit 1
fi

echo "== submodules"
git -C "$REPO" submodule update --init

# Puts a MOSIP client submodule on its face-liveness branch, creating it from the patch on a fresh clone.
apply_integration() {
  local name=$1 dir="$REPO/mosip/$1" patch="$REPO/mosip/patches/$1-face-liveness.patch"
  if git -C "$dir" rev-parse --verify -q face-liveness >/dev/null; then
    [ "$(git -C "$dir" branch --show-current)" = face-liveness ] || git -C "$dir" checkout -q face-liveness
  elif [ -z "$(git -C "$dir" status --porcelain)" ]; then
    echo "applying the face liveness integration to $name"
    git -C "$dir" checkout -q -b face-liveness
    git -C "$dir" apply "$patch"
  else
    echo "$name has local changes and no face-liveness branch; not applying $patch" >&2
    exit 1
  fi
}
apply_integration registration-client
apply_integration android-registration-client
# MediaPipe face landmarker for the Android module: tracked once in this repo, not duplicated in the patch
ASSET="$REPO/mosip/android-registration-client/android/livenessmanager/src/main/assets/face_landmarker.task"
[ -f "$ASSET" ] || cp "$REPO/face-liveness-active/models/face_landmarker.task" "$ASSET"

echo "== JDK 11"
if [ ! -x "$JDK11/bin/java" ]; then
  mkdir -p "$(dirname "$JDK11")"
  curl -fL -o /tmp/jdk11.tgz "https://api.adoptium.net/v3/binary/latest/11/ga/linux/x64/jdk/hotspot/normal/eclipse"
  mkdir -p "$JDK11" && tar xzf /tmp/jdk11.tgz -C "$JDK11" --strip-components=1 && rm /tmp/jdk11.tgz
fi
"$JDK11/bin/java" -version 2>&1 | head -1
use_jdk11

echo "== face-liveness-desktop (liveness-grpc-client)"
(cd "$REPO/face-liveness-desktop" && mvn -B -q install) > "$LOGS/face-liveness-desktop.log" 2>&1 \
  || { echo "failed, see $LOGS/face-liveness-desktop.log"; exit 1; }

echo "== MockMDS"
(cd "$MOCKMDS_DIR" && mvn -B -q clean install -DskipTests -Dgpg.skip -Dmaven.javadoc.skip=true) \
  > "$LOGS/mockmds.log" 2>&1 || { echo "failed, see $LOGS/mockmds.log"; exit 1; }

echo "== registration-client (takes a few minutes the first time)"
(cd "$RC_DIR" && mvn -B install -Dgpg.skip=true -DskipTests=true -Dmaven.javadoc.skip=true) \
  > "$LOGS/registration-client.log" 2>&1 || { echo "failed, see $LOGS/registration-client.log"; exit 1; }
(cd "$RC_DIR" && mvn -B -q test-compile -Dgpg.skip=true -pl registration-client) \
  >> "$LOGS/registration-client.log" 2>&1 || { echo "failed, see $LOGS/registration-client.log"; exit 1; }

echo "done. Next: mosip/scripts/start-services.sh"
