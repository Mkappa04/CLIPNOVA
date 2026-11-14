#!/usr/bin/env bash
# Start CLIPNOVA. Usage: ./start.sh [--dev] [--foreground]
#   default      : backend serves API + built dashboard on http://127.0.0.1:8000
#   --dev        : backend with auto-reload + Vite dev server on http://127.0.0.1:5173
#   --foreground : run the backend in the foreground (Ctrl+C to stop)
set -euo pipefail
source "$(dirname "$0")/scripts/common.sh"
cd "$ROOT"

DEV=0; FG=0
for a in "$@"; do case "$a" in --dev) DEV=1;; --foreground|-f) FG=1;; -h|--help) sed -n '2,6p' "$0"; exit 0;; *) err "Unknown option $a"; exit 1;; esac; done

[[ -x "$VENV/bin/uvicorn" ]] || { err "Not installed. Run ./install.sh first."; exit 1; }
command -v ffmpeg >/dev/null || { err "ffmpeg not found (sudo apt install ffmpeg)"; exit 1; }
load_env
HOST="${CLIPNOVA_HOST:-127.0.0.1}"; PORT="${CLIPNOVA_PORT:-8000}"
mkdir -p "$RUN_DIR" "$LOG_DIR"

if pid_alive "$RUN_DIR/backend.pid"; then
  warn "CLIPNOVA is already running (pid $(cat "$RUN_DIR/backend.pid")). Use ./stop.sh first."; exit 0
fi
if (exec 3<>"/dev/tcp/$HOST/$PORT") 2>/dev/null; then
  err "Port $PORT on $HOST is already in use by another process."; exit 1
fi

# Rebuild the dashboard if sources are newer than the build
if [[ $DEV -eq 0 ]]; then
  if [[ ! -f frontend/dist/index.html ]] || [[ -n "$(find frontend/src frontend/index.html -newer frontend/dist/index.html -print -quit)" ]]; then
    info "Building dashboard…"
    (cd frontend && npm run build --silent) || { err "Frontend build failed"; exit 1; }
  fi
fi

UVICORN=("$VENV/bin/uvicorn" backend.main:app --host "$HOST" --port "$PORT" --log-level warning)
[[ $DEV -eq 1 ]] && UVICORN+=(--reload --reload-dir backend)

banner "starting"
if [[ $FG -eq 1 && $DEV -eq 0 ]]; then
  info "Dashboard: http://$HOST:$PORT  (Ctrl+C to stop)"
  exec "${UVICORN[@]}"
fi

# Run each service as a session/process-group leader that records its own pid,
# so stop.sh can terminate the whole group (reloaders, node children).
spawn() { # spawn <pidfile> <logfile> <workdir> cmd...
  local pidf="$1" logf="$2" wd="$3"; shift 3
  rm -f "$pidf"
  ( cd "$wd" && exec setsid bash -c 'echo $$ > "$0"; exec "$@"' "$pidf" "$@" ) >>"$logf" 2>&1 < /dev/null &
  disown $! 2>/dev/null || true
  for _ in $(seq 1 20); do [[ -s "$pidf" ]] && return 0; sleep 0.1; done
  err "Could not start: $*"; return 1
}

spawn "$RUN_DIR/backend.pid" "$LOG_DIR/backend.out" "$ROOT" "${UVICORN[@]}"

for _ in $(seq 1 60); do
  if curl -fsS "http://$HOST:$PORT/api/health" >/dev/null 2>&1; then break; fi
  pid_alive "$RUN_DIR/backend.pid" || { err "Backend exited. See data/logs/backend.out"; tail -20 "$LOG_DIR/backend.out"; rm -f "$RUN_DIR/backend.pid"; exit 1; }
  sleep 0.5
done
curl -fsS "http://$HOST:$PORT/api/health" >/dev/null || { err "Backend did not become healthy in 30s"; exit 1; }
ok "Backend running (pid $(cat "$RUN_DIR/backend.pid")) — API http://$HOST:$PORT/docs"

if [[ $DEV -eq 1 ]]; then
  spawn "$RUN_DIR/frontend.pid" "$LOG_DIR/frontend.out" "$ROOT/frontend" ./node_modules/.bin/vite --host 127.0.0.1 --port 5173
  ok "Vite dev server: http://127.0.0.1:5173"
else
  ok "Dashboard: ${C_V}http://localhost:$PORT${C_0}  (apri dal browser di Windows)"
fi
info "Logs: data/logs/   Stop: ./stop.sh"
