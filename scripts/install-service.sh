#!/usr/bin/env bash
# OPTIONAL: run CLIPNOVA as a systemd *user* service (auto-start when WSL starts).
# Requires systemd in WSL (/etc/wsl.conf: [boot] systemd=true). Changes your user services: run it yourself.
#   scripts/install-service.sh            install + enable
#   scripts/install-service.sh --remove   disable + remove
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"
unit="$HOME/.config/systemd/user/clipnova.service"
if [[ "${1:-}" == "--remove" ]]; then
  systemctl --user disable --now clipnova.service 2>/dev/null || true
  rm -f "$unit"; systemctl --user daemon-reload; ok "Service removed"; exit 0
fi
[[ -x "$VENV/bin/uvicorn" ]] || { err "Run ./install.sh first"; exit 1; }
mkdir -p "$(dirname "$unit")"
cat > "$unit" <<UNIT
[Unit]
Description=CLIPNOVA gaming content automation (localhost only)
After=network.target

[Service]
WorkingDirectory=$ROOT
ExecStart=$VENV/bin/uvicorn backend.main:app --host 127.0.0.1 --port 8000 --log-level warning
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
UNIT
systemctl --user daemon-reload
systemctl --user enable --now clipnova.service
ok "Service installed: systemctl --user status clipnova"
warn "Use either the service or ./start.sh, not both (same port)."
