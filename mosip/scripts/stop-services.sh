#!/usr/bin/env bash
# Stops what start-services.sh started (by PID file only; never by process name).
source "$(dirname "${BASH_SOURCE[0]}")/env.sh"
for name in passive mockmds; do
  pidfile="$RUN_DIR/$name.pid"
  [ -f "$pidfile" ] || continue
  pid="$(cat "$pidfile")"
  if kill -0 "$pid" 2>/dev/null; then
    kill "$pid" && echo "stopped $name ($pid)"
    for _ in $(seq 1 20); do kill -0 "$pid" 2>/dev/null || break; sleep 0.5; done
  fi
  rm -f "$pidfile"
done
