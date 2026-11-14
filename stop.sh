#!/usr/bin/env bash
# Stop the CLIPNOVA processes started by ./start.sh (only those, via pid files).
set -euo pipefail
source "$(dirname "$0")/scripts/common.sh"

stopped=0
for name in frontend backend; do
  pidf="$RUN_DIR/$name.pid"
  [[ -f "$pidf" ]] || continue
  pid="$(cat "$pidf")"
  if kill -0 "$pid" 2>/dev/null; then
    info "Stopping $name (pid $pid)…"
    # Each service runs in its own process group (setsid in start.sh): stop the whole group
    kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true
    for _ in $(seq 1 30); do kill -0 "$pid" 2>/dev/null || break; sleep 0.3; done
    if kill -0 "$pid" 2>/dev/null; then warn "$name did not stop gracefully, killing"; kill -KILL -- "-$pid" 2>/dev/null || kill -KILL "$pid" 2>/dev/null || true; fi
    ok "$name stopped"; stopped=1
  fi
  rm -f "$pidf"
done
[[ $stopped -eq 1 ]] || info "CLIPNOVA is not running."
