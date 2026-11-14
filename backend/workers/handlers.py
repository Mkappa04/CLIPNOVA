"""Job handlers. Importing this module registers them on the job manager."""

from __future__ import annotations

import logging
from pathlib import Path

from backend.core.config import get_settings
from backend.database.session import session_scope
from backend.models.entities import StorageMode, Video, VideoStatus, new_id
from backend.services import ffmpeg
from backend.services.video_service import copy_with_progress, safe_filename
from backend.workers.queue import JobCancelled, JobContext, job_manager

log = logging.getLogger(__name__)


def _set_status(video_id: str, status: VideoStatus, error: str | None = None, **fields) -> None:
    with session_scope() as db:
        video = db.get(Video, video_id)
        if video is None:
            return
        video.status = status.value
        video.error = error
        for k, v in fields.items():
            setattr(video, k, v)


def _probe_video(ctx: JobContext, video_id: str, base: float = 0.0, span: float = 1.0) -> dict:
    with session_scope() as db:
        video = db.get(Video, video_id)
        if video is None:
            raise RuntimeError(f"Video {video_id} disappeared")
        path = Path(video.file_path)
    _set_status(video_id, VideoStatus.PROBING)
    ctx.progress(base + 0.1 * span, "Reading metadata (ffprobe)", force=True)
    info = ffmpeg.probe(path)
    ctx.check_cancelled()

    ctx.progress(base + 0.6 * span, "Generating thumbnail", force=True)
    thumb = get_settings().thumbnails_dir / f"{video_id}.jpg"
    thumb_path: str | None = None
    try:
        at = (info.duration or 0) * 0.1
        ffmpeg.generate_thumbnail(path, thumb, at_seconds=min(at, 30.0))
        thumb_path = str(thumb)
    except Exception as e:  # noqa: BLE001 - thumbnail is non-critical
        log.warning("Thumbnail failed for %s: %s", video_id, e)

    _set_status(
        video_id, VideoStatus.READY,
        duration=info.duration, width=info.width, height=info.height, fps=info.fps,
        video_codec=info.video_codec, audio_codec=info.audio_codec, has_audio=info.has_audio,
        bitrate=info.bitrate, thumbnail_path=thumb_path, file_size=path.stat().st_size,
    )
    return info.as_dict()


@job_manager.register("video.probe")
def probe_video(ctx: JobContext) -> dict:
    video_id = ctx.video_id or ctx.payload["video_id"]
    try:
        return {"media": _probe_video(ctx, video_id)}
    except JobCancelled:
        _set_status(video_id, VideoStatus.ERROR, "Probe cancelled")
        raise
    except Exception as e:
        _set_status(video_id, VideoStatus.ERROR, str(e))
        raise


@job_manager.register("video.copy_import")
def copy_import(ctx: JobContext) -> dict:
    video_id = ctx.video_id or ctx.payload["video_id"]
    src = Path(ctx.payload["source_path"])
    dest = get_settings().videos_dir / f"{new_id()[:12]}_{safe_filename(src.name)}"
    _set_status(video_id, VideoStatus.COPYING)
    try:
        ctx.progress(0.0, f"Copying {src.name}", force=True)
        try:
            copy_with_progress(
                src, dest,
                on_progress=lambda p: ctx.progress(p * 0.7, f"Copying {src.name} ({p:.0%})"),
                should_cancel=lambda: ctx.cancelled,
            )
        except InterruptedError as e:
            raise JobCancelled() from e
        _set_status(video_id, VideoStatus.PENDING, file_path=str(dest),
                    storage_mode=StorageMode.COPIED.value)
        media = _probe_video(ctx, video_id, base=0.7, span=0.3)
        return {"copied_to": str(dest), "media": media}
    except JobCancelled:
        _set_status(video_id, VideoStatus.ERROR, "Import cancelled")
        raise
    except Exception as e:
        _set_status(video_id, VideoStatus.ERROR, str(e))
        raise
