"""FFmpeg/ffprobe wrappers: probing, thumbnails, cancellable runs with progress."""

from __future__ import annotations

import json
import logging
import queue
import re
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path

from backend.core.config import get_settings
from backend.core.exceptions import MediaError

log = logging.getLogger(__name__)


@dataclass
class MediaInfo:
    duration: float | None
    width: int | None
    height: int | None
    fps: float | None
    video_codec: str | None
    audio_codec: str | None
    has_audio: bool
    bitrate: int | None
    format_name: str | None

    def as_dict(self) -> dict:
        return asdict(self)


def _parse_rate(rate: str | None) -> float | None:
    if not rate or rate in ("0/0", "0"):
        return None
    try:
        if "/" in rate:
            num, den = rate.split("/", 1)
            return round(float(num) / float(den), 3) if float(den) else None
        return round(float(rate), 3)
    except ValueError:
        return None


def _to_float(v) -> float | None:
    try:
        return float(v) if v not in (None, "N/A") else None
    except (TypeError, ValueError):
        return None


def probe(path: str | Path) -> MediaInfo:
    s = get_settings()
    cmd = [s.ffprobe_bin, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120, check=False)
    except FileNotFoundError as e:
        raise MediaError("ffprobe not found; install ffmpeg (sudo apt install ffmpeg)") from e
    except subprocess.TimeoutExpired as e:
        raise MediaError("ffprobe timed out") from e
    if proc.returncode != 0:
        raise MediaError(f"ffprobe failed: {proc.stderr.strip()[:500] or 'unknown error'}")

    data = json.loads(proc.stdout or "{}")
    streams = data.get("streams", [])
    fmt = data.get("format", {})
    video = next((st for st in streams if st.get("codec_type") == "video"
                  and not st.get("disposition", {}).get("attached_pic")), None)
    audio = next((st for st in streams if st.get("codec_type") == "audio"), None)
    if video is None:
        raise MediaError("No video stream found in file")

    width, height = video.get("width"), video.get("height")
    rotation = 0
    for sd in video.get("side_data_list", []) or []:
        if "rotation" in sd:
            rotation = int(sd["rotation"])
    rotation = rotation or int(video.get("tags", {}).get("rotate", 0) or 0)
    if abs(rotation) % 180 == 90 and width and height:
        width, height = height, width

    fps = _parse_rate(video.get("avg_frame_rate")) or _parse_rate(video.get("r_frame_rate"))
    duration = _to_float(fmt.get("duration")) or _to_float(video.get("duration"))
    bitrate = _to_float(fmt.get("bit_rate"))

    return MediaInfo(
        duration=round(duration, 3) if duration else None,
        width=width, height=height, fps=fps,
        video_codec=video.get("codec_name"),
        audio_codec=audio.get("codec_name") if audio else None,
        has_audio=audio is not None,
        bitrate=int(bitrate) if bitrate else None,
        format_name=fmt.get("format_name"),
    )


class FFmpegCancelled(Exception):
    pass


_TIME_RE = re.compile(r"out_time_(?:ms|us)=(\d+)")


def run_ffmpeg(
    args: list[str],
    *,
    duration: float | None = None,
    on_progress: Callable[[float], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
    timeout: float | None = None,
) -> None:
    """Run ffmpeg with machine-readable progress; terminates the process on cancel."""
    s = get_settings()
    cmd = [s.ffmpeg_bin, "-hide_banner", "-nostdin", "-loglevel", "error",
           "-progress", "pipe:1", "-nostats", *args]
    log.debug("ffmpeg %s", " ".join(cmd))
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    except FileNotFoundError as e:
        raise MediaError("ffmpeg not found; install it with: sudo apt install ffmpeg") from e

    lines: queue.Queue[str] = queue.Queue()
    stderr_buf: list[str] = []

    def _pump(stream, sink) -> None:
        for ln in iter(stream.readline, ""):
            sink(ln)
        stream.close()

    threading.Thread(target=_pump, args=(proc.stdout, lines.put), daemon=True).start()
    err_thread = threading.Thread(target=_pump, args=(proc.stderr, stderr_buf.append), daemon=True)
    err_thread.start()

    started = time.monotonic()
    try:
        while proc.poll() is None:
            if should_cancel and should_cancel():
                proc.terminate()
                try:
                    proc.wait(5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                raise FFmpegCancelled()
            if timeout and time.monotonic() - started > timeout:
                proc.kill()
                raise MediaError("ffmpeg timed out")
            try:
                line = lines.get(timeout=0.2)
            except queue.Empty:
                continue
            m = _TIME_RE.search(line)
            if m and duration and on_progress:
                on_progress(min(1.0, int(m.group(1)) / 1_000_000 / duration))
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
    err_thread.join(timeout=2)
    if proc.returncode != 0:
        tail = "".join(stderr_buf)[-800:].strip()
        raise MediaError(f"ffmpeg failed ({proc.returncode}): {tail}")


def generate_thumbnail(src: str | Path, dest: str | Path, at_seconds: float = 0.0, width: int = 640) -> Path:
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    for ts in dict.fromkeys([max(0.0, at_seconds), 0.0]):
        try:
            run_ffmpeg(["-ss", f"{ts:.3f}", "-i", str(src), "-frames:v", "1",
                        "-vf", f"scale={width}:-2", "-q:v", "3", "-y", str(dest)], timeout=60)
            if dest.exists() and dest.stat().st_size > 0:
                return dest
        except MediaError as e:
            log.warning("Thumbnail at %.2fs failed: %s", ts, e)
    raise MediaError("Could not generate thumbnail")


@lru_cache
def capabilities() -> dict:
    """Detect ffmpeg version and whether NVENC actually works (cached)."""
    s = get_settings()
    info: dict = {"ffmpeg": None, "ffprobe": None, "nvenc_h264": False, "hwaccels": []}
    try:
        out = subprocess.run([s.ffmpeg_bin, "-version"], capture_output=True, text=True, timeout=10)
        info["ffmpeg"] = out.stdout.splitlines()[0] if out.stdout else None
        out = subprocess.run([s.ffprobe_bin, "-version"], capture_output=True, text=True, timeout=10)
        info["ffprobe"] = out.stdout.splitlines()[0] if out.stdout else None
        out = subprocess.run([s.ffmpeg_bin, "-hide_banner", "-hwaccels"], capture_output=True, text=True, timeout=10)
        info["hwaccels"] = [ln.strip() for ln in out.stdout.splitlines()[1:] if ln.strip()]
        if s.use_gpu:
            test = subprocess.run(
                [s.ffmpeg_bin, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                 "color=c=black:s=256x256:d=0.1", "-frames:v", "1", "-c:v", "h264_nvenc", "-f", "null", "-"],
                capture_output=True, text=True, timeout=30,
            )
            info["nvenc_h264"] = test.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        log.warning("FFmpeg capability detection failed: %s", e)
    return info
