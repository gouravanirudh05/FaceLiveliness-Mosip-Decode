# Shared settings for the MOSIP integration scripts. Source it; do not run it.
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RUN_DIR="$REPO/.run"
JDK11="${JDK11:-$HOME/jdks/jdk11}"
CONDA_BASE="${CONDA_BASE:-$HOME/miniconda3}"
PASSIVE_PY="$CONDA_BASE/envs/face-liveness-passive/bin/python"
RC_DIR="$REPO/mosip/registration-client/registration"
MOCKMDS_DIR="$REPO/mosip/mosip-mock-services/MockMDS"
LIVENESS_PORT=50052
MDS_PORT=4501

use_jdk11() {
  if [ ! -x "$JDK11/bin/java" ]; then
    echo "JDK 11 not found at $JDK11 (run mosip/scripts/setup.sh, or set JDK11=/path/to/jdk11)" >&2
    exit 1
  fi
  export JAVA_HOME="$JDK11" PATH="$JDK11/bin:$PATH"
}

port_open() { (echo > "/dev/tcp/127.0.0.1/$1") 2>/dev/null; }
