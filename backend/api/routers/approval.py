from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.api.routers.clips import clip_out
from backend.api.routers.editing import render_out
from backend.content_generation import llm
from backend.core.exceptions import NotFoundError, ValidationFailed
from backend.database.session import get_db
from backend.models.entities import Clip, Export
from backend.models.schemas import ContentIn, ExportOut, ExportRequest, ReviewAction
from backend.publishing import exporter
from backend.rights_management.policy import Purpose
from backend.services import approval

router = APIRouter(prefix="/api", tags=["approval"])
QUEUE_STATES = ("review", "approved", "rejected", "archived", "exported")


def _clip(db: Session, clip_id: str) -> Clip:
    clip = db.get(Clip, clip_id)
    if clip is None:
        raise NotFoundError(f"Clip {clip_id} not found")
    return clip


def review_item(clip: Clip) -> dict:
    r = approval.latest_render(clip)
    return {"clip": clip_out(clip).model_dump(mode="json"), "render": render_out(r).model_dump(mode="json") if r else None,
            "content": clip.content, "review_note": clip.review_note,
            "approved_at": clip.approved_at.isoformat() + "Z" if clip.approved_at else None,
            "rights": approval.rights_summary(clip), "attribution": approval.attribution_text(clip)}


@router.get("/approval/queue")
def queue(status: str = Query("review"), db: Session = Depends(get_db)) -> list[dict]:
    states = [s for s in status.split(",") if s in QUEUE_STATES]
    clips = db.scalars(select(Clip).where(Clip.status.in_(states)).order_by(Clip.updated_at.desc())).all()
    return [review_item(c) for c in clips]


@router.get("/approval/counts")
def counts(db: Session = Depends(get_db)) -> dict:
    from sqlalchemy import func

    rows = db.execute(select(Clip.status, func.count()).where(Clip.status.in_(QUEUE_STATES)).group_by(Clip.status)).all()
    return {s: 0 for s in QUEUE_STATES} | dict(rows)


@router.get("/clips/{clip_id}/review")
def get_review(clip_id: str, db: Session = Depends(get_db)) -> dict:
    return review_item(_clip(db, clip_id))


class GenerateRequest(BaseModel):
    use_llm: bool = False
    language: str | None = None


@router.post("/clips/{clip_id}/content/generate")
def generate(clip_id: str, body: GenerateRequest, db: Session = Depends(get_db)) -> dict:
    """Draft copy (not saved): template mode, optionally rewritten by the local LLM."""
    clip = _clip(db, clip_id)
    lang = body.language if body.language in ("it", "en") else None
    content, warnings = approval.generate_content(clip, use_llm=body.use_llm, language=lang)
    return {"content": content, "warnings": warnings}


@router.put("/clips/{clip_id}/content")
def put_content(clip_id: str, body: ContentIn, db: Session = Depends(get_db)) -> dict:
    clip = _clip(db, clip_id)
    revoked = approval.set_content(clip, body.model_dump())
    db.commit()
    return {**review_item(clip), "approval_revoked": revoked}


@router.post("/clips/{clip_id}/approve")
def approve(clip_id: str, body: ReviewAction = ReviewAction(), db: Session = Depends(get_db)) -> dict:
    clip = _clip(db, clip_id)
    approval.approve(clip, body.note)
    db.commit()
    return review_item(clip)


@router.post("/clips/{clip_id}/reject")
def reject(clip_id: str, body: ReviewAction = ReviewAction(), db: Session = Depends(get_db)) -> dict:
    clip = _clip(db, clip_id)
    approval.reject(clip, body.note)
    db.commit()
    return review_item(clip)


@router.post("/clips/{clip_id}/archive")
def archive(clip_id: str, db: Session = Depends(get_db)) -> dict:
    clip = _clip(db, clip_id)
    approval.archive(clip)
    db.commit()
    return review_item(clip)


@router.post("/clips/{clip_id}/reopen")
def reopen(clip_id: str, db: Session = Depends(get_db)) -> dict:
    clip = _clip(db, clip_id)
    approval.reopen(clip)
    db.commit()
    return review_item(clip)


@router.post("/clips/{clip_id}/regenerate", status_code=202)
def regenerate(clip_id: str, db: Session = Depends(get_db)) -> dict:
    """Re-render with the saved edit settings (the clip returns to review afterwards)."""
    from backend.api.routers.editing import start_render

    return start_render(clip_id, db=db)


@router.get("/llm/status")
def llm_status() -> dict:
    return llm.status()


# ---------------------------------------------------------------- exports
def export_out(e: Export) -> ExportOut:
    out = ExportOut.model_validate(e)
    folder = Path(e.path)
    out.files = sorted(f.name for f in folder.iterdir()) if folder.is_dir() else []
    out.clip_title = (e.content_snapshot or {}).get("content", {}).get("title", "") or (e.clip.suggested_title if e.clip else "")
    out.video_title = e.clip.video.title if e.clip else ""
    return out


@router.get("/clips/{clip_id}/export-check")
def export_check(clip_id: str, purpose: Purpose = Purpose.COMMERCIAL, db: Session = Depends(get_db)) -> dict:
    clip = _clip(db, clip_id)
    try:
        return {"allowed": True, "decision": exporter.check_exportable(clip, purpose)}
    except ValidationFailed as e:
        return {"allowed": False, "decision": None, "message": e.message}
    except Exception as e:  # RightsViolation
        return {"allowed": False, "decision": getattr(e, "details", None), "message": str(e)}


@router.post("/clips/{clip_id}/export", response_model=ExportOut, status_code=201)
def create_export(clip_id: str, body: ExportRequest, db: Session = Depends(get_db)):
    clip = _clip(db, clip_id)
    exp = exporter.create_export(clip, list(body.platforms), Purpose(body.purpose))
    db.add(exp)
    db.commit()
    db.refresh(exp)
    return export_out(exp)


@router.get("/exports", response_model=list[ExportOut])
def list_exports(clip_id: str | None = None, limit: int = Query(100, ge=1, le=500), db: Session = Depends(get_db)):
    stmt = select(Export).order_by(Export.created_at.desc()).limit(limit)
    if clip_id:
        stmt = stmt.where(Export.clip_id == clip_id)
    return [export_out(e) for e in db.scalars(stmt).all()]


@router.get("/exports/{export_id}/files/{name}")
def export_file(export_id: str, name: str, db: Session = Depends(get_db)) -> FileResponse:
    e = db.get(Export, export_id)
    if e is None:
        raise NotFoundError("Export not found")
    folder = Path(e.path).resolve()
    f = (folder / name).resolve()
    if f.parent != folder or not f.is_file():
        raise NotFoundError("File not found")
    return FileResponse(f, filename=name if name.endswith((".zip", ".mp4", ".srt")) else None)


@router.delete("/exports/{export_id}")
def delete_export(export_id: str, confirm: bool = False, db: Session = Depends(get_db)) -> dict:
    import shutil

    from backend.core.config import get_settings

    if not confirm:
        raise ValidationFailed("Deletion requires explicit confirmation (confirm=true)", code="confirmation_required")
    e = db.get(Export, export_id)
    if e is None:
        raise NotFoundError("Export not found")
    root = get_settings().exports_dir.resolve()
    d = Path(e.path).resolve()
    if d.parent == root and d.is_dir():
        shutil.rmtree(d, ignore_errors=True)  # copies made outside data/ (export_copy_dir) are left untouched
    db.delete(e)
    db.commit()
    return {"deleted": export_id}


