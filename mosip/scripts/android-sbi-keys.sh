#!/usr/bin/env bash
# Prepares device keys for MOSIP's "Mock Android SBI" app (io.mosip.mock.sbi) from MockMDS's test keys and copies
# them to the phone's Download folder (when a phone is connected with USB debugging).
#
# MockMDS's .p12 files use legacy encryption (pbeWithSHA1And40BitRC2) that current Android cannot read ("Device key
# validation failed"); they are re-packaged here with AES-256, keeping each file's alias and password.
# Run mosip/scripts/setup.sh first (it builds MockMDS, whose target/ holds the keys). Needs OpenSSL 3.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/env.sh"

KEYS="$MOCKMDS_DIR/target/Biometric Devices/Finger/Slap/Keys"
OUT="$REPO/.run/android-sbi-keys"
[ -d "$KEYS" ] || { echo "$KEYS not found; run mosip/scripts/setup.sh first" >&2; exit 1; }
mkdir -p "$OUT"

for name in mosipfingerslap mosipfingerslapftm; do
  pem="$(mktemp)"
  openssl pkcs12 -in "$KEYS/$name.p12" -passin "pass:$name" -legacy -nodes -out "$pem" 2>/dev/null
  openssl pkcs12 -export -in "$pem" -name "$name" -passout "pass:$name" -out "$OUT/$name-android.p12" \
    -keypbe AES-256-CBC -certpbe AES-256-CBC -macalg sha256
  rm -f "$pem"
  echo "wrote $OUT/$name-android.p12 (alias and password: $name)"
done

if command -v adb >/dev/null && adb get-state >/dev/null 2>&1; then
  adb push "$OUT/mosipfingerslap-android.p12" "$OUT/mosipfingerslapftm-android.p12" /sdcard/Download/
  echo "copied to the phone's Download folder"
else
  echo "no phone connected: copy the two files to the phone's Download folder yourself"
fi
