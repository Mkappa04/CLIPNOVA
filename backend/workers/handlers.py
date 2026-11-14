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


# ---------------------------------------------------------------- analysis (Milestone 2)
@job_manager.register("video.analyze")
def analyze_video(ctx: JobContext) -> dict:
    from backend.clip_detection.pipeline import (
        TRANSCRIPT_FILE, SIGNALS_FILE, cache_dir, get_or_create_analysis, replace_detected_clips, run_analysis,
        score_video,
    )
    from backend.clip_detection.scoring import ScoringConfig
    from backend.models.entities import AnalysisStatus
    from backend.services.ffmpeg import FFmpegCancelled
    from backend.transcription.whisper_engine import TranscriptionCancelled

    video_id = ctx.video_id or ctx.payload["video_id"]
    opts = ctx.payload
    language = opts.get("language") if opts.get("language") in ("it", "en") else None
    cfg = ScoringConfig.model_validate(opts.get("scoring") or {})

    with session_scope() as db:
        video = db.get(Video, video_id)
        if video is None:
            raise RuntimeError(f"Video {video_id} not found")
        if not video.duration:
            raise RuntimeError("Video metadata missing: run the metadata probe first")
        prev_status = video.status if video.status in (VideoStatus.READY.value, VideoStatus.ANALYZED.value) \
            else VideoStatus.READY.value
        video.status = VideoStatus.ANALYZING.value
        analysis = get_or_create_analysis(db, video)
        analysis.status = AnalysisStatus.RUNNING.value
        analysis.error = None

    def fail(message: str) -> None:
        with session_scope() as db:
            v = db.get(Video, video_id)
            if v is not None:
                v.status = prev_status
                a = get_or_create_analysis(db, v)
                a.status = AnalysisStatus.FAILED.value
                a.error = message

    try:
        info = run_analysis(video, language=language, transcribe=bool(opts.get("transcribe", True)),
                            force=bool(opts.get("force", False)), cfg=cfg,
                            report=lambda p, m: ctx.progress(p, m), should_cancel=lambda: ctx.cancelled)
    except (InterruptedError, FFmpegCancelled, TranscriptionCancelled) as e:
        fail("Annullata dall'utente")
        raise JobCancelled() from e
    except Exception as e:
        fail(f"{type(e).__name__}: {e}")
        raise

    transcript = info["transcript"]
    with session_scope() as db:
        video = db.get(Video, video_id)
        analysis = get_or_create_analysis(db, video)
        analysis.scenes = info["scenes"]
        analysis.language = transcript.language if transcript else ""
        analysis.transcription_device = transcript.device if transcript else ""
        analysis.whisper_model = transcript.model if transcript else ""
        analysis.transcript_path = str(cache_dir(video_id) / TRANSCRIPT_FILE) if transcript else None
        analysis.timeline_path = str(cache_dir(video_id) / SIGNALS_FILE)
        analysis.config = cfg.model_dump()
        stats = {
            "decoder": info["decoder"], "media_cached": info["media_cached"], "timings": info["timings"],
            "audio": info["audio_stats"], "scenes": len(info["scenes"]),
        }
        if transcript:
            stats["transcript"] = {
                "segments": len(transcript.segments), "words": sum(len(s.words) for s in transcript.segments),
                "language_probability": transcript.language_probability, "elapsed_s": transcript.elapsed_s,
                "filtered_hallucinations": transcript.filtered_segments,
            }
        analysis.stats = stats
        _tl, detected = score_video(video, analysis, cfg)
        clips = replace_detected_clips(db, video, detected, analysis.language)
        analysis.status = AnalysisStatus.COMPLETED.value
        video.status = VideoStatus.ANALYZED.value
        video.error = None
    ctx.progress(1.0, f"{len(clips)} clip rilevate", force=True)
    return {"message": f"{len(clips)} clip rilevate", "clips": len(clips), "scenes": len(info["scenes"]),
            "timings": info["timings"],
            "transcription_device": transcript.device if transcript else None,
            "language": transcript.language if transcript else None}
