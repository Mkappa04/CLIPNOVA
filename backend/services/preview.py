"""Clip preview generation: short H.264/AAC MP4 (≤720p, original aspect) playable in any browser.

Uses NVENC when available, libx264 otherwise. Previews are cached per (clip, start, end).
The vertical 9:16 render is Milestone 3; previews keep the original framing.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path

from backend.core.config import get_settings
from backend.core.exceptions import MediaError
from backend.models.entities import Clip, Video
from backend.services import ffmpeg

log = logging.getLogger(__name__)
_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def preview_path(clip: Clip) -> Path:
    return get_settings().previews_dir / f"{clip.id}_{clip.start:.2f}_{clip.end:.2f}.mp4"


def ensure_preview(clip: Clip, video: Video) -> Path:
    target = preview_path(clip)
    if target.exists() and target.stat().st_size > 0:
        return target
    with _locks_guard:
        lock = _locks.setdefault(clip.id, threading.Lock())
    with lock:
        if target.exists() and target.stat().st_size > 0:
            return target
        src = Path(video.file_path)
        if not src.exists():
            raise MediaError(f"Source video missing: {src}")
        target.parent.mkdir(parents=True, exist_ok=True)
        duration = max(0.5, clip.end - clip.start)
        vf = "scale=-2:'min(720,ih)'"
        encoders = []
        if get_settings().use_gpu and ffmpeg.capabilities().get("nvenc_h264"):
            encoders.append(["-c:v", "h264_nvenc", "-preset", "p4", "-rc", "vbr", "-cq", "28", "-b:v", "0",
                             "-maxrate", "4M", "-bufsize", "8M"])
        encoders.append(["-c:v", "libx264", "-preset", "veryfast", "-crf", "24", "-maxrate", "4M", "-bufsize", "8M"])
        tmp = target.with_suffix(".part.mp4")
        last: Exception | None = None
        for enc in encoders:
            try:
                ffmpeg.run_ffmpeg(["-ss", f"{clip.start:.3f}", "-i", str(src), "-t", f"{duration:.3f}",
                                   "-vf", vf, *enc, "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
                                   "-movflags", "+faststart", "-y", str(tmp)], timeout=300)
                tmp.replace(target)
                return target
            except MediaError as e:
                log.warning("Preview encode failed with %s: %s", enc[1], e)
                last = e
        tmp.unlink(missing_ok=True)
        raise MediaError(f"Could not create preview: {last}")
