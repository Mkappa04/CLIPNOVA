from __future__ import annotations

import re
import shutil
from datetime import date
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.automation import creators as crm
from backend.content_generation import llm
from backend.core.config import get_settings
from backend.core.exceptions import NotFoundError, ValidationFailed
from backend.database.session import get_db
from backend.models.automation_entities import Creator, CreatorPermission, WatchFolder
from backend.models.entities import new_id
from backend.services.video_service import windows_to_wsl

router = APIRouter(prefix="/api/creators", tags=["creators"])
EVIDENCE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".pdf", ".txt", ".eml", ".msg"}


def perm_out(p: CreatorPermission) -> dict:
    today = date.today()
    return {"id": p.id, "granted_at": p.granted_at.isoformat(), "expires_at": p.expires_at.isoformat() if p.expires_at else None,
            "scope": p.scope, "commercial_use": p.commercial_use, "attribution_text": p.attribution_text,
            "restrictions": p.restrictions, "evidence_text": p.evidence_text, "has_evidence_file": bool(p.evidence_file),
            "revoked": p.revoked, "valid": not p.revoked and (p.expires_at is None or p.expires_at >= today),
            "days_left": (p.expires_at - today).days if p.expires_at else None}


def creator_out(db: Session, c: Creator) -> dict:
    folders = db.scalars(select(WatchFolder).where(WatchFolder.creator_id == c.id)).all()
    return {"id": c.id, "name": c.name, "language": c.language, "channels": c.channels, "metrics": c.metrics,
            "score": c.score, "notes": c.notes, "contact": c.contact, "status": c.status,
            "status_label": crm.STATUS_LABELS.get(c.status, c.status), "status_history": c.status_history,
            "source": c.source, "permissions": [perm_out(p) for p in c.permissions],
            "watch_folders": [{"id": f.id, "path": f.path, "enabled": f.enabled} for f in folders],
            "created_at": c.created_at.isoformat() + "Z"}


def _get(db: Session, cid: str) -> Creator:
    c = db.get(Creator, cid)
    if c is None:
        raise NotFoundError("Creator non trovato")
    return c


class CreatorIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    language: str = ""
    channels: list[dict] = Field(default_factory=list)
    metrics: dict = Field(default_factory=dict)
    score: float = 0
    notes: str = ""
    contact: str = ""
    source: str = Field("manual", pattern="^(manual|discovery)$")


@router.get("")
def list_creators(status: str | None = None, db: Session = Depends(get_db)) -> list[dict]:
    stmt = select(Creator).order_by(Creator.updated_at.desc())
    if status:
        stmt = stmt.where(Creator.status.in_(status.split(",")))
    return [creator_out(db, c) for c in db.scalars(stmt).all()]


@router.post("", status_code=201)
def add_creator(body: CreatorIn, db: Session = Depends(get_db)) -> dict:
    # avoid duplicates from discovery: same platform channel id
    for ch in body.channels:
        if ch.get("channel_id"):
            for c in db.scalars(select(Creator)).all():
                if any(x.get("channel_id") == ch["channel_id"] and x.get("platform") == ch.get("platform") for x in c.channels):
                    return creator_out(db, c)
    c = Creator(**body.model_dump(), status="to_contact",
                status_history=[{"at": None, "from": None, "to": "to_contact", "note": f"Aggiunto ({body.source})"}])
    db.add(c)
    db.commit()
    return creator_out(db, c)


@router.patch("/{cid}")
def update_creator(cid: str, body: dict, db: Session = Depends(get_db)) -> dict:
    c = _get(db, cid)
    for k in ("name", "language", "notes", "contact", "channels"):
        if k in body:
            setattr(c, k, body[k])
    if "status" in body:
        crm.set_status(c, body["status"], body.get("note", ""))
    db.commit()
    return creator_out(db, c)


@router.delete("/{cid}")
def delete_creator(cid: str, confirm: bool = False, db: Session = Depends(get_db)) -> dict:
    if not confirm:
        raise ValidationFailed("Conferma richiesta (confirm=true)", code="confirmation_required")
    c = _get(db, cid)
    db.delete(c)
    db.commit()
    return {"deleted": cid}


class MessageIn(BaseModel):
    language: str = Field("it", pattern="^(it|en)$")
    sender: str = ""
    channel: str = ""
    game: str = "GTA 6"
    what: str = ""
    platforms: list[str] = Field(default_factory=lambda: ["tiktok", "instagram", "youtube"])
    commercial: bool = False
    attribution: str = ""
    remove_on_revoke: bool = True
    extra: str = ""
    use_llm: bool = False


@router.post("/{cid}/message")
def message(cid: str, body: MessageIn, db: Session = Depends(get_db)) -> dict:
    """Draft permission request. Sending stays manual (copy/paste): CLIPNOVA never sends messages."""
    c = _get(db, cid)
    text = crm.permission_message(language=body.language, creator=c.name, sender=body.sender, channel=body.channel,
                                  game=body.game, what=body.what, platforms=body.platforms, commercial=body.commercial,
                                  attribution=body.attribution, remove_on_revoke=body.remove_on_revoke, extra=body.extra)
    warnings: list[str] = []
    generated_by = "template"
    if body.use_llm:
        try:
            rewritten = _llm_polish(text, body.language)
            allowed = text + " " + " ".join(str(v) for v in body.model_dump().values())
            bad = crm.message_facts_ok(rewritten, allowed)
            if bad or llm.novelty(rewritten, allowed) > 0.35:
                warnings.append("Proposta LLM scartata: aggiungeva informazioni non presenti " + (f"({', '.join(bad)})" if bad else ""))
            else:
                text, generated_by = rewritten, f"ollama:{get_settings().llm_model}"
        except llm.LLMUnavailable as e:
            warnings.append(f"LLM locale non disponibile: {e}")
    return {"text": text, "generated_by": generated_by, "warnings": warnings,
            "note": "Copia il testo e invialo tu dal canale che preferisci: CLIPNOVA non invia messaggi."}


def _llm_polish(text: str, language: str) -> str:
    import httpx

    s = get_settings()
    if s.llm_provider != "ollama":
        raise llm.LLMUnavailable("LLM disabilitato (CLIPNOVA_LLM_PROVIDER=none)")
    prompt = (f"Rewrite this permission request to be friendly and concise in {'Italian' if language == 'it' else 'English'}. "
              "Keep EVERY condition and fact exactly (platforms, commercial use, credit, revocation). Do not add any new "
              "promise, number, link or detail. Return only the message text.\n\n" + text)
    try:
        r = httpx.post(f"{s.llm_url}/api/generate", json={"model": s.llm_model, "prompt": prompt, "stream": False,
                                                          "think": False, "keep_alive": 0}, timeout=s.llm_timeout_s)
        r.raise_for_status()
        return r.json().get("response", "").strip()
    except (httpx.HTTPError, ValueError) as e:
        raise llm.LLMUnavailable(str(e)) from e


@router.post("/{cid}/permissions", status_code=201)
async def add_permission(
    cid: str, granted_at: date = Form(...), expires_at: date | None = Form(None), scope: str = Form(""),
    commercial_use: bool = Form(False), attribution_text: str = Form(...), restrictions: str = Form(""),
    evidence_text: str = Form(""), evidence: UploadFile | None = File(None), db: Session = Depends(get_db),
) -> dict:
    c = _get(db, cid)
    if not attribution_text.strip():
        raise ValidationFailed("Indica il testo di attribuzione concordato")
    if not evidence_text.strip() and evidence is None:
        raise ValidationFailed("Registra una prova del consenso (testo del messaggio o file)")
    stored = None
    if evidence is not None and evidence.filename:
        ext = Path(evidence.filename).suffix.lower()
        if ext not in EVIDENCE_EXT:
            raise ValidationFailed(f"Tipo di file non ammesso: {ext}")
        folder = get_settings().data_dir / "evidence" / c.id
        folder.mkdir(parents=True, exist_ok=True)
        dest = folder / f"{new_id()[:10]}{ext}"
        with dest.open("wb") as out:
            shutil.copyfileobj(evidence.file, out)
        stored = str(dest)
    crm.add_permission(db, c, granted_at=granted_at, expires_at=expires_at, scope=scope, commercial_use=commercial_use,
                       attribution_text=attribution_text.strip(), restrictions=restrictions, evidence_text=evidence_text,
                       evidence_file=stored)
    db.commit()
    return creator_out(db, c)


@router.post("/{cid}/permissions/{pid}/revoke")
def revoke(cid: str, pid: str, db: Session = Depends(get_db)) -> dict:
    c = _get(db, cid)
    p = db.get(CreatorPermission, pid)
    if p is None or p.creator_id != cid:
        raise NotFoundError("Permesso non trovato")
    p.revoked = True
    db.flush()
    db.refresh(c)
    if crm.valid_permission(c) is None:
        crm.set_status(c, "refused", "Permesso revocato")
    crm.sync_rights(db, c)
    db.commit()
    return creator_out(db, c)


@router.get("/{cid}/permissions/{pid}/evidence")
def evidence(cid: str, pid: str, db: Session = Depends(get_db)) -> FileResponse:
    p = db.get(CreatorPermission, pid)
    if p is None or p.creator_id != cid or not p.evidence_file or not Path(p.evidence_file).exists():
        raise NotFoundError("Prova non disponibile")
    return FileResponse(p.evidence_file)


class CreatorFolderIn(BaseModel):
    path: str = ""   # empty = data/creators/<name>


@router.post("/{cid}/watch-folder", status_code=201)
def creator_folder(cid: str, body: CreatorFolderIn, db: Session = Depends(get_db)) -> dict:
    """A watch folder for this creator's files: imports get rights from the recorded consent."""
    c = _get(db, cid)
    if crm.valid_permission(c) is None:
        raise ValidationFailed("Registra prima un permesso valido del creator")
    if body.path.strip():
        path, _ = windows_to_wsl(body.path)
    else:
        slug = re.sub(r"[^a-z0-9]+", "-", c.name.lower()).strip("-") or c.id[:8]
        path = get_settings().data_dir / "inbox" / slug
    path.mkdir(parents=True, exist_ok=True)
    if db.scalar(select(WatchFolder).where(WatchFolder.path == str(path))):
        raise ValidationFailed("Cartella già monitorata")
    f = WatchFolder(name=f"Creator: {c.name}", path=str(path), extensions=[".mp4", ".mkv", ".mov"], mode="copy",
                    creator_name=c.name, source=f"File forniti da {c.name}", creator_id=c.id, rights={},
                    pipeline={})
    db.add(f)
    db.commit()
    return creator_out(db, c)
