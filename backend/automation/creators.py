"""Lightweight creator CRM: negotiation status, permission requests, recorded consent, expiry.

Messages are only *generated*: sending stays manual (copy/paste). No DMs are ever sent.
"""

from __future__ import annotations

import re
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.automation.common import notify
from backend.core.exceptions import ValidationFailed
from backend.core.timeutil import utcnow
from backend.models.automation_entities import Creator, CreatorPermission, WatchFolder
from backend.models.entities import RightsRecord, Video

STATUSES = ("to_contact", "contacted", "waiting", "authorized", "refused", "expired")
STATUS_LABELS = {"to_contact": "da contattare", "contacted": "contattato", "waiting": "in attesa",
                 "authorized": "autorizzato", "refused": "rifiutato", "expired": "scaduto"}
EXPIRY_WARNING_DAYS = 7


def set_status(creator: Creator, status: str, note: str = "") -> None:
    if status not in STATUSES:
        raise ValidationFailed(f"Unknown status {status}")
    if status == creator.status and not note:
        return
    creator.status_history = [*(creator.status_history or []),
                              {"at": utcnow().isoformat() + "Z", "from": creator.status, "to": status, "note": note}]
    creator.status = status


def valid_permission(creator: Creator, today: date | None = None) -> CreatorPermission | None:
    today = today or utcnow().date()
    for p in creator.permissions:
        if not p.revoked and (p.expires_at is None or p.expires_at >= today):
            return p
    return None


def add_permission(db: Session, creator: Creator, **fields) -> CreatorPermission:
    p = CreatorPermission(creator_id=creator.id, **fields)
    if p.expires_at is not None and p.expires_at < p.granted_at:
        raise ValidationFailed("La scadenza è precedente alla data del consenso")
    db.add(p)
    db.flush()
    db.refresh(creator)
    set_status(creator, "authorized", f"Consenso registrato: {p.scope[:80]}")
    sync_rights(db, creator)
    return p


def sync_rights(db: Session, creator: Creator, today: date | None = None) -> int:
    """Propagate the current consent to videos imported from the creator's watch folders."""
    perm = valid_permission(creator, today)
    folder_ids = [f.id for f in db.scalars(select(WatchFolder).where(WatchFolder.creator_id == creator.id))]
    if not folder_ids:
        return 0
    from backend.models.automation_entities import WatchedFile

    video_ids = [v for v in db.scalars(select(WatchedFile.video_id).where(WatchedFile.folder_id.in_(folder_ids))) if v]
    n = 0
    for vid in video_ids:
        video = db.get(Video, vid)
        if video is None:
            continue
        r = video.rights or RightsRecord(video_id=video.id)
        if video.rights is None:
            video.rights = r
        r.owner = creator.name
        r.license_type = "creator_permission"
        if perm is None:
            r.authorization_status = "pending"
        else:
            r.authorization_status = "authorized"
            r.commercial_use_allowed = perm.commercial_use
            r.attribution_required = True
            r.attribution_text = perm.attribution_text
            r.expires_at = perm.expires_at
            r.restrictions = perm.restrictions
            r.evidence = f"Permesso registrato il {perm.granted_at.isoformat()} (id {perm.id[:8]}): {perm.scope}"
        n += 1
    return n


def check_permission_expiry(db: Session, today: date) -> dict:
    """Warn N days before a consent expires; mark creators whose last consent expired."""
    warned = expired = 0
    perms = db.scalars(select(CreatorPermission).where(CreatorPermission.revoked.is_(False),
                                                       CreatorPermission.expires_at.is_not(None))).all()
    for p in perms:
        days = (p.expires_at - today).days
        if 0 <= days <= EXPIRY_WARNING_DAYS and not p.expiry_notified:
            notify(db, f"Il permesso di {p.creator.name} scade tra {days} giorni",
                   f"Scadenza {p.expires_at.isoformat()}: rinnovalo o l'export di quel materiale verrà bloccato.",
                   "/creators", kind="warning")
            p.expiry_notified = True
            warned += 1
    for c in db.scalars(select(Creator).where(Creator.status == "authorized")).all():
        if valid_permission(c, today) is None:
            set_status(c, "expired", "Permesso scaduto")
            sync_rights(db, c, today)
            notify(db, f"Permesso di {c.name} scaduto", "Export bloccato per il materiale di questo creator.",
                   "/creators", kind="warning")
            expired += 1
    return {"warned": warned, "expired": expired}


# ---------------------------------------------------------------- permission request message
TEMPLATES = {
    "it": """Ciao {creator},

sono {sender}{channel_part}. Seguo i tuoi contenuti su {game} e vorrei chiederti il permesso di usare {what}.

Come li userei:
- clip brevi in formato verticale (TikTok, Instagram Reels, YouTube Shorts){platforms_part}
- con sottotitoli e montaggio, senza alterare il senso di ciò che dici o fai
- {commercial}

Attribuzione: in ogni video indicherei {attribution}.
Puoi revocare il permesso quando vuoi: in quel caso smetterò di pubblicare nuove clip con il tuo materiale{removal}.
{extra}
Se ti va bene, mi basta una risposta scritta con eventuali condizioni (piattaforme, durata, uso commerciale sì/no).

Grazie!
{sender}""",
    "en": """Hi {creator},

I'm {sender}{channel_part}. I follow your {game} content and I'd like to ask your permission to use {what}.

How I would use it:
- short vertical clips (TikTok, Instagram Reels, YouTube Shorts){platforms_part}
- with subtitles and editing, without changing the meaning of what you say or do
- {commercial}

Credit: every video would mention {attribution}.
You can revoke this permission at any time: I would then stop publishing new clips with your material{removal}.
{extra}
If that works for you, a written reply with any conditions (platforms, duration, commercial use yes/no) is all I need.

Thanks!
{sender}""",
}


def permission_message(*, language: str, creator: str, sender: str, channel: str, game: str, what: str,
                       platforms: list[str], commercial: bool, attribution: str, remove_on_revoke: bool,
                       extra: str = "") -> str:
    it = language != "en"
    t = TEMPLATES["it" if it else "en"]
    names = {"tiktok": "TikTok", "instagram": "Instagram", "youtube": "YouTube"}
    plat = ", ".join(names.get(p, p) for p in platforms)
    return t.format(
        creator=creator, sender=sender or ("[il tuo nome]" if it else "[your name]"),
        channel_part=(f" ({channel})" if channel else ""), game=game,
        what=what or ("alcuni momenti dei tuoi video/live" if it else "a few moments from your videos/streams"),
        platforms_part=(f": {plat}" if plat else ""),
        commercial=("su un canale che potrebbe essere monetizzato (uso commerciale)" if commercial else
                    "senza monetizzazione (uso non commerciale)") if it else
                   ("on a channel that may be monetised (commercial use)" if commercial else
                    "without monetisation (non-commercial use)"),
        attribution=attribution or (f"il tuo nome e il link al tuo canale" if it else "your name and a link to your channel"),
        removal=((" e rimuoverò quelle già pubblicate" if it else " and remove the ones already published")
                 if remove_on_revoke else ""),
        extra=(f"\n{extra.strip()}\n" if extra.strip() else ""),
    ).strip() + "\n"


def message_facts_ok(text: str, allowed: str) -> list[str]:
    """Numbers/handles/URLs in an LLM-rewritten message that are not in the inputs."""
    found = re.findall(r"(https?://\S+|@\w+|\b\d+[\d.,]*\b)", text)
    return [f for f in found if f not in allowed]
