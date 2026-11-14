#!/usr/bin/env bash
# Verify the host environment. Exit code 1 if a required dependency is missing.
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"
missing=()

banner "Environment check"
if grep -qi microsoft /proc/version; then
  grep -qi wsl2 /proc/version && ok "WSL 2" || warn "WSL detected but not WSL 2"
else
  warn "Not running under WSL (native Linux is fine too)"
fi
. /etc/os-release 2>/dev/null && { [[ "$ID" == "ubuntu" ]] && ok "$PRETTY_NAME" || warn "Distro: $PRETTY_NAME (tested on Ubuntu)"; }
case "$ROOT" in /mnt/*) err "Project is on the Windows filesystem ($ROOT). Move it under /home."; exit 1;; *) ok "Project in Linux filesystem: $ROOT";; esac

if command -v python3 >/dev/null && python3 -c 'import sys; sys.exit(sys.version_info < (3,10))'; then
  ok "Python $(python3 -V | cut -d' ' -f2)"
  python3 -c 'import venv, ensurepip' 2>/dev/null && ok "python venv" || { err "python3-venv missing"; missing+=(python3-venv); }
else err "Python >= 3.10 missing"; missing+=(python3 python3-venv); fi

if command -v node >/dev/null && [[ "$(node -p 'process.versions.node.split(".")[0]')" -ge 18 ]]; then
  ok "Node $(node -v)"; else err "Node.js >= 18 missing"; missing+=(nodejs); fi
command -v npm >/dev/null && ok "npm $(npm -v)" || { err "npm missing"; missing+=(npm); }
command -v git >/dev/null && ok "$(git --version)" || { warn "git missing"; missing+=(git); }
if command -v ffmpeg >/dev/null && command -v ffprobe >/dev/null; then
  ok "ffmpeg $(ffmpeg -version | head -1 | cut -d' ' -f3)"
else err "ffmpeg missing"; missing+=(ffmpeg); fi

if command -v nvidia-smi >/dev/null && nvidia-smi --query-gpu=name,memory.total --format=csv,noheader >/dev/null 2>&1; then
  ok "GPU: $(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader)"
  if ffmpeg -hide_banner -loglevel error -f lavfi -i color=s=256x256:d=0.1 -frames:v 1 -c:v h264_nvenc -f null - 2>/dev/null; then
    ok "NVENC encoding available"; else warn "NVENC not usable: rendering will use CPU (libx264)"; fi
else
  warn "NVIDIA GPU not visible in WSL. Update the Windows NVIDIA driver; do NOT install Linux NVIDIA drivers inside WSL."
fi
ok "RAM: $(free -h | awk '/Mem:/{print $2" total, "$7" available"}')"
ok "Disk free: $(df -h "$ROOT" | awk 'NR==2{print $4}')"

if ((${#missing[@]})); then
  # Node from Ubuntu 22.04 apt is v12: suggest NodeSource instead
  pkgs=("${missing[@]/nodejs/}"); pkgs=("${pkgs[@]/npm/}")
  echo
  err "Missing: ${missing[*]}"
  [[ -n "${pkgs[*]// /}" ]] && echo "   Install with:  sudo apt update && sudo apt install -y ${pkgs[*]}"
  [[ " ${missing[*]} " == *" nodejs "* || " ${missing[*]} " == *" npm "* ]] && \
    echo "   Node.js 20+:   https://github.com/nodesource/distributions (or nvm)"
  exit 1
fi
