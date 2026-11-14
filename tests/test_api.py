import json
import time

from backend.workers.queue import JobContext, job_manager
from tests.conftest import make_video, wait_job

AUTH_RIGHTS = {
    "owner": "Creator X", "license_type": "creator_permission", "authorization_status": "authorized",
    "commercial_use_allowed": False, "attribution_required": True, "attribution_text": "Credit: Creator X",
    "evidence": "DM permission",
}


def test_health_and_system(client):
    assert client.get("/api/health").json()["status"] == "ok"
    info = client.get("/api/system").json()
    assert "gpu" in info and "ffmpeg" in info and info["memory"]["total"] > 0


def test_upload_probe_and_library(client, sample_video):
    with sample_video.open("rb") as fh:
        r = client.post("/api/videos/upload",
                        files=[("files", (sample_video.name, fh, "video/mp4"))],
                        data={"game": "GTA 6", "creator": "Creator X", "source": "Own recording",
                              "rights": json.dumps(AUTH_RIGHTS)})
    assert r.status_code == 201, r.text
    body = r.json()
    vid = body["videos"][0]["id"]
    assert body["videos"][0]["storage_mode"] == "uploaded"
    job = wait_job(client, body["job_ids"][0])
    assert job["status"] == "completed", job

    v = client.get(f"/api/videos/{vid}").json()
    assert v["status"] == "ready"
    assert (v["width"], v["height"], v["fps"]) == (1280, 720, 30)
    assert v["has_thumbnail"] and v["rights"]["owner"] == "Creator X"
    assert client.get(f"/api/videos/{vid}/thumbnail").headers["content-type"] == "image/jpeg"

    rng = client.get(f"/api/videos/{vid}/stream", headers={"Range": "bytes=0-99"})
    assert rng.status_code == 206 and len(rng.content) == 100

    assert any(x["id"] == vid for x in client.get("/api/videos", params={"q": "sample"}).json())
    assert client.get("/api/videos", params={"game": "Minecraft"}).json() == []

    # Rights checks via API
    assert client.get(f"/api/videos/{vid}/rights/check", params={"purpose": "non_commercial"}).json()["allowed"]
    commercial = client.get(f"/api/videos/{vid}/rights/check", params={"purpose": "commercial"}).json()
    assert not commercial["allowed"]

    upd = client.put(f"/api/videos/{vid}/rights", json={**AUTH_RIGHTS, "license_type": "credit_only"})
    assert upd.status_code == 200
    assert not client.get(f"/api/videos/{vid}/rights/check", params={"purpose": "non_commercial"}).json()["allowed"]

    patched = client.patch(f"/api/videos/{vid}", json={"title": "Heist gone wrong", "game": "GTA 6"}).json()
    assert patched["title"] == "Heist gone wrong"

    dash = client.get("/api/dashboard").json()
    assert dash["videos"]["total"] >= 1 and dash["storage"]["data_bytes"] > 0


def test_upload_rejects_bad_extension(client, media_dir):
    p = media_dir / "notes.txt"
    p.write_text("hello")
    with p.open("rb") as fh:
        r = client.post("/api/videos/upload", files=[("files", (p.name, fh, "text/plain"))])
    assert r.status_code == 422 and "Unsupported" in r.json()["message"]


def test_import_path_reference_and_delete_keeps_file(client, media_dir):
    src = make_video(media_dir / "referenced.mkv", seconds=2)
    r = client.post("/api/videos/import-path", json={"path": str(src), "mode": "reference", "game": "Fortnite"})
    assert r.status_code == 201, r.text
    vid = r.json()["videos"][0]["id"]
    assert wait_job(client, r.json()["job_ids"][0])["status"] == "completed"
    assert client.get(f"/api/videos/{vid}").json()["storage_mode"] == "referenced"
    assert "Fortnite" in client.get("/api/videos/games").json()

    assert client.delete(f"/api/videos/{vid}").status_code == 422  # confirmation required
    d = client.delete(f"/api/videos/{vid}", params={"confirm": True, "delete_file": True}).json()
    assert d["removed_files"] == [] and src.exists()  # referenced originals are never deleted
    assert client.get(f"/api/videos/{vid}").status_code == 404


def test_import_path_copy_then_delete_managed_file(client, media_dir):
    src = make_video(media_dir / "tocopy.mov", seconds=2)
    r = client.post("/api/videos/import-path", json={"path": str(src), "mode": "copy"})
    vid = r.json()["videos"][0]["id"]
    job = wait_job(client, r.json()["job_ids"][0])
    assert job["status"] == "completed", job
    v = client.get(f"/api/videos/{vid}").json()
    assert v["storage_mode"] == "copied" and v["file_path"] != str(src)
    d = client.delete(f"/api/videos/{vid}", params={"confirm": True, "delete_file": True}).json()
    assert d["removed_files"] == [v["file_path"]] and src.exists()


def test_import_path_errors(client):
    assert client.post("/api/videos/import-path", json={"path": "/nope/x.mp4"}).status_code == 422
    assert client.post("/api/videos/import-path", json={"path": "relative.mp4"}).status_code == 422


def test_job_cancellation(client):
    @job_manager.register("test.sleep")
    def _sleep(ctx: JobContext):
        for i in range(200):
            ctx.check_cancelled()
            ctx.progress(i / 200, f"step {i}")
            time.sleep(0.05)
        return {"done": True}

    jid = job_manager.submit("test.sleep")
    deadline = time.time() + 5
    while client.get(f"/api/jobs/{jid}").json()["status"] != "running" and time.time() < deadline:
        time.sleep(0.05)
    assert client.post(f"/api/jobs/{jid}/cancel").status_code == 200
    assert wait_job(client, jid)["status"] == "cancelled"
    assert client.post(f"/api/jobs/{jid}/cancel").status_code == 409


def test_unknown_api_route_404(client):
    assert client.get("/api/does-not-exist").status_code == 404
