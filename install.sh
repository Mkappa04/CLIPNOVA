#!/usr/bin/env bash
# CLIPNOVA installer — run inside Ubuntu WSL. Idempotent; never overwrites .env or data.
# Usage: ./install.sh [--dev] [--no-ai]
set -euo pipefail
source "$(dirname "$0")/scripts/common.sh"
cd "$ROOT"

bash scripts/check_env.sh || { err "Fix the missing dependencies above, then re-run ./install.sh"; exit 1; }

banner "Python backend"
if [[ ! -x "$VENV/bin/python" ]]; then
  info "Creating virtual environment in .venv"
  python3 -m venv "$VENV"
fi
"$VENV/bin/pip" install --quiet --upgrade pip
"$VENV/bin/pip" install --quiet -r requirements.txt
[[ " $* " == *" --dev "* ]] && "$VENV/bin/pip" install --quiet -r requirements-dev.txt
ok "Python dependencies installed (.venv)"

banner "AI stack (faster-whisper, OpenCV, PySceneDetect, CUDA runtime libs)"
if [[ " $* " == *" --no-ai "* ]]; then
  warn "Skipped (--no-ai): clip detection will not be available"
else
  free_gb=$(df -BG --output=avail "$ROOT" | tail -1 | tr -dc '0-9')
  if (( free_gb < 6 )); then
    err "Only ${free_gb} GB free: the AI stack needs ~1.5 GB + ~1.6 GB for the Whisper model. Free space or use --no-ai."
    exit 1
  fi
  info "Installing (~1.5 GB, one time; ${free_gb} GB free)…"
  "$VENV/bin/pip" install --quiet -r requirements-ai.txt
  ok "AI stack installed. Whisper weights (~1.6 GB) download on the first analysis into data/models/"
fi

banner "Frontend"
cd "$ROOT/frontend"
if [[ -f package-lock.json ]]; then npm ci --no-audit --no-fund --loglevel=error; else npm install --no-audit --no-fund --loglevel=error; fi
npm run build --silent
ok "Dashboard built (frontend/dist)"
cd "$ROOT"

banner "Configuration"
if [[ -f .env ]]; then ok ".env already exists (kept as is)"; else cp .env.example .env; ok "Created .env from .env.example"; fi
mkdir -p data/{videos,thumbnails,logs,cache,renders,run,models,previews}
ok "Data folders ready"

echo
ok "Installation complete. Start with:  ${C_V}./start.sh${C_0}"
