"""Prepare analysis artefacts in ONE decode pass of the source video:

- proxy.mp4 : low-res, low-fps, silent copy for scene/motion analysis
- audio.wav : 16 kHz mono PCM for loudness analysis and Whisper

Decoder order follows CLIPNOVA_ANALYSIS_DECODER (cpu|nvdec); the other one is the fallback. Results are
cached in data/cache/<video_id>/ and reused while the source is unchanged.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from backend.core.config import get_settings
from backend.services import ffmpeg

log = logging.getLogger(__name__)


@dataclass
class PreparedMedia:
    proxy: Path
    audio: Path | None
    decoder: str
    cached: bool


def _signature(src: Path) -> dict:
    st = src.stat()
    s = get_settings()
    return {"size": st.st_size, "mtime": int(st.st_mtime), "w": s.analysis_proxy_width,
            "fps": s.analysis_proxy_fps}


def prepare_media(
    src: Path, cache_dir: Path, *, duration: float | None, has_audio: bool,
    on_progress: Callable[[float], None] | None = None, should_cancel: Callable[[], bool] | None = None,
    force: bool = False,
) -> PreparedMedia:
    s = get_settings()
    cache_dir.mkdir(parents=True, exist_ok=True)
    proxy, audio, manifest = cache_dir / "proxy.mp4", cache_dir / "audio.wav", cache_dir / "media.json"
    sig = _signature(src)

    if not force and manifest.exists() and proxy.exists() and (audio.exists() or not has_audio):
        try:
            data = json.loads(manifest.read_text())
            if data.get("signature") == sig:
                return PreparedMedia(proxy, audio if has_audio else None, data.get("decoder", "?"), True)
        except (json.JSONDecodeError, OSError):
            pass

    outputs = ["-map", "0:v:0", "-vf", f"fps={s.analysis_proxy_fps},scale={s.analysis_proxy_width}:-2",
               "-c:v", "libx264", "-preset", "ultrafast", "-crf", "30", "-an", "-y", str(proxy)]
    if has_audio:
        outputs += ["-map", "0:a:0", "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", "-y", str(audio)]

    attempts = [("cpu", [])]
    if s.use_gpu:
        nvdec = ("nvdec", ["-hwaccel", "cuda"])
        attempts = [nvdec, *attempts] if s.analysis_decoder == "nvdec" else [*attempts, nvdec]
    last_error: Exception | None = None
    for decoder, pre in attempts:
        try:
            ffmpeg.run_ffmpeg([*pre, "-i", str(src), *outputs], duration=duration,
                              on_progress=on_progress, should_cancel=should_cancel)
            manifest.write_text(json.dumps({"signature": sig, "decoder": decoder}))
            return PreparedMedia(proxy, audio if has_audio else None, decoder, False)
        except ffmpeg.FFmpegCancelled:
            raise
        except Exception as e:  # noqa: BLE001 - try next decoder
            log.warning("Media preparation with %s failed: %s", decoder, e)
            last_error = e
    raise RuntimeError(f"Could not prepare media for analysis: {last_error}")
