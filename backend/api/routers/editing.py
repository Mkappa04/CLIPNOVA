from __future__ import annotations

import shutil
from pathlib import Path

import cv2
from fastapi import APIRouter, Body, Depends, Query
from fastapi.responses import FileResponse, PlainTextResponse, Response
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.core.config import get_settings
from backend.core.exceptions import ConflictError, NotFoundError, ValidationFailed
from backend.database.session import get_db
from backend.editing import service
from backend.editing.config import LAYOUT_NEEDS_WEBCAM, EditConfig, Region
from backend.editing.frames import grab_frame
from backend.editing.renderer import preview_frame, source_cues
from backend.editing.webcam import detect_webcam
from backend.models.entities import ACTIVE_JOB_STATUSES, Clip, Job, Render
from backend.models.schemas import RenderOut, SubtitlesIn
from backend.services import video_service as vs
from backend.subtitles.ass import build_ass, build_srt
from backend.subtitles.cues import validate_cues
from backend.subtitles.presets import PRESETS, get_preset
from backend.workers.queue import job_manager

router = APIRouter(prefix="/api", tags=["editing"])


def _clip(db: Session, clip_id: str) -> Clip:
    clip = db.get(Clip, clip_id)
    if clip is None:
        raise NotFoundError(f"Clip {clip_id} not found")
    if not Path(clip.video.file_path).exists():
        raise ValidationFailed(f"Source video missing: {clip.video.file_path}")
    return clip


def render_out(r: Render) -> RenderOut:
    out = RenderOut.model_validate(r)
    out.clip_title = r.clip.suggested_title if r.clip else ""
    out.video_title = r.clip.video.title if r.clip else ""
    out.game = r.clip.video.game if r.clip else ""
    out.has_thumbnail = bool(r.thumbnail_path and Path(r.thumbnail_path).exists())
    return out


# ---------------------------------------------------------------- presets & config
@router.get("/subtitles/presets")
def presets() -> list[dict]:
    return [p.as_dict() for p in PRESETS.values()]


@router.get("/edit/defaults")
def edit_defaults() -> dict:
    return {"config": EditConfig().model_dump(), "schema": EditConfig.model_json_schema()}


@router.get("/clips/{clip_id}/edit")
def get_edit(clip_id: str, db: Session = Depends(get_db)) -> dict:
    clip = _clip(db, clip_id)
    cfg = service.effective_config(clip)
    webcam = cfg.webcam_region or service.video_webcam(clip.video)
    warnings = []
    if cfg.layout in LAYOUT_NEEDS_WEBCAM and webcam is None:
        warnings.append("Questo layout richiede la regione webcam: rilevala o selezionala a mano")
    return {"config": cfg.model_dump(), "saved": bool(clip.edit_config), "webcam_region": webcam.model_dump() if webcam else None,
            "warnings": warnings}


@router.put("/clips/{clip_id}/edit")
def put_edit(clip_id: str, cfg: EditConfig, db: Session = Depends(get_db)) -> dict:
    clip = _clip(db, clip_id)
    clip.edit_config = cfg.model_dump()
    db.commit()
    return get_edit(clip_id, db)


class FrameRequest(BaseModel):
    t: float = 0.0
    config: EditConfig | None = None


@router.post("/clips/{clip_id}/preview-frame")
def clip_preview_frame(clip_id: str, body: FrameRequest = Body(default_factory=FrameRequest),
                       db: Session = Depends(get_db)) -> Response:
    """Composed 9:16 frame (540x960 JPEG) with subtitles, for the editor preview. Unsaved config allowed."""
    clip = _clip(db, clip_id)
    jpg = preview_frame(service.clip_source(clip, body.config), body.t)
    return Response(jpg, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


# ---------------------------------------------------------------- webcam
@router.get("/videos/{video_id}/frame")
def video_frame(video_id: str, t: float = 0.0, db: Session = Depends(get_db)) -> Response:
    video = vs.get_video(db, video_id)
    frame = grab_frame(Path(video.file_path), t, video.width or 1920, video.height or 1080, max_w=960)
    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return Response(buf.tobytes(), media_type="image/jpeg", headers={"Cache-Control": "max-age=60"})


@router.post("/videos/{video_id}/webcam/detect")
def webcam_detect(video_id: str, save: bool = True, db: Session = Depends(get_db)) -> dict:
    video = vs.get_video(db, video_id)
    if not video.duration:
        raise ValidationFailed("Video metadata not ready")
    det = detect_webcam(Path(video.file_path), video.duration, video.width or 1920, video.height or 1080)
    if det.region is not None and save:
        current = service.video_webcam(video)
        if current is None or current.source == "auto":  # never overwrite a manual selection
            video.webcam_region = det.region.model_dump()
            db.commit()
    return {**det.as_dict(), "saved_region": video.webcam_region}


@router.put("/videos/{video_id}/webcam")
def webcam_set(video_id: str, region: Region | None = None, db: Session = Depends(get_db)) -> dict:
    video = vs.get_video(db, video_id)
    video.webcam_region = region.model_copy(update={"source": "manual", "confidence": 1.0}).model_dump() if region else None
    db.commit()
    return {"webcam_region": video.webcam_region}


# ---------------------------------------------------------------- subtitles
@router.get("/clips/{clip_id}/subtitles")
def get_subtitles(clip_id: str, db: Session = Depends(get_db)) -> dict:
    clip = _clip(db, clip_id)
    cs = service.clip_source(clip)
    return {"cues": source_cues(cs), "edited": clip.subtitles is not None, "preset": cs.config.subtitle_preset,
            "duration": clip.duration}


@router.put("/clips/{clip_id}/subtitles")
def put_subtitles(clip_id: str, body: SubtitlesIn, db: Session = Depends(get_db)) -> dict:
    clip = _clip(db, clip_id)
    cues = validate_cues([c.model_dump() for c in body.cues], clip.duration)
    clip.subtitles = cues
    db.commit()
    return get_subtitles(clip_id, db)


@router.delete("/clips/{clip_id}/subtitles")
def reset_subtitles(clip_id: str, confirm: bool = False, db: Session = Depends(get_db)) -> dict:
    if not confirm:
        raise ValidationFailed("Resetting discards your subtitle edits: pass confirm=true", code="confirmation_required")
    clip = _clip(db, clip_id)
    clip.subtitles = None
    db.commit()
    return get_subtitles(clip_id, db)


@router.get("/clips/{clip_id}/subtitles/export")
def export_subtitles(clip_id: str, format: str = Query("srt", pattern="^(srt|ass)$"), db: Session = Depends(get_db)):
    """Clip-relative subtitles (no silence cuts / intro): for use in external editors."""
    clip = _clip(db, clip_id)
    cs = service.clip_source(clip)
    cues = source_cues(cs)
    if format == "srt":
        body, media = build_srt(cues), "application/x-subrip"
    else:
        body = build_ass(cues, get_preset(cs.config.subtitle_preset), position=cs.config.subtitle_position,
                         highlight=cs.config.highlight_words, scale=cs.config.subtitle_scale)
        media = "text/x-ssa"
    return PlainTextResponse(body, media_type=media,
                             headers={"Content-Disposition": f'attachment; filename="clip_{clip.id[:8]}.{format}"'})


# ---------------------------------------------------------------- render
class RenderRequest(BaseModel):
    config: EditConfig | None = None


@router.post("/clips/{clip_id}/render", status_code=202)
def start_render(clip_id: str, body: RenderRequest = Body(default_factory=RenderRequest),
                 db: Session = Depends(get_db)) -> dict:
    clip = _clip(db, clip_id)
    active = db.scalar(select(func.count(Job.id)).where(
        Job.type == "render.clip", Job.status.in_(ACTIVE_JOB_STATUSES), Job.payload["clip_id"].as_string() == clip_id))
    if active:
        raise ConflictError("A render for this clip is already queued or running")
    if body.config is not None:
        clip.edit_config = body.config.model_dump()
        db.commit()
    job_id = job_manager.submit("render.clip", {"clip_id": clip_id}, video_id=clip.video_id)
    return {"job_id": job_id}


@router.get("/renders", response_model=list[RenderOut])
def list_renders(clip_id: str | None = None, status: str | None = None,
                 limit: int = Query(100, ge=1, le=500), db: Session = Depends(get_db)):
    stmt = select(Render).order_by(Render.created_at.desc()).limit(limit)
    if clip_id:
        stmt = stmt.where(Render.clip_id == clip_id)
    if status:
        stmt = stmt.where(Render.status.in_(status.split(",")))
    return [render_out(r) for r in db.scalars(stmt).all()]


def _render(db: Session, render_id: str) -> Render:
    r = db.get(Render, render_id)
    if r is None:
        raise NotFoundError(f"Render {render_id} not found")
    return r


@router.get("/renders/{render_id}/file")
def render_file(render_id: str, download: bool = False, db: Session = Depends(get_db)) -> FileResponse:
    r = _render(db, render_id)
    if not r.path or not Path(r.path).exists():
        raise NotFoundError("Render file not available")
    name = f"clipnova_{(r.clip.suggested_title if r.clip else 'clip')[:40]}_{r.id[:6]}.mp4"
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in name)
    return FileResponse(r.path, media_type="video/mp4", filename=safe if download else None,
                        content_disposition_type="attachment" if download else "inline")


@router.get("/renders/{render_id}/thumbnail")
def render_thumbnail(render_id: str, db: Session = Depends(get_db)) -> FileResponse:
    r = _render(db, render_id)
    if not r.thumbnail_path or not Path(r.thumbnail_path).exists():
        raise NotFoundError("No thumbnail")
    return FileResponse(r.thumbnail_path, media_type="image/jpeg")


@router.get("/renders/{render_id}/subtitles")
def render_subtitles(render_id: str, format: str = Query("srt", pattern="^(srt|ass)$"), db: Session = Depends(get_db)):
    r = _render(db, render_id)
    path = r.srt_path if format == "srt" else r.ass_path
    if not path or not Path(path).exists():
        raise NotFoundError("Subtitles not available")
    return FileResponse(path, filename=f"clipnova_{r.id[:6]}.{format}")


@router.delete("/renders/{render_id}")
def delete_render(render_id: str, confirm: bool = False, db: Session = Depends(get_db)) -> dict:
    if not confirm:
        raise ValidationFailed("Deletion requires explicit confirmation (confirm=true)", code="confirmation_required")
    r = _render(db, render_id)
    if r.status == "rendering":
        raise ConflictError("Render in progress: cancel the job first")
    root = get_settings().renders_dir.resolve()
    d = (root / r.id).resolve()
    if d.parent == root and d.is_dir():
        shutil.rmtree(d, ignore_errors=True)
    db.delete(r)
    db.commit()
    return {"deleted": render_id}
