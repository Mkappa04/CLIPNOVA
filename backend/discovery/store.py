"""Encrypted API keys, daily quota accounting and a result cache (all in local SQLite)."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from backend.core.config import get_settings
from backend.core.timeutil import utcnow
from backend.models.automation_entities import ApiKey, ApiQuota, SearchCache
from backend.publishing.crypto import decrypt_json, encrypt_json, mask

PROVIDER_FIELDS = {"youtube_data": ["api_key"], "twitch": ["client_id", "client_secret"]}


class QuotaExceeded(Exception):
    pass


class NotConfigured(Exception):
    pass


def get_keys(db: Session, provider: str) -> dict:
    row = db.get(ApiKey, provider)
    return decrypt_json(row.credentials_encrypted) if row and row.credentials_encrypted else {}


def set_keys(db: Session, provider: str, values: dict) -> dict:
    fields = PROVIDER_FIELDS[provider]
    current = get_keys(db, provider)
    for f in fields:
        v = (values.get(f) or "").strip()
        if v and not v.startswith("••••"):   # masked value sent back unchanged → keep the stored one
            current[f] = v
        elif f in values and values[f] == "":
            current.pop(f, None)
    row = db.get(ApiKey, provider)
    enc = encrypt_json(current) if current else ""
    if row is None:
        db.add(ApiKey(provider=provider, credentials_encrypted=enc))
    else:
        row.credentials_encrypted = enc
    return mask(current)


def configured(db: Session, provider: str) -> bool:
    keys = get_keys(db, provider)
    return all(keys.get(f) for f in PROVIDER_FIELDS[provider])


def quota_day(provider: str, now: datetime | None = None) -> date:
    """YouTube quota resets at midnight Pacific Time."""
    now = (now or datetime.now(ZoneInfo("UTC"))).astimezone(ZoneInfo("America/Los_Angeles"))
    return now.date() if provider == "youtube_data" else (now.date())


def quota_row(db: Session, provider: str) -> ApiQuota:
    day = quota_day(provider)
    row = db.query(ApiQuota).filter_by(provider=provider, day=day).one_or_none()
    if row is None:
        row = ApiQuota(provider=provider, day=day, units=0, calls=0)
        db.add(row)
        db.flush()
    return row


def quota_status(db: Session, provider: str) -> dict:
    s = get_settings()
    row = quota_row(db, provider)
    limit = s.youtube_daily_quota - s.youtube_quota_reserve if provider == "youtube_data" else None
    return {"day": row.day.isoformat(), "units": row.units, "calls": row.calls, "limit": limit,
            "remaining": (limit - row.units) if limit is not None else None}


def spend(db: Session, provider: str, units: int) -> None:
    s = get_settings()
    row = quota_row(db, provider)
    if provider == "youtube_data":
        limit = s.youtube_daily_quota - s.youtube_quota_reserve
        if row.units + units > limit:
            raise QuotaExceeded(f"Quota YouTube giornaliera esaurita ({row.units}/{limit} unità): riprova domani "
                                f"(reset a mezzanotte, ora del Pacifico)")
    row.units += units
    row.calls += 1


def cache_key(provider: str, params: dict) -> str:
    return hashlib.sha256(f"{provider}:{json.dumps(params, sort_keys=True)}".encode()).hexdigest()


def cache_get(db: Session, provider: str, params: dict):
    row = db.get(SearchCache, cache_key(provider, params))
    if row is not None and row.expires_at > utcnow():
        return row.results, row.created_at
    return None, None


def cache_put(db: Session, provider: str, params: dict, results) -> None:
    key = cache_key(provider, params)
    ttl = timedelta(hours=get_settings().discovery_cache_ttl_h)
    row = db.get(SearchCache, key)
    if row is None:
        db.add(SearchCache(key=key, provider=provider, params=params, results=results, created_at=utcnow(),
                           expires_at=utcnow() + ttl))
    else:
        row.results, row.created_at, row.expires_at = results, utcnow(), utcnow() + ttl


def purge_cache(db: Session) -> int:
    return db.query(SearchCache).filter(SearchCache.expires_at <= utcnow()).delete()
