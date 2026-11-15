import subprocess
import time

import cv2
import numpy as np
import pytest

from tests.conftest import wait_job


@pytest.fixture(scope="module")
def cam_clip(client, webcam_video):
    with webcam_video.open("rb") as fh:
        r = client.post("/api/videos/upload", files=[("files", (webcam_video.name, fh, "video/mp4"))],
                        data={"game": "GTA 6"})
    vid = r.json()["videos"][0]["id"]
    assert wait_job(client, r.json()["job_ids"][0])["status"] == "completed"
    assert wait_job(client, client.post(f"/api/videos/{vid}/analyze", json={}).json()["job_id"])["status"] == "completed"
    clip = client.post(f"/api/videos/{vid}/clips", json={"start": 0.5, "end": 14.5, "category": "reaction",
                                                         "suggested_title": "Render test"}).json()
    return vid, clip["id"]


def probe(path_or_bytes):
    args = ["ffprobe", "-v", "error", "-show_entries", "stream=codec_name,width,height:format=duration",
            "-of", "default=nw=1", "-i", "pipe:0"]
    return subprocess.run(args, input=path_or_bytes, capture_output=True).stdout.decode()


def test_webcam_detect_and_manual_override(client, cam_clip):
    vid, _ = cam_clip
    d = client.post(f"/api/videos/{vid}/webcam/detect").json()
    assert d["region"] and d["saved_region"]["source"] == "auto"
    frame = client.get(f"/api/videos/{vid}/frame", params={"t": 3})
    assert frame.headers["content-type"] == "image/jpeg"
    manual = {"x": 0.03, "y": 0.64, "w": 0.22, "h": 0.30}
    assert client.put(f"/api/videos/{vid}/webcam", json=manual).json()["webcam_region"]["source"] == "manual"
    again = client.post(f"/api/videos/{vid}/webcam/detect").json()
    assert again["saved_region"]["source"] == "manual"  # auto-detection never overwrites a manual choice


def test_edit_config_and_preview_frame(client, cam_clip):
    _, cid = cam_clip
    e = client.get(f"/api/clips/{cid}/edit").json()
    assert e["config"]["layout"] == "stack" and e["webcam_region"]  # webcam present → stack by default
    cfg = {**e["config"], "layout": "pip", "subtitle_preset": "viral"}
    assert client.put(f"/api/clips/{cid}/edit", json=cfg).json()["config"]["layout"] == "pip"
    assert client.put(f"/api/clips/{cid}/edit", json={**cfg, "zoom_strength": 9}).status_code == 422
    pv = client.post(f"/api/clips/{cid}/preview-frame", json={"t": 6.0, "config": {**cfg, "layout": "split"}})
    assert pv.status_code == 200, pv.text
    img = cv2.imdecode(np.frombuffer(pv.content, np.uint8), cv2.IMREAD_COLOR)
    assert img.shape[:2] == (960, 540)


def test_subtitle_editing(client, cam_clip):
    _, cid = cam_clip
    s = client.get(f"/api/clips/{cid}/subtitles").json()
    assert not s["edited"] and s["cues"] and "country" in " ".join(c["text"] for c in s["cues"]).lower()
    cues = s["cues"]
    cues[0]["text"] = "TESTO MODIFICATO A MANO"
    saved = client.put(f"/api/clips/{cid}/subtitles", json={"cues": cues}).json()
    assert saved["edited"] and saved["cues"][0]["text"] == "TESTO MODIFICATO A MANO"
    assert len(saved["cues"][0]["words"]) == 4
    srt = client.get(f"/api/clips/{cid}/subtitles/export", params={"format": "srt"}).text
    assert "TESTO MODIFICATO A MANO" in srt and "-->" in srt
    assert "[Events]" in client.get(f"/api/clips/{cid}/subtitles/export", params={"format": "ass"}).text
    assert client.delete(f"/api/clips/{cid}/subtitles").status_code == 422
    # keep the edit for the render test below


def test_render_full_pipeline(client, cam_clip):
    _, cid = cam_clip
    cfg = {"layout": "stack", "subtitle_preset": "gaming", "intro": True, "intro_duration": 1.0, "outro": True,
           "outro_duration": 1.0, "remove_silences": True, "silence_strategy": "no_speech", "quality": "draft"}
    job = client.post(f"/api/clips/{cid}/render", json={"config": cfg})
    assert job.status_code == 202, job.text
    assert client.post(f"/api/clips/{cid}/render", json={}).status_code == 409  # one render at a time
    done = wait_job(client, job.json()["job_id"])
    assert done["status"] == "completed", done
    renders = client.get("/api/renders", params={"clip_id": cid}).json()
    r = renders[0]
    assert r["status"] == "completed" and r["width"] == 1080 and r["height"] == 1920 and r["has_thumbnail"]
    assert r["stats"]["cut_seconds"] > 0  # pauses removed
    expected = 14.0 - r["stats"]["cut_seconds"] + 2.0
    assert r["duration"] == pytest.approx(expected, abs=0.25)
    assert client.get(f"/api/clips/{cid}").json()["status"] == "review"

    f = client.get(f"/api/renders/{r['id']}/file", params={"download": True})
    assert f.status_code == 200 and "attachment" in f.headers["content-disposition"]
    info = probe(f.content)
    assert "codec_name=h264" in info and "codec_name=aac" in info and "width=1080" in info and "height=1920" in info
    # loudness normalised to the social standard (-14 LUFS, two-pass loudnorm)
    from backend.core.config import get_settings

    mp4 = get_settings().renders_dir / r["id"] / "clip.mp4"
    out = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(mp4), "-af", "ebur128", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    integrated = float(out[out.rindex("Summary:"):].split("I:")[1].split("LUFS")[0])
    assert integrated == pytest.approx(-14, abs=1.5), integrated
    srt = client.get(f"/api/renders/{r['id']}/subtitles", params={"format": "srt"}).text
    assert "TESTO MODIFICATO A MANO".upper() in srt.upper()


def test_render_cancel_and_delete(client, cam_clip):
    _, cid = cam_clip
    job = client.post(f"/api/clips/{cid}/render", json={"config": {"layout": "pip", "quality": "high", "fps": 60}}).json()
    deadline = time.time() + 30
    while client.get(f"/api/jobs/{job['job_id']}").json()["progress"] < 0.05 and time.time() < deadline:
        time.sleep(0.1)
    client.post(f"/api/jobs/{job['job_id']}/cancel")
    assert wait_job(client, job["job_id"])["status"] == "cancelled"
    cancelled = [r for r in client.get("/api/renders", params={"clip_id": cid}).json() if r["status"] == "cancelled"]
    assert cancelled
    assert client.get(f"/api/clips/{cid}").json()["status"] == "review"  # previous status restored

    from backend.core.config import get_settings

    done = [r for r in client.get("/api/renders", params={"clip_id": cid}).json() if r["status"] == "completed"][0]
    folder = get_settings().renders_dir / done["id"]
    assert folder.exists()
    assert client.delete(f"/api/renders/{done['id']}").status_code == 422
    assert client.delete(f"/api/renders/{done['id']}", params={"confirm": True}).status_code == 200
    assert not folder.exists()
