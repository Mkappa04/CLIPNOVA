"""Host/system introspection: WSL, GPU, RAM, disk, AI runtime availability."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
from functools import lru_cache
from importlib.util import find_spec
from pathlib import Path

from backend.core.config import get_settings
from backend.services import ffmpeg


def _read(path: str) -> str:
    try:
        return Path(path).read_text()
    except OSError:
        return ""


def dir_size(path: Path) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += (Path(root) / f).stat().st_size
            except OSError:
                pass
    return total


def _meminfo() -> dict:
    vals: dict[str, int] = {}
    for line in _read("/proc/meminfo").splitlines():
        k, _, rest = line.partition(":")
        parts = rest.split()
        if parts:
            vals[k] = int(parts[0]) * 1024
    return {"total": vals.get("MemTotal"), "available": vals.get("MemAvailable")}


def gpu_info() -> dict:
    exe = shutil.which("nvidia-smi") or ("/usr/lib/wsl/lib/nvidia-smi"
                                          if Path("/usr/lib/wsl/lib/nvidia-smi").exists() else None)
    if not exe:
        return {"available": False, "reason": "nvidia-smi not found"}
    try:
        out = subprocess.run(
            [exe, "--query-gpu=name,memory.total,memory.used,memory.free,driver_version,utilization.gpu",
             "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"available": False, "reason": str(e)}
    if out.returncode != 0 or not out.stdout.strip():
        return {"available": False, "reason": out.stderr.strip() or "no GPU reported"}
    name, total, used, free, driver, util = [p.strip() for p in out.stdout.strip().splitlines()[0].split(",")]
    return {"available": True, "name": name, "memory_total_mb": int(total), "memory_used_mb": int(used),
            "memory_free_mb": int(free), "driver": driver,
            "utilization_pct": int(util) if util.isdigit() else None}


@lru_cache
def _static_info() -> dict:
    version = _read("/proc/version")
    os_release = dict(
        line.split("=", 1) for line in _read("/etc/os-release").splitlines() if "=" in line
    )
    cpu = next((ln.split(":", 1)[1].strip() for ln in _read("/proc/cpuinfo").splitlines()
                if ln.startswith("model name")), platform.processor())
    return {
        "is_wsl": "microsoft" in version.lower(),
        "is_wsl2": "wsl2" in version.lower(),
        "kernel": platform.release(),
        "distro": os_release.get("PRETTY_NAME", "").strip('"'),
        "python": platform.python_version(),
        "cpu": cpu,
        "cpu_threads": os.cpu_count(),
    }


def ai_runtime() -> dict:
    modules = {name: find_spec(name) is not None
               for name in ("torch", "faster_whisper", "cv2", "scenedetect")}
    info: dict = {"modules": modules, "cuda_available": None}
    if modules["torch"]:
        try:
            import torch  # type: ignore

            info["cuda_available"] = bool(torch.cuda.is_available())
            info["torch_version"] = torch.__version__
        except Exception as e:  # noqa: BLE001
            info["torch_error"] = str(e)
    return info


def system_info() -> dict:
    s = get_settings()
    disk = shutil.disk_usage(s.data_dir)
    return {
        **_static_info(),
        "memory": _meminfo(),
        "disk": {"total": disk.total, "used": disk.used, "free": disk.free,
                 "data_dir": str(s.data_dir), "data_dir_bytes": dir_size(s.data_dir)},
        "gpu": gpu_info(),
        "ffmpeg": ffmpeg.capabilities(),
        "ai": ai_runtime(),
    }
