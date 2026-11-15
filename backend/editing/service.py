"""Glue between DB entities and the editing engine."""

from __future__ import annotations

from pathlib import Path

from pydantic import ValidationError

from backend.editing.config import EditConfig, Region, default_config_for
from backend.editing.renderer import ClipSource
from backend.models.entities import Clip, Video


def video_webcam(video: Video) -> Region | None:
    if not video.webcam_region:
        return None
    try:
        return Region.model_validate(video.webcam_region)
    except ValidationError:
        return None


def effective_config(clip: Clip) -> EditConfig:
    """Stored config merged over defaults (layout default depends on the webcam)."""
    base = default_config_for(video_webcam(clip.video) is not None)
    if clip.edit_config:
        try:
            return EditConfig.model_validate({**base.model_dump(), **clip.edit_config})
        except ValidationError:
            return base
    return base


def clip_source(clip: Clip, config: EditConfig | None = None) -> ClipSource:
    video = clip.video
    cfg = config or effective_config(clip)
    webcam = cfg.webcam_region or video_webcam(video)
    return ClipSource(
        clip_id=clip.id, video_id=video.id, src=Path(video.file_path), start=clip.start, end=clip.end,
        peak_time=clip.peak_time, title=clip.suggested_title or video.title, width=video.width or 1920,
        height=video.height or 1080, has_audio=video.has_audio, webcam=webcam, subtitles=clip.subtitles,
        config=cfg,
    )
