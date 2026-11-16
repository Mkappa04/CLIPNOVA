"""Audio library: list / import (license required) / preview / edit / delete music and sound effects."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.core.config import get_settings
from backend.core.exceptions import NotFoundError, ValidationFailed
from backend.database.session import get_db
from backend.editing import audio_library as lib
from backend.editing import effects, vfx
from backend.editing.plan import MUSIC_MOODS, SFX_CATEGORIES
from backend.models.entities import AudioAsset

router = APIRouter(prefix="/api", tags=["audio"])

MOOD_LABEL = {"cinematic": "Cinematografica", "dynamic": "Dinamica", "electronic": "Elettronica",
              "chill": "Rilassata", "dramatic": "Drammatica", "gaming": "Gaming"}
MEDIA = {".wav": "audio/wav", ".mp3": "audio/mpeg", ".ogg": "audio/ogg", ".flac": "audio/flac",
         ".m4a": "audio/mp4", ".aac": "audio/aac", ".opus": "audio/ogg"}


def _asset(db: Session, asset_id: str) -> AudioAsset:
    a = db.get(AudioAsset, asset_id)
    if a is None:
        raise NotFoundError(f"Audio {asset_id} not found")
    return a


@router.get("/audio/meta")
def audio_meta() -> dict:
    s = get_settings()
    return {"moods": [{"id": m, "label": MOOD_LABEL[m]} for m in MUSIC_MOODS],
            "sfx_categories": [{"id": c, "label": c.replace("_", " "), "description": effects.DESCRIPTION.get(c, "")}
                               for c in SFX_CATEGORIES],
            "licenses": [{"id": k, "label": v} for k, v in lib.LICENSES.items()],
            "formats": sorted(lib.AUDIO_EXT), "max_mb": s.audio_import_max_mb, "max_s": s.audio_import_max_s}


@router.get("/audio")
def list_audio(kind: str | None = Query(None, pattern="^(music|sfx)$"), db: Session = Depends(get_db)) -> list[dict]:
    lib.ensure_builtin(db)
    stmt = select(AudioAsset).order_by(AudioAsset.kind, AudioAsset.origin.desc(), AudioAsset.category, AudioAsset.title)
    if kind:
        stmt = stmt.where(AudioAsset.kind == kind)
    out = []
    for a in db.scalars(stmt):
        d = lib.as_dict(a)
        d.pop("path", None)
        out.append(d)
    return out


@router.post("/audio", status_code=201)
async def import_audio(file: UploadFile = File(...), kind: str = Form(...), category: str = Form(...),
                       title: str = Form(""), license: str = Form(""), attribution: str = Form(""),
                       source_url: str = Form(""), notes: str = Form(""), rights_confirmed: bool = Form(False),
                       db: Session = Depends(get_db)) -> dict:
    limit = int(get_settings().audio_import_max_mb * 1024 * 1024)
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise ValidationFailed(f"File troppo grande (max {get_settings().audio_import_max_mb:.0f} MB)", code="too_large")
    a = lib.import_file(db, data, file.filename or "audio", kind=kind, category=category, title=title,
                        license=license, attribution=attribution, source_url=source_url, notes=notes,
                        rights_confirmed=rights_confirmed)
    d = lib.as_dict(a)
    d.pop("path", None)
    return d


class AudioPatch(BaseModel):
    title: str | None = Field(None, max_length=160)
    category: str | None = None
    enabled: bool | None = None
    gain_db: float | None = Field(None, ge=-18, le=12)
    attribution: str | None = Field(None, max_length=500)
    source_url: str | None = Field(None, max_length=500)
    notes: str | None = Field(None, max_length=1000)


@router.patch("/audio/{asset_id}")
def patch_audio(asset_id: str, body: AudioPatch, db: Session = Depends(get_db)) -> dict:
    a = _asset(db, asset_id)
    data = body.model_dump(exclude_none=True)
    if "category" in data:
        valid = MUSIC_MOODS if a.kind == "music" else SFX_CATEGORIES
        if data["category"] not in valid or a.origin == "builtin":
            raise ValidationFailed("Categoria non valida (gli asset di serie non cambiano categoria)",
                                   code="invalid_category")
    if a.origin == "builtin":
        data = {k: v for k, v in data.items() if k in ("enabled", "gain_db")}
    for k, v in data.items():
        setattr(a, k, v)
    db.commit()
    d = lib.as_dict(a)
    d.pop("path", None)
    return d


@router.delete("/audio/{asset_id}")
def delete_audio(asset_id: str, confirm: bool = False, db: Session = Depends(get_db)) -> dict:
    if not confirm:
        raise ValidationFailed("Deletion requires explicit confirmation (confirm=true)", code="confirmation_required")
    lib.delete_asset(db, _asset(db, asset_id))
    return {"deleted": asset_id}


@router.get("/audio/{asset_id}/file")
def audio_file(asset_id: str, db: Session = Depends(get_db)) -> FileResponse:
    a = _asset(db, asset_id)
    p = Path(a.path)
    if not p.exists():
        raise NotFoundError("Audio file missing")
    return FileResponse(p, media_type=MEDIA.get(p.suffix.lower(), "application/octet-stream"),
                        headers={"Cache-Control": "max-age=300"})


@router.get("/editing/effects")
def effects_catalog() -> dict:
    """What the Visual Effects Engine can do, and the colour looks."""
    return {"effects": vfx.CATALOG,
            "looks": [{"id": k, "label": v["label"]} for k, v in vfx.LOOKS.items()]}
