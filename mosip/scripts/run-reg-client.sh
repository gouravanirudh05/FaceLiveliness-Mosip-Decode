#!/usr/bin/env bash
# Runs the Desktop Registration Client built by setup.sh (JavaFX 11 from its own target/lib).
# Start mosip/scripts/start-services.sh first. Without a MOSIP server (mosip.hostname) the client stops at the
# login screen: the first login and the initial sync are online only. Logs: registration-client/logs/.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/env.sh"
use_jdk11
cd "$RC_DIR/registration-client"
JAR="target/registration-client-1.2.0.2.jar"
[ -f "$JAR" ] || { echo "$JAR not found; run mosip/scripts/setup.sh first" >&2; exit 1; }
FX="$(ls target/lib/javafx-*-11.0.2-linux.jar | tr '\n' ':')"
# The machine key registered with the server (Collab) is the TPM one; without TPM access the client silently
# switches to software keys in .mosipkeys/ and the server rejects it. Needs the tss group (sg tss -c ... until re-login).
if [ -e /dev/tpmrm0 ] && [ ! -r /dev/tpmrm0 ]; then
  echo "WARNING: no access to /dev/tpmrm0; the client will use software keys, not the registered TPM key." >&2
  echo "         Run: sg tss -c mosip/scripts/run-reg-client.sh  (or log out and back in)" >&2
fi
exec java --module-path "$FX" \
  --add-modules=javafx.controls,javafx.fxml,javafx.base,javafx.web,javafx.swing,javafx.graphics \
  --add-exports javafx.graphics/com.sun.javafx.application=ALL-UNNAMED \
  -cp "$JAR:target/lib/*" io.mosip.registration.controller.Initialization "$@"
