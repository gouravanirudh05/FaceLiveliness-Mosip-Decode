#!/usr/bin/env bash
# Runs the Desktop Registration Client built by setup.sh (JavaFX 11 from its own target/lib).
# Start mosip/scripts/start-services.sh first. Server: MOSIP_HOST=<host> (see below). Without a server the client stops at the
# login screen: the first login and the initial sync are online only. Logs: registration-client/logs/.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/env.sh"
use_jdk11
cd "$RC_DIR/registration-client"
JAR="target/registration-client-1.2.0.2.jar"
[ -f "$JAR" ] || { echo "$JAR not found; run mosip/scripts/setup.sh first" >&2; exit 1; }
FX="$(ls target/lib/javafx-*-11.0.2-linux.jar | tr '\n' ':')"
# MOSIP_HOST=<host> (e.g. api-internal.collab.mosip.net) points the client at that server without rebuilding: an
# edited copy of the built-in props/mosip-application.properties goes first on the classpath. The upgrade server is
# left unchanged on purpose, so the client cannot replace the patched jars with the server's stock build.
PROPS_CP=""
if [ -n "${MOSIP_HOST:-}" ]; then
  PROPS_DIR="$REPO/.run/regclient-props"
  mkdir -p "$PROPS_DIR/props"
  unzip -p "target/lib/registration-services-1.2.0.2.jar" props/mosip-application.properties \
    | sed "s|^mosip.hostname=.*|mosip.hostname=$MOSIP_HOST|" > "$PROPS_DIR/props/mosip-application.properties"
  # MOSIP_HEALTHCHECK_URL: the client is online only when this returns 2xx (Collab's regclient-api host answers
  # its own health URL with 403; api-internal's works over the VPN).
  if [ -n "${MOSIP_HEALTHCHECK_URL:-}" ]; then
    sed -i "s|^mosip.reg.healthcheck.url=.*|mosip.reg.healthcheck.url=$MOSIP_HEALTHCHECK_URL|" \
      "$PROPS_DIR/props/mosip-application.properties"
  fi
  PROPS_CP="$PROPS_DIR:"
  echo "MOSIP server: $MOSIP_HOST"
fi
# The machine key registered with the server (Collab) is the TPM one; without TPM access the client silently
# switches to software keys in .mosipkeys/ and the server rejects it. Needs the tss group (sg tss -c ... until re-login).
if [ -e /dev/tpmrm0 ] && [ ! -r /dev/tpmrm0 ]; then
  echo "WARNING: no access to /dev/tpmrm0; the client will use software keys, not the registered TPM key." >&2
  echo "         Run: sg tss -c mosip/scripts/run-reg-client.sh  (or log out and back in)" >&2
fi
exec java --module-path "$FX" \
  --add-modules=javafx.controls,javafx.fxml,javafx.base,javafx.web,javafx.swing,javafx.graphics \
  --add-exports javafx.graphics/com.sun.javafx.application=ALL-UNNAMED \
  -cp "$PROPS_CP$JAR:target/lib/*" io.mosip.registration.controller.Initialization "$@"
