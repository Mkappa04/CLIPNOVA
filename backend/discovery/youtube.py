"""YouTube Data API v3 search (API key). Costs: search.list = 100 units, videos.list = 1 unit."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

import httpx

API = "https://www.googleapis.com/youtube/v3"
SEARCH_COST, VIDEOS_COST = 100, 1


class YouTubeError(Exception):
    pass


def iso_duration_s(d: str | None) -> int:
    m = re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", d or "")
    if not m:
        return 0
    days, h, mi, s = (int(x or 0) for x in m.groups())
    return days * 86400 + h * 3600 + mi * 60 + s


def search(client: httpx.Client, api_key: str, *, query: str, language: str | None, days: int,
           shorts_only: bool, cc_only: bool, max_results: int, spend) -> list[dict]:
    params = {"part": "snippet", "q": query, "type": "video", "maxResults": min(50, max_results),
              "order": "viewCount", "key": api_key,
              "publishedAfter": (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")}
    if language in ("it", "en"):
        params["relevanceLanguage"] = language
    if shorts_only:
        params["videoDuration"] = "short"     # < 4 minutes
    if cc_only:
        params["videoLicense"] = "creativeCommon"
    spend(SEARCH_COST)
    r = client.get(f"{API}/search", params=params)
    _check(r)
    ids = [it["id"]["videoId"] for it in r.json().get("items", []) if it.get("id", {}).get("videoId")]
    if not ids:
        return []
    spend(VIDEOS_COST)
    r = client.get(f"{API}/videos", params={"part": "snippet,statistics,contentDetails,status",
                                            "id": ",".join(ids), "key": api_key})
    _check(r)
    out = []
    for v in r.json().get("items", []):
        sn, st, cd, status = v.get("snippet", {}), v.get("statistics", {}), v.get("contentDetails", {}), v.get("status", {})
        dur = iso_duration_s(cd.get("duration"))
        out.append({
            "platform": "youtube", "id": v["id"], "title": sn.get("title", ""), "creator": sn.get("channelTitle", ""),
            "channel_id": sn.get("channelId"), "channel_url": f"https://www.youtube.com/channel/{sn.get('channelId')}",
            "url": (f"https://www.youtube.com/shorts/{v['id']}" if dur <= 60 else f"https://www.youtube.com/watch?v={v['id']}"),
            "published_at": sn.get("publishedAt"), "duration_s": dur, "is_short": dur <= 60,
            "views": int(st.get("viewCount", 0)), "likes": int(st["likeCount"]) if "likeCount" in st else None,
            "comments": int(st.get("commentCount", 0)), "license": status.get("license", "youtube"),
            "language": sn.get("defaultAudioLanguage") or sn.get("defaultLanguage") or "",
            "thumbnail": (sn.get("thumbnails", {}).get("medium") or {}).get("url"),
        })
    return out


def _check(r: httpx.Response) -> None:
    if r.status_code == 403 and "quota" in r.text.lower():
        raise YouTubeError("Quota YouTube esaurita lato Google: riprova domani")
    if r.status_code in (400, 403):
        try:
            msg = r.json()["error"]["message"]
        except (ValueError, KeyError):
            msg = r.text[:200]
        raise YouTubeError(f"YouTube API: {msg}")
    if r.status_code >= 400:
        raise YouTubeError(f"YouTube API HTTP {r.status_code}")
