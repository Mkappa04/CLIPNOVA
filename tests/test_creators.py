import io
import shutil
from datetime import date, timedelta

from tests.conftest import make_video, wait_job


def test_crm_flow_message_and_consent(client):
    body = {"name": "Streamer Test", "language": "it", "source": "discovery",
            "channels": [{"platform": "youtube", "channel_id": "UCxyz", "url": "https://youtube.com/channel/UCxyz"}]}
    c = client.post("/api/creators", json=body).json()
    assert c["status"] == "to_contact"
    assert client.post("/api/creators", json=body).json()["id"] == c["id"]      # same channel → no duplicate
    c = client.patch(f"/api/creators/{c['id']}", json={"status": "contacted", "note": "DM su Instagram"}).json()
    assert c["status"] == "contacted" and c["status_history"][-1]["note"] == "DM su Instagram"

    m = client.post(f"/api/creators/{c['id']}/message", json={"language": "it", "sender": "Flavio", "commercial": True,
                                                              "attribution": "@streamertest", "platforms": ["tiktok"]}).json()
    t = m["text"]
    assert "Streamer Test" in t and "TikTok" in t and "uso commerciale" in t and "@streamertest" in t
    assert "revocare" in t and m["generated_by"] == "template" and "non invia" in m["note"]

    # consent requires proof
    r = client.post(f"/api/creators/{c['id']}/permissions", data={"granted_at": str(date.today()), "attribution_text": "Clip di @st"})
    assert r.status_code == 422
    r = client.post(f"/api/creators/{c['id']}/permissions",
                    data={"granted_at": str(date.today()), "expires_at": str(date.today() + timedelta(days=90)),
                          "scope": "clip GTA 6 dai VOD", "commercial_use": "true", "attribution_text": "Clip di @st",
                          "restrictions": "niente YouTube"},
                    files={"evidence": ("dm.png", io.BytesIO(b"\x89PNG fake"), "image/png")})
    assert r.status_code == 201, r.text
    c = r.json()
    assert c["status"] == "authorized" and c["permissions"][0]["valid"] and c["permissions"][0]["has_evidence_file"]
    pid = c["permissions"][0]["id"]
    assert client.get(f"/api/creators/{c['id']}/permissions/{pid}/evidence").content == b"\x89PNG fake"


def test_creator_folder_import_prefills_rights_and_expiry_blocks(client, tmp_path):
    from backend.automation.creators import check_permission_expiry
    from backend.automation.watcher import watcher
    from backend.core.timeutil import utcnow
    from backend.database.session import session_scope

    c = client.post("/api/creators", json={"name": "Creator Folder"}).json()
    assert client.post(f"/api/creators/{c['id']}/watch-folder", json={}).status_code == 422   # no consent yet
    expires = date.today() + timedelta(days=5)
    client.post(f"/api/creators/{c['id']}/permissions",
                data={"granted_at": str(date.today()), "expires_at": str(expires), "scope": "VOD GTA 6",
                      "commercial_use": "false", "attribution_text": "Credit: @creatorfolder", "evidence_text": "Sì, va bene!"})
    inbox = tmp_path / "inbox"
    c = client.post(f"/api/creators/{c['id']}/watch-folder", json={"path": str(inbox)}).json()
    folder_id = c["watch_folders"][0]["id"]
    client.put(f"/api/watch-folders/{folder_id}", json={
        "path": str(inbox), "mode": "copy", "creator_id": c["id"], "creator_name": "Creator Folder",
        "pipeline": {"analyze": False, "render_top_n": 0}})
    make_video(inbox / "vod.mp4", seconds=8, tag="test_creators-8")
    base = utcnow()
    watcher.tick(now=base)
    watcher.tick(now=base + timedelta(seconds=30))
    f = client.get("/api/watch-folders/files", params={"folder_id": folder_id}).json()[0]
    assert wait_job(client, f["job_id"])["status"] == "completed"
    rights = client.get(f"/api/videos/{f['video_id']}").json()["rights"]
    assert rights["owner"] == "Creator Folder" and rights["authorization_status"] == "authorized"
    assert rights["attribution_text"] == "Credit: @creatorfolder" and rights["expires_at"] == str(expires)
    assert not rights["commercial_use_allowed"] and "VOD GTA 6" in rights["evidence"]
    check = client.get(f"/api/videos/{f['video_id']}/rights/check", params={"purpose": "non_commercial"}).json()
    assert check["allowed"] and any("expires soon" in w for w in check["warnings"])

    client.post("/api/notifications/read")
    with session_scope() as db:   # 5 days before expiry: warning (the watcher's hourly check may have sent it already)
        check_permission_expiry(db, date.today())
    with session_scope() as db:   # after expiry: creator expired + export blocked
        check_permission_expiry(db, expires + timedelta(days=1))
    c2 = [x for x in client.get("/api/creators").json() if x["id"] == c["id"]][0]
    assert c2["status"] == "expired"
    titles = [n["title"] for n in client.get("/api/notifications").json()["items"]]
    assert any("scade tra" in t for t in titles) and any("scaduto" in t for t in titles)
    rights = client.get(f"/api/videos/{f['video_id']}").json()["rights"]
    assert rights["authorization_status"] == "pending"
    assert not client.get(f"/api/videos/{f['video_id']}/rights/check", params={"purpose": "non_commercial"}).json()["allowed"]
