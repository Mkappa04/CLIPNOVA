"""GPU helpers for WSL 2.

The CUDA runtime libraries (cuBLAS, cuDNN) are installed as pip wheels inside
the venv (nvidia-*-cu12). CTranslate2 dlopen()s them by soname, so we preload
them with RTLD_GLOBAL before the first CUDA model load. The NVIDIA *driver*
comes from Windows via /usr/lib/wsl/lib: nothing is installed system-wide.
"""

from __future__ import annotations

import ctypes
import logging
import subprocess
import threading
from importlib.util import find_spec
from pathlib import Path

log = logging.getLogger(__name__)

_lock = threading.Lock()
_preloaded: bool | None = None

# Load order matters: cublasLt before cublas, cudnn core before its sub-libraries.
_ORDER = ("libcublasLt", "libcublas", "libnvrtc", "libcudnn.so", "libcudnn_")


def _nvidia_lib_dirs() -> list[Path]:
    spec = find_spec("nvidia")
    if spec is None or not spec.submodule_search_locations:
        return []
    dirs: list[Path] = []
    for base in spec.submodule_search_locations:
        dirs.extend(sorted(p for p in Path(base).glob("*/lib") if p.is_dir()))
    return dirs


def preload_cuda_libs() -> bool:
    """Preload pip-provided CUDA libs. Returns True if cuBLAS and cuDNN loaded."""
    global _preloaded
    with _lock:
        if _preloaded is not None:
            return _preloaded
        libs = [p for d in _nvidia_lib_dirs() for p in d.glob("lib*.so*") if p.is_file()]

        def rank(p: Path) -> int:
            for i, prefix in enumerate(_ORDER):
                if p.name.startswith(prefix):
                    return i
            return len(_ORDER)

        loaded: set[str] = set()
        for lib in sorted(libs, key=lambda p: (rank(p), p.name)):
            try:
                ctypes.CDLL(str(lib), mode=ctypes.RTLD_GLOBAL)
                loaded.add(lib.name)
            except OSError as e:
                log.debug("Could not preload %s: %s", lib.name, e)
        _preloaded = any(n.startswith("libcublas.so") for n in loaded) and any(
            n.startswith("libcudnn.so") for n in loaded)
        log.info("CUDA libs preloaded: %s (%d libraries)", _preloaded, len(loaded))
        return _preloaded


def cuda_device_count() -> int:
    try:
        import ctranslate2  # type: ignore

        return int(ctranslate2.get_cuda_device_count())
    except Exception:  # noqa: BLE001
        return 0


def free_vram_mb() -> int | None:
    """Free VRAM as reported by nvidia-smi (None if unavailable)."""
    for exe in ("nvidia-smi", "/usr/lib/wsl/lib/nvidia-smi"):
        try:
            out = subprocess.run([exe, "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
                                 capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            continue
        if out.returncode == 0 and out.stdout.strip():
            return int(out.stdout.strip().splitlines()[0])
    return None
