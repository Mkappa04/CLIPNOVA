import shutil
from datetime import timedelta

import pytest

from backend.automation import common
from backend.automation.watcher import watcher
from backend.core.timeutil import utcnow
from tests.conftest import wait_job

PIPELINE = {"analyze": True, "render_top_n": 1, "min_score": 0, "detect_webcam": True,
            "edit_config": {"quality": "draft", "subtitle_preset": "viral"}}


def settings(client, **kw):
    body = {"paused": False, "window": {"enabled": False, "start": "22:00", "end": "07:00"}, "idle_only": False, **kw}
    assert client.put("/api/automation/settings", json=body).status_code == 200


def test_end_to_end_pipeline_to_review(client, tmp_path, gameplay_video):
    folder = tmp_path / "auto"
    folder.mkdir()
    fid = client.post("/api/watch-folders", json={"path": str(folder), "pipeline": PIPELINE, "mode": "copy",
                                                  "game": "GTA 6", "creator_name": "Me"}).json()["id"]
    client.post("/api/notifications/read")
    from tests.conftest import unique_copy

    unique_copy(gameplay_video, folder / "gta session.mp4", "auto-pipeline")
    base = utcnow()
    watcher.tick(now=base)
    watcher.tick(now=base + timedelta(seconds=30))
    f = client.get("/api/watch-folders/files", params={"folder_id": fid}).json()[0]
    assert f["status"] == "processing" and f["job_id"]
    job = wait_job(client, f["job_id"], timeout=300)
    assert job["status"] == "completed", job
    f = client.get("/api/watch-folders/files", params={"folder_id": fid}).json()[0]
    assert f["status"] == "done" and f["stage"] == "review"

    video = client.get(f"/api/videos/{f['video_id']}").json()
    assert video["status"] == "analyzed" and video["storage_mode"] == "copied"
    assert video["rights"]["license_type"] == "own_content" and video["rights"]["authorization_status"] == "authorized"
    review = client.get("/api/approval/queue", params={"status": "review"}).json()
    mine = [i for i in review if i["clip"]["video_id"] == f["video_id"]]
    assert len(mine) == 1 and mine[0]["render"]["status"] == "completed"
    assert mine[0]["render"]["config"]["subtitle_preset"] == "viral"          # folder edit settings applied
    assert mine[0]["clip"]["status"] == "review"                              # never auto-approved
    n = client.get("/api/notifications", params={"unread_only": True}).json()
    assert any("da revisionare" in i["title"] for i in n["items"])


def test_resource_gating_pause_window_idle(client, tmp_path, media_dir, monkeypatch):
    from tests.conftest import make_video

    folder = tmp_path / "gate"
    folder.mkdir()
    fid = client.post("/api/watch-folders", json={"path": str(folder), "pipeline": {"analyze": False}}).json()["id"]
    make_video(folder / "a.mp4", seconds=3, tag="test_auto_pipeline-3")

    settings(client, paused=True)
    base = utcnow()
    assert watcher.tick(now=base).get("paused")
    assert client.get("/api/watch-folders/files", params={"folder_id": fid}).json() == []   # nothing scanned

    # outside the time window → imported but deferred
    now_h = __import__("datetime").datetime.now().hour
    start, end = f"{(now_h + 2) % 24:02d}:00", f"{(now_h + 3) % 24:02d}:00"
    settings(client, window={"enabled": True, "start": start, "end": end})
    watcher.tick(now=base)
    watcher.tick(now=base + timedelta(seconds=30))
    f = client.get("/api/watch-folders/files", params={"folder_id": fid}).json()[0]
    assert f["status"] == "deferred" and "fascia oraria" in f["reason"]

    # idle-only with a busy GPU → still deferred
    monkeypatch.setattr(common.os, "getloadavg", lambda: (0.1, 0.1, 0.1))  # CPU idle, GPU busy (gaming)
    monkeypatch.setattr(common, "gpu_utilisation", lambda: 95)
    settings(client, idle_only=True)
    watcher.tick(now=base + timedelta(seconds=40))
    f = client.get("/api/watch-folders/files", params={"folder_id": fid}).json()[0]
    assert f["status"] == "deferred" and "GPU occupata" in f["reason"]

    # resume → submitted
    monkeypatch.setattr(common, "gpu_utilisation", lambda: 5)
    settings(client)
    watcher.tick(now=base + timedelta(seconds=50))
    f = client.get("/api/watch-folders/files", params={"folder_id": fid}).json()[0]
    assert f["status"] == "processing"
    assert wait_job(client, f["job_id"])["status"] == "completed"


def test_resume_after_restart(client, tmp_path, media_dir):
    from backend.database.session import session_scope
    from backend.models import Job, WatchedFile
    from tests.conftest import make_video

    folder = tmp_path / "restart"
    folder.mkdir()
    fid = client.post("/api/watch-folders", json={"path": str(folder), "pipeline": {"analyze": False}}).json()["id"]
    make_video(folder / "r.mp4", seconds=4, tag="test_auto_pipeline-4")
    base = utcnow()
    watcher.tick(now=base)
    watcher.tick(now=base + timedelta(seconds=30))
    f = client.get("/api/watch-folders/files", params={"folder_id": fid}).json()[0]
    wait_job(client, f["job_id"])
    with session_scope() as db:  # simulate: the job was interrupted by an application restart
        wf = db.get(WatchedFile, f["id"])
        wf.status = "processing"
        job = db.get(Job, wf.job_id)
        job.status, job.error = "failed", "Interrupted by application restart"
    watcher.tick(now=base + timedelta(seconds=60))
    f2 = client.get("/api/watch-folders/files", params={"folder_id": fid}).json()[0]
    assert f2["status"] == "processing" and f2["job_id"] != f["job_id"] and f2["attempts"] == 2
    assert wait_job(client, f2["job_id"])["status"] == "completed"
