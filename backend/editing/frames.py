"""Raw frame I/O through FFmpeg pipes (BGR24 numpy arrays)."""

from __future__ import annotations

import subprocess
from collections.abc import Iterator
from pathlib import Path

import numpy as np

from backend.core.config import get_settings
from backend.core.exceptions import MediaError


def scaled_size(width: int, height: int, max_w: int = 1920) -> tuple[int, int]:
    """Decode size: downscale >1080p sources (4K) to max_w wide, keep even dimensions."""
    if width <= max_w:
        return width - width % 2, height - height % 2
    h = int(round(height * max_w / width))
    return max_w, h - h % 2


def grab_frame(src: Path, t: float, width: int, height: int, max_w: int = 1920) -> np.ndarray:
    w, h = scaled_size(width, height, max_w)
    cmd = [get_settings().ffmpeg_bin, "-hide_banner", "-loglevel", "error", "-nostdin",
           "-ss", f"{max(0.0, t):.3f}", "-i", str(src), "-frames:v", "1",
           "-vf", f"scale={w}:{h}", "-f", "rawvideo", "-pix_fmt", "bgr24", "pipe:1"]
    proc = subprocess.run(cmd, capture_output=True, timeout=60)
    data = proc.stdout
    if proc.returncode != 0 or len(data) < w * h * 3:
        if t > 0.5:  # seeking past the last frame: try slightly earlier
            return grab_frame(src, t - 0.5, width, height, max_w)
        raise MediaError(f"Could not read frame at {t:.2f}s: {proc.stderr.decode(errors='ignore')[-300:]}")
    return np.frombuffer(data[: w * h * 3], dtype=np.uint8).reshape(h, w, 3).copy()


class FrameReader:
    """Stream frames of [start, start+duration) at a fixed fps."""

    def __init__(self, src: Path, start: float, duration: float, fps: float, width: int, height: int,
                 max_w: int = 1920, extra_vf: str = "") -> None:
        self.w, self.h = scaled_size(width, height, max_w)
        vf = f"fps={fps},scale={self.w}:{self.h}" + (f",{extra_vf}" if extra_vf else "")
        self.cmd = [get_settings().ffmpeg_bin, "-hide_banner", "-loglevel", "error", "-nostdin",
                    "-ss", f"{max(0.0, start):.3f}", "-i", str(src), "-t", f"{duration:.3f}", "-an",
                    "-vf", vf, "-f", "rawvideo", "-pix_fmt", "bgr24", "pipe:1"]
        self.proc: subprocess.Popen | None = None
        self.frame_bytes = self.w * self.h * 3

    def __iter__(self) -> Iterator[np.ndarray]:
        self.proc = subprocess.Popen(self.cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                     bufsize=self.frame_bytes * 2)
        assert self.proc.stdout is not None
        try:
            while True:
                buf = self.proc.stdout.read(self.frame_bytes)
                if len(buf) < self.frame_bytes:
                    break
                yield np.frombuffer(buf, dtype=np.uint8).reshape(self.h, self.w, 3)
        finally:
            self.close()

    def close(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.kill()
            self.proc.wait()


def sample_frames(src: Path, duration: float, width: int, height: int, n: int = 24,
                  max_w: int = 960) -> list[np.ndarray]:
    """n frames evenly spread over the video (skipping the first/last 3%).

    Uses one fast keyframe seek per sample, so the cost does not grow with the video length."""
    if duration <= 0:
        return []
    times = np.linspace(duration * 0.03, duration * 0.97, n)
    frames = []
    for t in times:
        try:
            frames.append(grab_frame(src, float(t), width, height, max_w=max_w))
        except MediaError:
            continue
    return frames
