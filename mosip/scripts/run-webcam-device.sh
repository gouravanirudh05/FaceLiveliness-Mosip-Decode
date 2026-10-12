#!/usr/bin/env bash
# Feeds the webcam into MockMDS's face stream so it acts as a live L0 face device (Ctrl-C to stop).
# Arguments go to mosip/tools/mockmds_webcam_feeder.py, e.g. --camera 1 or --source clip.mp4
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/env.sh"
exec "$PASSIVE_PY" "$REPO/mosip/tools/mockmds_webcam_feeder.py" "$@"
