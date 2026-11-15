"""Twitch Helix (app access token via client credentials): top clips and VODs of a game."""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import httpx

TOKEN_URL = "https://id.twitch.tv/oauth2/token"
API = "https://api.twitch.tv/helix"
_token_cache: dict[str, tuple[str, float]] = {}


class TwitchError(Exception):
    pass


def _token(client: httpx.Client, cid: str, secret: str) -> str:
    tok = _token_cache.get(cid)
    if tok and tok[1] > time.time() + 60:
        return tok[0]
    r = client.post(TOKEN_URL, data={"client_id": cid, "client_secret": secret, "grant_type": "client_credentials"})
    if r.status_code >= 400:
        raise TwitchError(f"Twitch: credenziali non valide ({r.status_code})")
    d = r.json()
    _token_cache[cid] = (d["access_token"], time.time() + int(d.get("expires_in", 3600)))
    return d["access_token"]


def _get(client, cid, token, path, params) -> dict:
    r = client.get(f"{API}/{path}", params=params, headers={"Client-Id": cid, "Authorization": f"Bearer {token}"})
    if r.status_code == 429:
        raise TwitchError("Twitch: limite di richieste raggiunto, riprova tra poco")
    if r.status_code >= 400:
        raise TwitchError(f"Twitch API {path}: HTTP {r.status_code}")
    return r.json()


def top_content(client: httpx.Client, cid: str, secret: str, *, game_name: str, days: int, language: str | None,
                kind: str, limit: int) -> list[dict]:
    token = _token(client, cid, secret)
    games = _get(client, cid, token, "games", {"name": game_name}).get("data", [])
    if not games:
        raise TwitchError(f"Gioco «{game_name}» non trovato su Twitch")
    game_id = games[0]["id"]
    out = []
    if kind == "clips":
        now = datetime.now(timezone.utc)
        data = _get(client, cid, token, "clips", {"game_id": game_id, "first": min(100, limit),
                                                  "started_at": (now - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                                                  "ended_at": now.strftime("%Y-%m-%dT%H:%M:%SZ")}).get("data", [])
        for c in data:
            if language and c.get("language", "")[:2] != language:
                continue
            out.append({"platform": "twitch", "kind": "clip", "id": c["id"], "title": c.get("title", ""),
                        "creator": c.get("broadcaster_name", ""), "channel_id": c.get("broadcaster_id"),
                        "channel_url": f"https://www.twitch.tv/{c.get('broadcaster_name', '').lower()}",
                        "url": c.get("url"), "published_at": c.get("created_at"), "duration_s": round(c.get("duration", 0)),
                        "views": c.get("view_count", 0), "likes": None, "comments": None, "license": "twitch",
                        "language": c.get("language", ""), "thumbnail": c.get("thumbnail_url")})
    else:
        period = "day" if days <= 1 else "week" if days <= 7 else "month"
        data = _get(client, cid, token, "videos", {"game_id": game_id, "first": min(100, limit), "sort": "views",
                                                   "period": period, "type": "archive",
                                                   **({"language": language} if language else {})}).get("data", [])
        for v in data:
            out.append({"platform": "twitch", "kind": "vod", "id": v["id"], "title": v.get("title", ""),
                        "creator": v.get("user_name", ""), "channel_id": v.get("user_id"),
                        "channel_url": f"https://www.twitch.tv/{v.get('user_login', '')}", "url": v.get("url"),
                        "published_at": v.get("created_at"), "duration_s": 0, "views": v.get("view_count", 0),
                        "likes": None, "comments": None, "license": "twitch", "language": v.get("language", ""),
                        "thumbnail": (v.get("thumbnail_url") or "").replace("%{width}", "320").replace("%{height}", "180")})
    return out[:limit]
