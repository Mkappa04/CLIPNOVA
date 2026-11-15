from __future__ import annotations

from datetime import timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.core.config import get_settings
from backend.core.exceptions import ConflictError, NotFoundError, ValidationFailed
from backend.core.timeutil import utcnow
from backend.database.session import get_db
from backend.models.entities import Export, Publication, PublicationStatus, SocialAccount
from backend.models.schemas import AccountIn, AccountOut, PublicationIn, PublicationOut
from backend.publishing.crypto import decrypt_json, encrypt_json, mask
from backend.publishing.registry import PUBLISHERS, get_publisher
from backend.publishing.service import preflight
from backend.services.approval import APPROVED_STATES

router = APIRouter(prefix="/api/publishing", tags=["publishing"])


@router.get("/status")
def status() -> dict:
    s = get_settings()
    return {
        "enabled": s.publishing_enabled,
        "explanation": ("La pubblicazione automatica è disabilitata. Usa l'export manuale assistito, oppure "
                        "imposta CLIPNOVA_PUBLISHING_ENABLED=true dopo aver configurato le API ufficiali.")
        if not s.publishing_enabled else "Pubblicazione via API ufficiali abilitata: richiede sempre conferma.",
        "export_copy_dir": str(s.export_copy_dir) if s.export_copy_dir else None,
        "providers": [{"platform": p.platform, "name": p.name, "docs_url": p.docs_url,
                       "credential_fields": p.credential_fields, "notes": p.notes} for p in PUBLISHERS.values()],
    }


def account_out(a: SocialAccount) -> AccountOut:
    out = AccountOut.model_validate(a)
    try:
        out.credentials = mask(decrypt_json(a.credentials_encrypted))
    except ValueError:
        out.credentials = {}
        out.status = "undecryptable"
    return out


@router.get("/accounts", response_model=list[AccountOut])
def accounts(db: Session = Depends(get_db)):
    return [account_out(a) for a in db.scalars(select(SocialAccount).order_by(SocialAccount.created_at)).all()]


@router.post("/accounts", response_model=AccountOut, status_code=201)
def add_account(body: AccountIn, db: Session = Depends(get_db)):
    pub = get_publisher(body.platform)
    creds = {k: v.strip() for k, v in body.credentials.items() if k in pub.credential_fields and v.strip()}
    missing = pub.missing_credentials(creds)
    if missing:
        raise ValidationFailed(f"Missing credentials for {pub.name}: {', '.join(missing)}")
    acc = SocialAccount(platform=body.platform, display_name=body.display_name or pub.name,
                        credentials_encrypted=encrypt_json(creds), status="connected")
    db.add(acc)
    db.commit()
    return account_out(acc)


@router.delete("/accounts/{account_id}")
def delete_account(account_id: str, confirm: bool = False, db: Session = Depends(get_db)) -> dict:
    if not confirm:
        raise ValidationFailed("Deletion requires explicit confirmation (confirm=true)", code="confirmation_required")
    acc = db.get(SocialAccount, account_id)
    if acc is None:
        raise NotFoundError("Account not found")
    active = db.scalar(select(Publication.id).where(Publication.account_id == account_id, Publication.status.in_(
        [PublicationStatus.SCHEDULED.value, PublicationStatus.PUBLISHING.value])))
    if active:
        raise ConflictError("Account has scheduled publications: cancel them first")
    db.delete(acc)
    db.commit()
    return {"deleted": account_id}


def publication_out(p: Publication) -> PublicationOut:
    out = PublicationOut.model_validate(p)
    out.clip_title = (p.export.content_snapshot or {}).get("content", {}).get("title", "") if p.export else ""
    return out


@router.get("/publications", response_model=list[PublicationOut])
def publications(status: str | None = None, limit: int = Query(100, ge=1, le=500), db: Session = Depends(get_db)):
    stmt = select(Publication).order_by(Publication.created_at.desc()).limit(limit)
    if status:
        stmt = stmt.where(Publication.status.in_(status.split(",")))
    return [publication_out(p) for p in db.scalars(stmt).all()]


@router.post("/publications", response_model=PublicationOut, status_code=201)
def schedule(body: PublicationIn, db: Session = Depends(get_db)):
    if not get_settings().publishing_enabled:
        raise ValidationFailed("Publishing is disabled: set CLIPNOVA_PUBLISHING_ENABLED=true, or use the manual export",
                               code="publishing_disabled")
    if not body.confirm:
        raise ValidationFailed("Explicit confirmation required (confirm=true)", code="confirmation_required")
    exp = db.get(Export, body.export_id)
    acc = db.get(SocialAccount, body.account_id)
    if exp is None or acc is None:
        raise NotFoundError("Export or account not found")
    if acc.platform not in exp.platforms:
        raise ValidationFailed(f"This export was not prepared for {acc.platform}")
    if exp.clip.status not in APPROVED_STATES:
        raise ValidationFailed("The clip is not approved")
    when = body.scheduled_at or utcnow()
    if when.tzinfo is not None:
        when = when.astimezone(timezone.utc).replace(tzinfo=None)
    pub = Publication(clip_id=exp.clip_id, export_id=exp.id, account_id=acc.id, platform=acc.platform,
                      privacy=body.privacy, scheduled_at=when, approved_confirmation=True,
                      log=[{"at": utcnow().isoformat() + "Z", "msg": "Scheduled with explicit confirmation"}])
    db.add(pub)
    db.flush()
    reason = preflight(pub)
    if reason:
        db.rollback()
        raise ValidationFailed(f"Cannot schedule: {reason}")
    db.commit()
    return publication_out(pub)


@router.post("/publications/{pub_id}/cancel", response_model=PublicationOut)
def cancel(pub_id: str, db: Session = Depends(get_db)):
    p = db.get(Publication, pub_id)
    if p is None:
        raise NotFoundError("Publication not found")
    if p.status != PublicationStatus.SCHEDULED.value:
        raise ConflictError(f"Cannot cancel a publication that is {p.status}")
    p.status = PublicationStatus.CANCELLED.value
    db.commit()
    return publication_out(p)


@router.post("/publications/{pub_id}/retry", response_model=PublicationOut)
def retry(pub_id: str, db: Session = Depends(get_db)):
    p = db.get(Publication, pub_id)
    if p is None:
        raise NotFoundError("Publication not found")
    if p.status != PublicationStatus.FAILED.value:
        raise ConflictError("Only failed publications can be retried")
    p.status, p.attempts, p.next_attempt_at, p.scheduled_at = PublicationStatus.SCHEDULED.value, 0, None, utcnow()
    db.commit()
    return publication_out(p)
