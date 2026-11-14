from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import ValidationError
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from backend.core.exceptions import NotFoundError, ValidationFailed
from backend.database.session import get_db
from backend.models.entities import StorageMode, Video, VideoStatus
from backend.models.schemas import (
    ImportPathRequest,
    ImportResult,
    RightsDecisionOut,
    RightsIn,
    RightsOut,
    VideoOut,
    VideoUpdate,
)
from backend.rights_management.policy import Purpose, evaluate
from backend.services import video_service as vs
from backend.workers.queue import job_manager

router = APIRouter(prefix="/api/videos", tags=["videos"])


@router.get("", response_model=list[VideoOut])
def list_videos(
    q: str | None = None, game: str | None = None, status: str | None = None,
    db: Session = Depends(get_db),
) -> list[VideoOut]:
    stmt = select(Video).order_by(Video.created_at.desc())
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Video.title.ilike(like), Video.creator.ilike(like),
                              Video.original_filename.ilike(like)))
    if game:
        stmt = stmt.where(Video.game == game)
    if status:
        stmt = stmt.where(Video.status == status)
    return [vs.to_out(db, v) for v in db.scalars(stmt).unique().all()]


@router.get("/games", response_model=list[str])
def list_games(db: Session = Depends(get_db)) -> list[str]:
    return sorted(set(db.scalars(select(Video.game)).all()) | {"GTA 6"})


@router.post("/upload", response_model=ImportResult, status_code=201)
def upload_videos(
    files: list[UploadFile] = File(...),
    game: str = Form("GTA 6"),
    creator: str = Form(""),
    source: str = Form(""),
    notes: str = Form(""),
    rights: str = Form("{}"),
    db: Session = Depends(get_db),
) -> ImportResult:
    try:
        rights_in = RightsIn.model_validate(json.loads(rights or "{}"))
    except (json.JSONDecodeError, ValidationError) as e:
        raise ValidationFailed(f"Invalid rights data: {e}") from e
    for f in files:
        vs.check_extension(f.filename or "")

    created: list[Video] = []
    saved: list[Path] = []
    try:
        for f in files:
            path, size = vs.save_upload_stream(f.file, f.filename or "video")
            saved.append(path)
            created.append(vs.create_video(
                db, file_path=path, original_filename=f.filename or path.name,
                storage_mode=StorageMode.UPLOADED, file_size=size, title=None, game=game,
                creator=creator, source=source, notes=notes, rights=rights_in))
        db.commit()
    except Exception:
        db.rollback()
        for p in saved:
            p.unlink(missing_ok=True)
        raise

    job_ids = [job_manager.submit("video.probe", {"video_id": v.id}, video_id=v.id) for v in created]
    return ImportResult(videos=[vs.to_out(db, v) for v in created], job_ids=job_ids)


@router.post("/import-path", response_model=ImportResult, status_code=201)
def import_from_path(req: ImportPathRequest, db: Session = Depends(get_db)) -> ImportResult:
    path, warnings = vs.resolve_import_path(req.path)
    video = vs.create_video(
        db, file_path=path, original_filename=path.name, storage_mode=StorageMode.REFERENCED,
        file_size=path.stat().st_size, title=req.title, game=req.game, creator=req.creator,
        source=req.source, notes=req.notes, rights=req.rights,
        status=VideoStatus.COPYING if req.mode == "copy" else VideoStatus.PENDING,
    )
    db.commit()
    if req.mode == "copy":
        job_id = job_manager.submit("video.copy_import", {"video_id": video.id, "source_path": str(path)},
                                    video_id=video.id)
    else:
        job_id = job_manager.submit("video.probe", {"video_id": video.id}, video_id=video.id)
    return ImportResult(videos=[vs.to_out(db, video)], job_ids=[job_id], warnings=warnings)


@router.get("/{video_id}", response_model=VideoOut)
def get_video(video_id: str, db: Session = Depends(get_db)) -> VideoOut:
    return vs.to_out(db, vs.get_video(db, video_id))


@router.patch("/{video_id}", response_model=VideoOut)
def update_video(video_id: str, body: VideoUpdate, db: Session = Depends(get_db)) -> VideoOut:
    video = vs.get_video(db, video_id)
    for k, v in body.model_dump(exclude_unset=True).items():
        if v is not None:
            setattr(video, k, v.strip() if isinstance(v, str) and k != "notes" else v)
    db.commit()
    return vs.to_out(db, video)


@router.delete("/{video_id}")
def delete_video(
    video_id: str,
    confirm: bool = Query(False, description="Must be true: deletion is irreversible"),
    delete_file: bool = Query(False, description="Also delete the file, only if managed by CLIPNOVA"),
    db: Session = Depends(get_db),
) -> dict:
    if not confirm:
        raise ValidationFailed("Deletion requires explicit confirmation (confirm=true)",
                               code="confirmation_required")
    video = vs.get_video(db, video_id)
    result = vs.delete_video(db, video, delete_file)
    db.commit()
    return {"deleted": video_id, **result}


@router.post("/{video_id}/reprobe")
def reprobe(video_id: str, db: Session = Depends(get_db)) -> dict:
    video = vs.get_video(db, video_id)
    if not Path(video.file_path).exists():
        raise ValidationFailed(f"Source file is missing: {video.file_path}")
    return {"job_id": job_manager.submit("video.probe", {"video_id": video.id}, video_id=video.id)}


@router.get("/{video_id}/thumbnail")
def thumbnail(video_id: str, db: Session = Depends(get_db)) -> FileResponse:
    video = vs.get_video(db, video_id)
    if not video.thumbnail_path or not Path(video.thumbnail_path).exists():
        raise NotFoundError("No thumbnail")
    return FileResponse(video.thumbnail_path, media_type="image/jpeg",
                        headers={"Cache-Control": "max-age=300"})


@router.get("/{video_id}/stream")
def stream(video_id: str, db: Session = Depends(get_db)) -> FileResponse:
    video = vs.get_video(db, video_id)
    path = Path(video.file_path)
    if not path.exists():
        raise NotFoundError("Source file is missing")
    media = {".mp4": "video/mp4", ".m4v": "video/mp4", ".mov": "video/quicktime",
             ".webm": "video/webm", ".mkv": "video/x-matroska"}.get(path.suffix.lower(), "application/octet-stream")
    return FileResponse(path, media_type=media)


# ---------------------------------------------------------------- rights
@router.get("/{video_id}/rights", response_model=RightsOut | None)
def get_rights(video_id: str, db: Session = Depends(get_db)):
    return vs.get_video(db, video_id).rights


@router.put("/{video_id}/rights", response_model=RightsOut)
def put_rights(video_id: str, body: RightsIn, db: Session = Depends(get_db)):
    video = vs.get_video(db, video_id)
    record = vs.apply_rights(video, body)
    db.commit()
    db.refresh(record)
    return record


@router.get("/{video_id}/rights/check", response_model=RightsDecisionOut)
def check_rights(video_id: str, purpose: Purpose = Purpose.COMMERCIAL, db: Session = Depends(get_db)):
    video = vs.get_video(db, video_id)
    return evaluate(video.rights, purpose).as_dict()
