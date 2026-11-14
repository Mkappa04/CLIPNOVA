#!/usr/bin/env bash
# CLIPNOVA installer — run inside Ubuntu WSL. Idempotent; never overwrites .env or data.
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
[[ "${1:-}" == "--dev" ]] && "$VENV/bin/pip" install --quiet -r requirements-dev.txt
ok "Python dependencies installed (.venv)"

banner "Frontend"
cd "$ROOT/frontend"
if [[ -f package-lock.json ]]; then npm ci --no-audit --no-fund --loglevel=error; else npm install --no-audit --no-fund --loglevel=error; fi
npm run build --silent
ok "Dashboard built (frontend/dist)"
cd "$ROOT"

banner "Configuration"
if [[ -f .env ]]; then ok ".env already exists (kept as is)"; else cp .env.example .env; ok "Created .env from .env.example"; fi
mkdir -p data/{videos,thumbnails,logs,cache,renders,run}
ok "Data folders ready"

echo
ok "Installation complete. Start with:  ${C_V}./start.sh${C_0}"
