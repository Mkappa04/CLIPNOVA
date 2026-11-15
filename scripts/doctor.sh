#!/usr/bin/env bash
# Health check: environment, service, GPU transcription, storage, recent errors.
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"
cd "$ROOT"
bash scripts/check_env.sh || true
load_env
PORT="${CLIPNOVA_PORT:-8000}"
banner "Service"
if curl -fsS "http://127.0.0.1:$PORT/api/health" >/dev/null 2>&1; then
  ok "Backend running on http://localhost:$PORT ($(curl -s "http://127.0.0.1:$PORT/api/health" | grep -o '"version":"[^"]*"'))"
else
  warn "Backend not running (./start.sh)"
fi
banner "AI runtime"
if [[ -x "$VENV/bin/python" ]]; then
  "$VENV/bin/python" - <<'PY'
from backend.core import gpu
cuda = gpu.cuda_device_count() > 0 and gpu.preload_cuda_libs()
print(("✔" if cuda else "!") + f" CUDA for Whisper: {'available' if cuda else 'not available (CPU fallback)'}")
free = gpu.free_vram_mb()
print(f"✔ Free VRAM: {free} MB" if free is not None else "! VRAM unknown")
PY
fi
banner "Storage"
du -sh data/* 2>/dev/null | sort -h | tail -6
banner "Recent errors"
n=$(grep -c " ERROR \| WARNING " data/logs/clipnova.log 2>/dev/null || echo 0)
info "$n warnings/errors in data/logs/clipnova.log; last ones:"
grep " ERROR \| WARNING " data/logs/clipnova.log 2>/dev/null | tail -5
