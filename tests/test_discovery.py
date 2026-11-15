from datetime import datetime, timedelta, timezone

import httpx
import pytest

from backend.api.routers import discovery as disc_router
from backend.discovery import twitch

NOW = datetime.now(timezone.utc)


def yt_handler(calls):
    def h(r: httpx.Request):
        calls.append(r.url.path)
        assert r.url.params["key"] == "AIza-test-key"
        if r.url.path.endswith("/search"):
            assert r.url.params["q"] == "GTA 6" and r.url.params["relevanceLanguage"] == "it"
            return httpx.Response(200, json={"items": [{"id": {"videoId": v}} for v in ("a", "b", "c")]})
        items = []
        for vid, views, hours, lic in (("a", 1_000_000, 240, "youtube"), ("b", 50_000, 5, "creativeCommon"),
                                       ("c", 900, 100, "youtube")):
            items.append({"id": vid, "snippet": {"title": f"Video {vid}", "channelTitle": f"Chan {vid}", "channelId": f"UC{vid}",
                                                 "publishedAt": (NOW - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")},
                          "statistics": {"viewCount": str(views), "likeCount": str(views // 20), "commentCount": "10"},
                          "contentDetails": {"duration": "PT45S"}, "status": {"license": lic}})
        return httpx.Response(200, json={"items": items})
    return h


def use(monkeypatch, handler):
    monkeypatch.setattr(disc_router, "client_factory", lambda: httpx.Client(transport=httpx.MockTransport(handler)))


def test_disabled_without_keys(client):
    r = client.post("/api/discovery/search", json={"platform": "twitch"}).json()
    assert r["enabled"] is False and r["results"] == []


def test_youtube_search_rank_quota_cache(client, monkeypatch):
    k = client.put("/api/discovery/keys", json={"provider": "youtube_data", "values": {"api_key": "AIza-test-key"}}).json()
    assert k["configured"] and k["keys"]["api_key"].startswith("••••") and "AIza" not in str(k)
    calls = []
    use(monkeypatch, yt_handler(calls))
    before = client.get("/api/discovery/status").json()["youtube"]["quota"]["units"]
    body = {"platform": "youtube", "query": "GTA 6", "language": "it", "days": 30, "shorts_only": True}
    r = client.post("/api/discovery/search", json=body).json()
    assert r["enabled"] and not r["cached"] and len(r["results"]) == 3
    assert r["quota"]["units"] == before + 101                   # search.list 100 + videos.list 1
    scores = [x["score"] for x in r["results"]]
    assert scores == sorted(scores, reverse=True) and all("/ora" in x["score_reason"] for x in r["results"])
    assert r["results"][-1]["id"] == "c"                         # small and slow ranks last
    cc = [x for x in r["results"] if x["license"] == "creativeCommon"][0]
    assert "CC BY" in cc["attribution_hint"] and cc["is_short"] and cc["url"].endswith("/shorts/b")
    assert {c["name"] for c in r["creators"]} == {"Chan a", "Chan b", "Chan c"}
    n = len(calls)
    again = client.post("/api/discovery/search", json=body).json()
    assert again["cached"] and len(calls) == n                    # served from the local cache, no API call
    client.post("/api/discovery/search", json={**body, "refresh": True})
    assert len(calls) == n + 2


def test_youtube_quota_guard_and_errors(client, monkeypatch):
    from backend.core.config import get_settings
    from backend.database.session import session_scope
    from backend.discovery import store

    with session_scope() as db:
        row = store.quota_row(db, "youtube_data")
        row.units = get_settings().youtube_daily_quota - get_settings().youtube_quota_reserve - 50
    use(monkeypatch, yt_handler([]))
    r = client.post("/api/discovery/search", json={"platform": "youtube", "query": "quota test", "refresh": True})
    assert r.status_code == 422 and r.json()["error"] == "quota_exceeded"
    with session_scope() as db:
        store.quota_row(db, "youtube_data").units = 0
    use(monkeypatch, lambda r: httpx.Response(403, json={"error": {"message": "API key not valid"}}))
    r = client.post("/api/discovery/search", json={"platform": "youtube", "query": "bad key", "refresh": True})
    assert r.status_code == 502 and "API key not valid" in r.json()["message"]


def test_twitch_top_clips(client, monkeypatch):
    twitch._token_cache.clear()
    client.put("/api/discovery/keys", json={"provider": "twitch", "values": {"client_id": "cid", "client_secret": "sec"}})

    def h(r: httpx.Request):
        if r.url.host == "id.twitch.tv":
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
        assert r.headers["client-id"] == "cid" and r.headers["authorization"] == "Bearer tok"
        if r.url.path.endswith("/games"):
            return httpx.Response(200, json={"data": [{"id": "123", "name": r.url.params["name"]}]})
        assert r.url.params["game_id"] == "123"
        return httpx.Response(200, json={"data": [
            {"id": "c1", "title": "Inseguimento", "broadcaster_name": "StreamerIT", "broadcaster_id": "1", "url": "https://clips.twitch.tv/c1",
             "created_at": (NOW - timedelta(hours=10)).strftime("%Y-%m-%dT%H:%M:%SZ"), "duration": 28.5, "view_count": 5000, "language": "it"},
            {"id": "c2", "title": "Heist", "broadcaster_name": "StreamerEN", "broadcaster_id": "2", "url": "https://clips.twitch.tv/c2",
             "created_at": (NOW - timedelta(hours=50)).strftime("%Y-%m-%dT%H:%M:%SZ"), "duration": 30, "view_count": 90000, "language": "en"},
        ]})

    use(monkeypatch, h)
    r = client.post("/api/discovery/search", json={"platform": "twitch", "days": 7, "twitch_kind": "clips"}).json()
    assert [x["id"] for x in r["results"]] == ["c2", "c1"] and r["results"][0]["platform"] == "twitch"
    it = client.post("/api/discovery/search", json={"platform": "twitch", "days": 7, "language": "it", "refresh": True}).json()
    assert [x["creator"] for x in it["results"]] == ["StreamerIT"]
