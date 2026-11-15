import io
import zipfile
from datetime import date, timedelta

import httpx
import pytest

from backend.core.config import get_settings
from tests.conftest import wait_job

AUTHORIZED = {"owner": "Creator X", "license_type": "creator_permission", "authorization_status": "authorized",
              "commercial_use_allowed": True, "attribution_required": True, "attribution_text": "Credit: @creatorx",
              "evidence": "email"}


@pytest.fixture(scope="module")
def rendered(client, gameplay_video):
    with gameplay_video.open("rb") as fh:
        r = client.post("/api/videos/upload", files=[("files", ("approval.mp4", fh, "video/mp4"))],
                        data={"game": "GTA 6", "creator": "Creator X"})
    vid = r.json()["videos"][0]["id"]
    assert wait_job(client, r.json()["job_ids"][0])["status"] == "completed"
    assert wait_job(client, client.post(f"/api/videos/{vid}/analyze", json={}).json()["job_id"])["status"] == "completed"
    cid = client.post(f"/api/videos/{vid}/clips", json={"start": 24, "end": 36, "category": "reaction"}).json()["id"]
    # approving before rendering is refused
    client.patch(f"/api/clips/{cid}", json={"status": "review"})
    assert client.post(f"/api/clips/{cid}/approve", json={}).status_code == 422
    job = client.post(f"/api/clips/{cid}/render", json={"config": {"quality": "draft", "layout": "full"}}).json()
    assert wait_job(client, job["job_id"])["status"] == "completed"
    return vid, cid


def test_generate_and_save_content(client, rendered):
    _, cid = rendered
    g = client.post(f"/api/clips/{cid}/content/generate", json={"use_llm": False}).json()
    assert g["content"]["generated_by"] == "template"
    title = g["content"]["title"]
    assert "“" in title, title
    quoted = title.split("“")[1].split("”")[0]

    def norm(t):
        return " ".join("".join(c for c in t.lower() if c.isalnum() or c.isspace()).split())

    clip_text = client.get(f"/api/clips/{cid}").json()["transcript"]
    assert norm(quoted) in norm(clip_text), "the title must quote words actually spoken in the clip"
    saved = client.put(f"/api/clips/{cid}/content", json={**g["content"], "hashtags": ["#GTA6", "gaming"]}).json()
    assert saved["content"]["hashtags"] == ["GTA6", "gaming"] and not saved["approval_revoked"]


def test_approve_then_edit_revokes(client, rendered):
    _, cid = rendered
    q = client.get("/api/approval/queue", params={"status": "review"}).json()
    assert any(i["clip"]["id"] == cid and i["render"] for i in q)
    a = client.post(f"/api/clips/{cid}/approve", json={"note": "ok"}).json()
    assert a["clip"]["status"] == "approved" and a["approved_at"]
    content = a["content"]
    edited = client.put(f"/api/clips/{cid}/content", json={**content, "title": "Nuovo titolo"}).json()
    assert edited["approval_revoked"] and edited["clip"]["status"] == "review"
    assert client.post(f"/api/clips/{cid}/approve", json={}).json()["clip"]["status"] == "approved"


def test_export_blocked_by_rights_then_allowed(client, rendered):
    vid, cid = rendered
    # no rights recorded (upload without rights → unknown license) → blocked with reasons
    r = client.post(f"/api/clips/{cid}/export", json={"platforms": ["tiktok"], "purpose": "non_commercial"})
    assert r.status_code == 403 and r.json()["error"] == "rights_violation"
    assert r.json()["details"]["blockers"]
    client.put(f"/api/videos/{vid}/rights", json={**AUTHORIZED, "license_type": "credit_only"})
    assert client.post(f"/api/clips/{cid}/export", json={"platforms": ["tiktok"]}).status_code == 403
    client.put(f"/api/videos/{vid}/rights", json={**AUTHORIZED, "commercial_use_allowed": False})
    assert client.post(f"/api/clips/{cid}/export", json={"platforms": ["tiktok"], "purpose": "commercial"}).status_code == 403
    client.put(f"/api/videos/{vid}/rights", json=AUTHORIZED)
    check = client.get(f"/api/clips/{cid}/export-check", params={"purpose": "commercial"}).json()
    assert check["allowed"]

    e = client.post(f"/api/clips/{cid}/export", json={"platforms": ["tiktok", "youtube", "instagram"],
                                                      "purpose": "commercial"})
    assert e.status_code == 201, e.text
    exp = e.json()
    assert {"tiktok.txt", "youtube.txt", "instagram.txt", "CHECKLIST.txt", "metadata.json", "package.zip",
            "thumbnail.jpg", "subtitles.srt"} <= set(exp["files"])
    assert any(f.endswith(".mp4") for f in exp["files"])
    tk = client.get(f"/api/exports/{exp['id']}/files/tiktok.txt").text
    assert "Credit: @creatorx" in tk and "#GTA6" in tk          # attribution is always kept
    yt = client.get(f"/api/exports/{exp['id']}/files/youtube.txt").text
    assert "#Shorts" in yt
    z = zipfile.ZipFile(io.BytesIO(client.get(f"/api/exports/{exp['id']}/files/package.zip").content))
    assert "CHECKLIST.txt" in z.namelist() and any(n.endswith(".mp4") for n in z.namelist())
    assert client.get(f"/api/exports/{exp['id']}/files/..%2F..%2Fclipnova.db").status_code == 404
    assert client.get(f"/api/clips/{cid}").json()["status"] == "exported"


def test_publishing_guards_and_flow(client, rendered, monkeypatch):
    from backend.publishing import service

    vid, cid = rendered
    exp = client.get("/api/exports", params={"clip_id": cid}).json()[0]
    acc = client.post("/api/publishing/accounts", json={"platform": "youtube", "display_name": "Canale test",
                                                       "credentials": {"client_id": "c", "client_secret": "s",
                                                                       "refresh_token": "r-secret-token"}}).json()
    assert acc["credentials"]["refresh_token"].startswith("••••") and "r-secret" not in str(acc)
    body = {"export_id": exp["id"], "account_id": acc["id"], "confirm": True}

    # disabled by default
    assert get_settings().publishing_enabled is False
    r = client.post("/api/publishing/publications", json=body)
    assert r.status_code == 422 and r.json()["error"] == "publishing_disabled"

    monkeypatch.setattr(get_settings(), "publishing_enabled", True)
    assert client.post("/api/publishing/publications", json={**body, "confirm": False}).status_code == 422

    calls = {"n": 0}

    def handler(req: httpx.Request):
        if req.url.host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"access_token": "AT"})
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(503)                      # transient error → retry with backoff
        if req.method == "POST":
            return httpx.Response(200, headers={"Location": "https://upload.example/s"})
        return httpx.Response(200, json={"id": "YT1"})

    monkeypatch.setattr(service, "_client_factory", lambda: httpx.Client(transport=httpx.MockTransport(handler)))
    pub = client.post("/api/publishing/publications", json=body).json()
    assert pub["status"] == "scheduled"
    assert service.publish_now(pub["id"]) == "scheduled"   # first attempt failed (503), rescheduled
    p = client.get("/api/publishing/publications").json()[0]
    assert p["attempts"] == 1 and p["next_attempt_at"] and "Retryable" in p["log"][-1]["msg"]
    assert service.publish_now(pub["id"]) == "published"
    p = client.get("/api/publishing/publications").json()[0]
    assert p["remote_id"] == "YT1" and p["remote_url"].endswith("YT1")

    # rights expire after scheduling → blocked at dispatch time
    pub2 = client.post("/api/publishing/publications", json=body).json()
    client.put(f"/api/videos/{vid}/rights", json={**AUTHORIZED, "expires_at": str(date.today() - timedelta(days=1))})
    assert service.publish_now(pub2["id"]) == "failed"
    p2 = [x for x in client.get("/api/publishing/publications").json() if x["id"] == pub2["id"]][0]
    assert "Verifica diritti non superata" in p2["last_error"]

    # the scheduler only dispatches when enabled
    monkeypatch.setattr(get_settings(), "publishing_enabled", False)
    assert service.scheduler.tick() == 0


def test_reject_archive_reopen_and_delete_export(client, rendered):
    vid, cid = rendered
    client.put(f"/api/videos/{vid}/rights", json=AUTHORIZED)
    assert client.post(f"/api/clips/{cid}/reject", json={"note": "audio basso"}).json()["clip"]["status"] == "rejected"
    assert client.post(f"/api/clips/{cid}/reopen").json()["clip"]["status"] == "review"
    assert client.post(f"/api/clips/{cid}/archive").json()["clip"]["status"] == "archived"
    exp = client.get("/api/exports", params={"clip_id": cid}).json()[0]
    assert client.delete(f"/api/exports/{exp['id']}").status_code == 422
    assert client.delete(f"/api/exports/{exp['id']}", params={"confirm": True}).status_code == 200
    counts = client.get("/api/approval/counts").json()
    assert counts["archived"] >= 1
