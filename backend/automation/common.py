from __future__ import annotations

import hashlib
import os
import subprocess
from datetime import datetime, time
from pathlib import Path

from sqlalchemy.orm import Session

from backend.core.timeutil import utcnow
from backend.models.automation_entities import AppSetting, Notification

SAMPLE = 1024 * 1024


def quick_signature(path: Path) -> str:
    """sha256 of size + 1 MB at start, middle and end. Fast even for multi-GB files on /mnt/c."""
    size = path.stat().st_size
    h = hashlib.sha256(str(size).encode())
    with path.open("rb") as fh:
        for off in sorted({0, max(0, size // 2 - SAMPLE // 2), max(0, size - SAMPLE)}):
            fh.seek(off)
            h.update(fh.read(SAMPLE))
    return h.hexdigest()


# ---------------------------------------------------------------- runtime settings
AUTOMATION_DEFAULTS = {
    "paused": False,
    "window": {"enabled": False, "start": "22:00", "end": "07:00"},
    "idle_only": False,
    "idle_max_cpu": 0.6,     # 1-min load average per CPU thread
    "idle_max_gpu": 35,      # % GPU utilisation (includes Windows games via WSL)
}


def get_setting(db: Session, key: str, default: dict) -> dict:
    row = db.get(AppSetting, key)
    value = dict(default)
    if row is not None and isinstance(row.value, dict):
        value.update(row.value)
    return value


def put_setting(db: Session, key: str, value: dict) -> dict:
    row = db.get(AppSetting, key)
    if row is None:
        db.add(AppSetting(key=key, value=value))
    else:
        row.value = value
    return value


def automation_settings(db: Session) -> dict:
    return get_setting(db, "automation", AUTOMATION_DEFAULTS)


# ---------------------------------------------------------------- resource gating
def _in_window(now_local: time, start: str, end: str) -> bool:
    s = time.fromisoformat(start)
    e = time.fromisoformat(end)
    return s <= now_local < e if s <= e else (now_local >= s or now_local < e)


def gpu_utilisation() -> int | None:
    for exe in ("nvidia-smi", "/usr/lib/wsl/lib/nvidia-smi"):
        try:
            out = subprocess.run([exe, "--query-gpu=utilization.gpu", "--format=csv,noheader,nounits"],
                                 capture_output=True, text=True, timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            continue
        if out.returncode == 0 and out.stdout.strip().isdigit():
            return int(out.stdout.strip())
    return None


def can_run_heavy(cfg: dict, now: datetime | None = None) -> tuple[bool, str]:
    """Whether the automatic pipeline may start heavy work now."""
    if cfg.get("paused"):
        return False, "Automazione in pausa"
    now = now or datetime.now()
    win = cfg.get("window") or {}
    if win.get("enabled") and not _in_window(now.time(), win.get("start", "00:00"), win.get("end", "23:59")):
        return False, f"Fuori dalla fascia oraria {win.get('start')}–{win.get('end')}"
    if cfg.get("idle_only"):
        load = os.getloadavg()[0] / max(1, os.cpu_count() or 1)
        if load > float(cfg.get("idle_max_cpu", 0.6)):
            return False, f"PC occupato (carico CPU {load:.2f})"
        gpu = gpu_utilisation()
        if gpu is not None and gpu > int(cfg.get("idle_max_gpu", 35)):
            return False, f"GPU occupata ({gpu}%): probabilmente stai giocando"
    return True, ""


def notify(db: Session, title: str, body: str = "", link: str = "", kind: str = "info") -> None:
    db.add(Notification(kind=kind, title=title[:300], body=body, link=link, created_at=utcnow()))
