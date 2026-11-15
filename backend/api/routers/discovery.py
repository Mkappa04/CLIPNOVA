from __future__ import annotations

from collections.abc import Callable

import httpx
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.core.config import get_settings
from backend.core.exceptions import ClipnovaError, ValidationFailed
from backend.database.session import get_db
from backend.discovery import ranking, store, twitch, youtube

router = APIRouter(prefix="/api/discovery", tags=["discovery"])
client_factory: Callable[[], httpx.Client] = lambda: httpx.Client(timeout=20)  # noqa: E731 (tests override)


class DiscoveryError(ClipnovaError):
    status_code = 502
    code = "discovery_error"


@router.get("/status")
def status(db: Session = Depends(get_db)) -> dict:
    return {
        "youtube": {"configured": store.configured(db, "youtube_data"), "quota": store.quota_status(db, "youtube_data")},
        "twitch": {"configured": store.configured(db, "twitch"), "game": get_settings().twitch_game_name},
        "cache_ttl_h": get_settings().discovery_cache_ttl_h,
        "policy": ("Solo ricerca tramite API ufficiali: CLIPNOVA non scarica mai video di terzi, nemmeno con licenza "
                   "Creative Commons. Il file va ottenuto in modo legittimo, per esempio direttamente dal creator."),
    }


@router.get("/keys")
def get_keys(db: Session = Depends(get_db)) -> dict:
    from backend.publishing.crypto import mask

    return {p: mask(store.get_keys(db, p)) for p in store.PROVIDER_FIELDS}


class KeysIn(BaseModel):
    provider: str = Field(pattern="^(youtube_data|twitch)$")
    values: dict[str, str]


@router.put("/keys")
def put_keys(body: KeysIn, db: Session = Depends(get_db)) -> dict:
    masked = store.set_keys(db, body.provider, body.values)
    db.commit()
    return {"provider": body.provider, "keys": masked, "configured": store.configured(db, body.provider)}


class SearchIn(BaseModel):
    platform: str = Field("youtube", pattern="^(youtube|twitch)$")
    query: str = Field("GTA 6", max_length=200)
    language: str | None = Field(None, pattern="^(it|en)$")
    days: int = Field(7, ge=1, le=365)
    shorts_only: bool = False
    cc_only: bool = False
    twitch_kind: str = Field("clips", pattern="^(clips|vods)$")
    max_results: int = Field(25, ge=5, le=50)
    refresh: bool = False


@router.post("/search")
def search(body: SearchIn, db: Session = Depends(get_db)) -> dict:
    provider = "youtube_data" if body.platform == "youtube" else "twitch"
    if not store.configured(db, provider):
        return {"enabled": False, "results": [], "creators": [],
                "message": "API non configurata: inserisci le chiavi gratuite in Settings → Scoperta contenuti"}
    params = body.model_dump(exclude={"refresh"})
    if not body.refresh:
        cached, at = store.cache_get(db, provider, params)
        if cached is not None:
            return {"enabled": True, "cached": True, "cached_at": at.isoformat() + "Z", **cached,
                    "quota": store.quota_status(db, provider) if provider == "youtube_data" else None}
    keys = store.get_keys(db, provider)
    try:
        with client_factory() as client:
            if provider == "youtube_data":
                items = youtube.search(client, keys["api_key"], query=body.query, language=body.language, days=body.days,
                                       shorts_only=body.shorts_only, cc_only=body.cc_only,
                                       max_results=body.max_results, spend=lambda u: store.spend(db, provider, u))
            else:
                items = twitch.top_content(client, keys["client_id"], keys["client_secret"],
                                           game_name=get_settings().twitch_game_name, days=body.days,
                                           language=body.language, kind=body.twitch_kind, limit=body.max_results)
    except store.QuotaExceeded as e:
        db.commit()
        raise ValidationFailed(str(e), code="quota_exceeded") from e
    except (youtube.YouTubeError, twitch.TwitchError) as e:
        db.commit()  # keep the quota accounting of the attempt
        raise DiscoveryError(str(e)) from e
    except httpx.HTTPError as e:
        db.commit()
        raise DiscoveryError(f"Rete: {e}") from e
    for it in items:
        if it.get("license") == "creativeCommon":
            it["attribution_hint"] = (f"“{it['title']}” di {it['creator']} ({it['url']}), licenza CC BY: "
                                      "ottieni il file in modo legittimo (es. dal creator) e cita sempre l'autore.")
    payload = {"results": ranking.rank_items(items), "creators": ranking.rank_creators(items)}
    store.cache_put(db, provider, params, payload)
    store.purge_cache(db)
    db.commit()
    return {"enabled": True, "cached": False, **payload,
            "quota": store.quota_status(db, provider) if provider == "youtube_data" else None}
