from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.automation.common import AUTOMATION_DEFAULTS, automation_settings, can_run_heavy, put_setting
from backend.automation.pipeline import PIPELINE_DEFAULTS, pipeline_config
from backend.automation.watcher import watcher
from backend.core.config import SUPPORTED_VIDEO_EXTENSIONS, get_settings
from backend.core.exceptions import NotFoundError, ValidationFailed
from backend.core.timeutil import utcnow
from backend.database.session import get_db
from backend.editing.config import EditConfig
from backend.models.automation_entities import Creator, Notification, WatchedFile, WatchFolder
from backend.models.schemas import RightsIn
from backend.services.video_service import windows_to_wsl

router = APIRouter(prefix="/api", tags=["automation"])


class PipelineIn(BaseModel):
    analyze: bool = True
    language: str = Field("auto", pattern="^(auto|it|en)$")
    render_top_n: int = Field(3, ge=0, le=10)
    min_score: float = Field(45, ge=0, le=100)
    detect_webcam: bool = True
    edit_config: dict = Field(default_factory=dict)


class FolderIn(BaseModel):
    name: str = Field("", max_length=200)
    path: str
    enabled: bool = True
    recursive: bool = False
    extensions: list[str] = Field(default_factory=lambda: [".mp4", ".mkv", ".mov"])
    mode: str = Field("reference", pattern="^(reference|copy)$")
    game: str = "GTA 6"
    creator_name: str = ""
    source: str = ""
    rights: RightsIn = Field(default_factory=lambda: RightsIn(license_type="own_content", authorization_status="authorized",
                                                             commercial_use_allowed=True, attribution_required=False))
    pipeline: PipelineIn = Field(default_factory=PipelineIn)
    creator_id: str | None = None


def folder_out(db: Session, f: WatchFolder) -> dict:
    counts = dict(db.execute(select(WatchedFile.status, func.count()).where(WatchedFile.folder_id == f.id)
                             .group_by(WatchedFile.status)).all())
    p = Path(f.path)
    return {"id": f.id, "name": f.name, "path": f.path, "enabled": f.enabled, "recursive": f.recursive,
            "extensions": f.extensions, "mode": f.mode, "game": f.game, "creator_name": f.creator_name,
            "source": f.source, "rights": f.rights, "pipeline": pipeline_config(f.pipeline),
            "creator_id": f.creator_id, "creator": f.creator.name if f.creator else None,
            "exists": p.is_dir(), "on_windows": str(p).startswith("/mnt/"),
            "last_scan_at": f.last_scan_at.isoformat() + "Z" if f.last_scan_at else None,
            "last_error": f.last_error, "counts": counts}


def _validate(body: FolderIn) -> tuple[Path, dict]:
    path, _ = windows_to_wsl(body.path)
    if not path.is_absolute():
        raise ValidationFailed("Il percorso deve essere assoluto")
    if not path.is_dir():
        raise ValidationFailed(f"Cartella non trovata: {path}")
    root = get_settings().data_dir.resolve()
    if path.resolve() == root or root in path.resolve().parents:
        raise ValidationFailed("Non puoi monitorare la cartella dati di CLIPNOVA")
    exts = [e.lower() if e.startswith(".") else f".{e.lower()}" for e in body.extensions]
    bad = [e for e in exts if e not in SUPPORTED_VIDEO_EXTENSIONS]
    if bad:
        raise ValidationFailed(f"Estensioni non supportate: {', '.join(bad)}")
    EditConfig.model_validate(body.pipeline.edit_config or {})  # fail early on invalid edit settings
    data = body.model_dump()
    data["extensions"] = exts
    data["rights"] = body.rights.model_dump(mode="json")
    data["path"] = str(path)
    return path, data


@router.get("/automation/status")
def status(db: Session = Depends(get_db)) -> dict:
    cfg = automation_settings(db)
    ok, reason = can_run_heavy(cfg)
    counts = dict(db.execute(select(WatchedFile.status, func.count()).group_by(WatchedFile.status)).all())
    s = get_settings()
    return {"settings": cfg, "watcher_running": watcher.running, "watcher_enabled": s.automation_enabled,
            "poll_s": s.automation_poll_s, "stable_s": s.automation_stable_s, "remux_grace_s": s.automation_remux_grace_s,
            "last_tick_at": watcher.last_tick_at.isoformat() + "Z" if watcher.last_tick_at else None,
            "last_tick_stats": watcher.last_tick_stats, "can_run_now": ok, "blocked_reason": reason,
            "counts": counts, "pipeline_defaults": PIPELINE_DEFAULTS}


class AutomationSettingsIn(BaseModel):
    paused: bool = False
    window: dict = Field(default_factory=lambda: dict(AUTOMATION_DEFAULTS["window"]))
    idle_only: bool = False
    idle_max_cpu: float = Field(0.6, gt=0, le=4)
    idle_max_gpu: int = Field(35, ge=1, le=100)


@router.put("/automation/settings")
def put_settings(body: AutomationSettingsIn, db: Session = Depends(get_db)) -> dict:
    from datetime import time

    w = body.window
    try:
        time.fromisoformat(w.get("start", "22:00"))
        time.fromisoformat(w.get("end", "07:00"))
    except ValueError as e:
        raise ValidationFailed("Orari non validi (HH:MM)") from e
    put_setting(db, "automation", body.model_dump())
    db.commit()
    return status(db)


@router.post("/automation/scan")
def scan_now() -> dict:
    return watcher.tick()


@router.get("/watch-folders")
def folders(db: Session = Depends(get_db)) -> list[dict]:
    return [folder_out(db, f) for f in db.scalars(select(WatchFolder).order_by(WatchFolder.created_at)).all()]


@router.post("/watch-folders", status_code=201)
def add_folder(body: FolderIn, db: Session = Depends(get_db)) -> dict:
    _, data = _validate(body)
    if data.get("creator_id") and db.get(Creator, data["creator_id"]) is None:
        raise ValidationFailed("Creator non trovato")
    if db.scalar(select(WatchFolder).where(WatchFolder.path == data["path"])):
        raise ValidationFailed("Questa cartella è già monitorata")
    f = WatchFolder(**data)
    db.add(f)
    db.commit()
    return folder_out(db, f)


@router.put("/watch-folders/{folder_id}")
def update_folder(folder_id: str, body: FolderIn, db: Session = Depends(get_db)) -> dict:
    f = db.get(WatchFolder, folder_id)
    if f is None:
        raise NotFoundError("Cartella non trovata")
    _, data = _validate(body)
    for k, v in data.items():
        setattr(f, k, v)
    db.commit()
    return folder_out(db, f)


@router.delete("/watch-folders/{folder_id}")
def delete_folder(folder_id: str, confirm: bool = False, db: Session = Depends(get_db)) -> dict:
    """Stops monitoring. Files on disk and already imported videos are never touched."""
    if not confirm:
        raise ValidationFailed("Conferma richiesta (confirm=true)", code="confirmation_required")
    f = db.get(WatchFolder, folder_id)
    if f is None:
        raise NotFoundError("Cartella non trovata")
    db.delete(f)
    db.commit()
    return {"deleted": folder_id}


@router.get("/watch-folders/files")
def files(folder_id: str | None = None, status: str | None = None, limit: int = Query(200, ge=1, le=1000),
          db: Session = Depends(get_db)) -> list[dict]:
    stmt = select(WatchedFile).order_by(WatchedFile.updated_at.desc()).limit(limit)
    if folder_id:
        stmt = stmt.where(WatchedFile.folder_id == folder_id)
    if status:
        stmt = stmt.where(WatchedFile.status.in_(status.split(",")))
    out = []
    for wf in db.scalars(stmt).all():
        out.append({"id": wf.id, "folder_id": wf.folder_id, "name": Path(wf.path).name, "path": wf.path, "size": wf.size,
                    "status": wf.status, "reason": wf.reason, "stage": wf.stage, "video_id": wf.video_id,
                    "job_id": wf.job_id, "attempts": wf.attempts,
                    "first_seen_at": wf.first_seen_at.isoformat() + "Z", "updated_at": wf.updated_at.isoformat() + "Z"})
    return out


@router.post("/watch-folders/files/{file_id}/retry")
def retry_file(file_id: str, db: Session = Depends(get_db)) -> dict:
    wf = db.get(WatchedFile, file_id)
    if wf is None:
        raise NotFoundError("File non trovato")
    if wf.status not in ("error", "skipped"):
        raise ValidationFailed("Solo file in errore o scartati possono essere ripresi")
    wf.status = "ready" if wf.video_id else "waiting"
    wf.reason, wf.attempts, wf.last_change_at = "Ripresa manuale", 0, utcnow()
    db.commit()
    return {"status": wf.status}


# ---------------------------------------------------------------- notifications
@router.get("/notifications")
def notifications(unread_only: bool = False, limit: int = Query(30, ge=1, le=200), db: Session = Depends(get_db)) -> dict:
    stmt = select(Notification).order_by(Notification.created_at.desc()).limit(limit)
    if unread_only:
        stmt = stmt.where(Notification.read.is_(False))
    unread = db.scalar(select(func.count()).select_from(Notification).where(Notification.read.is_(False))) or 0
    return {"unread": unread, "items": [{"id": n.id, "kind": n.kind, "title": n.title, "body": n.body, "link": n.link,
                                         "read": n.read, "created_at": n.created_at.isoformat() + "Z"}
                                        for n in db.scalars(stmt).all()]}


@router.post("/notifications/read")
def mark_read(db: Session = Depends(get_db)) -> dict:
    db.query(Notification).filter(Notification.read.is_(False)).update({"read": True})
    db.commit()
    return {"unread": 0}
