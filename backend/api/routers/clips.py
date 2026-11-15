from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.clip_detection.pipeline import load_transcript
from backend.clip_detection.scoring import clip_transcript
from backend.core.exceptions import NotFoundError, ValidationFailed
from backend.database.session import get_db
from backend.models.entities import Clip, Video
from backend.models.schemas import ClipCreate, ClipOut, ClipUpdate
from backend.services import preview
from backend.services import video_service as vs

router = APIRouter(prefix="/api", tags=["clips"])

SORTS = {"score": Clip.score.desc(), "start": Clip.start.asc(), "created": Clip.created_at.desc(),
         "confidence": Clip.confidence.desc()}


def clip_out(c: Clip) -> ClipOut:
    out = ClipOut.model_validate(c)
    if c.video is not None:
        out.video_title, out.game = c.video.title, c.video.game
    return out


def _get(db: Session, clip_id: str) -> Clip:
    clip = db.get(Clip, clip_id)
    if clip is None:
        raise NotFoundError(f"Clip {clip_id} not found")
    return clip


def _validate_range(video: Video, start: float, end: float) -> None:
    if end - start < 1.0:
        raise ValidationFailed("A clip must be at least 1 second long")
    if video.duration and end > video.duration + 0.05:
        raise ValidationFailed(f"End ({end:.2f}s) is beyond the video duration ({video.duration:.2f}s)")


@router.get("/clips", response_model=list[ClipOut])
def list_clips(
    video_id: str | None = None, category: str | None = None, status: str | None = None,
    min_score: float | None = None, sort: str = Query("score", pattern="^(score|start|created|confidence)$"),
    limit: int = Query(200, ge=1, le=1000), db: Session = Depends(get_db),
):
    stmt = select(Clip).order_by(SORTS[sort]).limit(limit)
    if video_id:
        stmt = stmt.where(Clip.video_id == video_id)
    if category:
        stmt = stmt.where(Clip.category.in_(category.split(",")))
    if status:
        stmt = stmt.where(Clip.status.in_(status.split(",")))
    if min_score is not None:
        stmt = stmt.where(Clip.score >= min_score)
    return [clip_out(c) for c in db.scalars(stmt).all()]


@router.post("/videos/{video_id}/clips", response_model=ClipOut, status_code=201)
def create_clip(video_id: str, body: ClipCreate, db: Session = Depends(get_db)):
    video = vs.get_video(db, video_id)
    _validate_range(video, body.start, body.end)
    clip = Clip(video_id=video_id, start=round(body.start, 2), end=round(body.end, 2), category=body.category.value,
                suggested_title=body.suggested_title, origin="manual", score=0, confidence=1.0,
                reason="Clip creata manualmente", transcript=clip_transcript(load_transcript(video_id), body.start, body.end),
                language=video.analysis.language if video.analysis else "")
    db.add(clip)
    db.commit()
    db.refresh(clip)
    return clip_out(clip)


@router.get("/clips/{clip_id}", response_model=ClipOut)
def get_clip(clip_id: str, db: Session = Depends(get_db)):
    return clip_out(_get(db, clip_id))


@router.patch("/clips/{clip_id}", response_model=ClipOut)
def update_clip(clip_id: str, body: ClipUpdate, db: Session = Depends(get_db)):
    clip = _get(db, clip_id)
    data = body.model_dump(exclude_unset=True, exclude_none=True)
    start, end = data.get("start", clip.start), data.get("end", clip.end)
    if "start" in data or "end" in data:
        _validate_range(clip.video, start, end)
        if (round(start, 2), round(end, 2)) != (clip.start, clip.end):
            if clip.preview_path:
                Path(clip.preview_path).unlink(missing_ok=True)
                clip.preview_path = None
            clip.start, clip.end = round(start, 2), round(end, 2)
            clip.transcript = clip_transcript(load_transcript(clip.video_id), clip.start, clip.end)
    if "category" in data:
        clip.category = data["category"].value
    if "suggested_title" in data:
        clip.suggested_title = data["suggested_title"]
    if "status" in data:
        clip.status = data["status"]
        clip.approved_at = None  # any manual status change drops a previous approval
    db.commit()
    db.refresh(clip)
    return clip_out(clip)


@router.delete("/clips/{clip_id}")
def delete_clip(clip_id: str, confirm: bool = False, db: Session = Depends(get_db)) -> dict:
    if not confirm:
        raise ValidationFailed("Deletion requires explicit confirmation (confirm=true)", code="confirmation_required")
    clip = _get(db, clip_id)
    if clip.status == "rendering":
        raise ValidationFailed("Clip is rendering: cancel the render first")
    if clip.preview_path:
        Path(clip.preview_path).unlink(missing_ok=True)
    vs.remove_render_dirs(clip)
    db.delete(clip)
    db.commit()
    return {"deleted": clip_id}


@router.get("/clips/{clip_id}/preview")
def clip_preview(clip_id: str, db: Session = Depends(get_db)) -> FileResponse:
    clip = _get(db, clip_id)
    path = preview.ensure_preview(clip, clip.video)
    if clip.preview_path != str(path):
        clip.preview_path = str(path)
        db.commit()
    return FileResponse(path, media_type="video/mp4")
