"""End-to-end: presets → AI editing plan → real FFmpeg render with Brand Kit logo, subtitles, SFX.

Checks the output, not just that a job finished: resolution, codecs, fps, duration, audio, logo pixels
(position + opacity), subtitles drawn, tracking used, and error handling."""

import subprocess

import cv2
import numpy as np
import pytest

from tests.conftest import unique_copy, wait_job

MAGENTA = np.array([255, 0, 255])  # BGR


def logo_png(w=200, h=100, border=10, alpha=255) -> bytes:
    img = np.zeros((h, w, 4), np.uint8)
    img[border:h - border, border:w - border] = (255, 0, 255, alpha)
    return cv2.imencode(".png", img)[1].tobytes()


def upload_logo(client, data: bytes, name="logo.png"):
    return client.post("/api/brand-kit/logo", files={"file": (name, data, "image/png")})


def probe(path) -> dict:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                          "stream=codec_type,codec_name,width,height,r_frame_rate:format=duration",
                          "-of", "json", str(path)], capture_output=True, text=True, check=True).stdout
    import json
    return json.loads(out)


def frame_at(path, t: float) -> np.ndarray:
    raw = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", f"{t:.2f}", "-i", str(path),
                          "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "bgr24", "pipe:1"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(1920, 1080, 3)


def jpeg(resp) -> np.ndarray:
    assert resp.status_code == 200, resp.text
    return cv2.imdecode(np.frombuffer(resp.content, np.uint8), cv2.IMREAD_COLOR).astype(np.float64)


@pytest.fixture(scope="module")
def game_clip(client, gameplay_video, media_dir):
    """Analysed synthetic gameplay; manual clip 33-47 s: end of speech, pause, loud burst at 45 s."""
    src = unique_copy(gameplay_video, media_dir / "gameplay_edit.mp4", "editing-engine")
    with src.open("rb") as fh:
        r = client.post("/api/videos/upload", files=[("files", (src.name, fh, "video/mp4"))], data={"game": "GTA 6"})
    vid = r.json()["videos"][0]["id"]
    assert wait_job(client, r.json()["job_ids"][0])["status"] == "completed"
    assert wait_job(client, client.post(f"/api/videos/{vid}/analyze", json={}).json()["job_id"],
                    timeout=300)["status"] == "completed"
    clip = client.post(f"/api/videos/{vid}/clips", json={"start": 33.0, "end": 47.0, "category": "reaction",
                                                         "suggested_title": "Editing engine test"}).json()
    return vid, clip["id"]


@pytest.fixture(autouse=True)
def _no_logo(client):
    yield
    if client.get("/api/brand-kit").json()["logo"]:
        client.delete("/api/brand-kit/logo", params={"confirm": True})


# ------------------------------------------------------------------ Brand Kit API
def test_brand_kit_upload_validation_and_settings(client):
    st = client.get("/api/brand-kit").json()
    assert st["logo"] is None and st["limits"]["format"] == "PNG"
    # invalid uploads
    jpg = cv2.imencode(".jpg", np.zeros((64, 64, 3), np.uint8))[1].tobytes()
    assert upload_logo(client, jpg, "logo.png").status_code == 422                      # JPEG renamed .png
    assert upload_logo(client, b"\x89PNG\r\n\x1a\n" + b"garbage" * 20).status_code == 422  # fake PNG
    assert upload_logo(client, logo_png(alpha=0)).json()["error"] == "invalid_logo"     # fully transparent
    from backend.core.config import get_settings
    big = get_settings().brand_logo_max_mb
    get_settings().brand_logo_max_mb = 0.0001
    try:
        r = upload_logo(client, logo_png())
        assert r.status_code == 422 and r.json()["error"] == "logo_too_large"
    finally:
        get_settings().brand_logo_max_mb = big

    r = upload_logo(client, logo_png(), "../../etc/my logo.png")
    assert r.status_code == 201, r.text
    s = r.json()
    assert s["logo"]["width"] == 180 and s["logo"]["height"] == 80   # transparent border trimmed
    assert s["logo"]["original_name"] == "my logo.png" and "/" not in s["logo"]["url"].split("?")[0][15:]
    assert "brand" not in str(s["logo"]) or "data/brand" not in str(s)  # no server paths exposed
    png = client.get("/api/brand-kit/logo")
    assert png.headers["content-type"] == "image/png"
    img = cv2.imdecode(np.frombuffer(png.content, np.uint8), cv2.IMREAD_UNCHANGED)
    assert img.shape == (80, 180, 4)

    # settings + placement (aspect preserved, inside the frame, out of the platform UI)
    for pos in ("top-left", "top-right", "bottom-left", "bottom-right"):
        p = client.put("/api/brand-kit/settings", json={"position": pos, "size": 0.2, "opacity": 0.7,
                                                         "margin": 30, "enabled": True}).json()["placement"]
        assert p["w"] == 216 and p["h"] == 96 and p["corner"] == pos
        assert 0 <= p["x"] and p["x"] + p["w"] <= 1080 and 0 <= p["y"] and p["y"] + p["h"] <= 1920
        assert (p["y"] >= 190) if pos.startswith("top") else (p["y"] + p["h"] <= 1920 - 380)
    assert client.put("/api/brand-kit/settings", json={"opacity": 3}).status_code == 422

    # replace keeps one logo, delete needs confirmation
    r2 = upload_logo(client, logo_png(120, 120)).json()
    assert r2["logo"]["width"] == 100 and r2["logo"]["id"] != s["logo"]["id"]
    assert client.delete("/api/brand-kit/logo").status_code == 422
    assert client.delete("/api/brand-kit/logo", params={"confirm": True}).json()["logo"] is None
    assert client.get("/api/brand-kit/logo").status_code == 404


# ------------------------------------------------------------------ presets + plan via API
def test_presets_and_plan_api(client, game_clip):
    vid, cid = game_clip
    presets = client.get("/api/editing/presets").json()
    five = ["gaming_dynamic", "gaming_cinematic", "sports_highlights", "podcast_clean", "storytelling"]
    assert [p["id"] for p in presets][:5] == five
    for pid in five:
        cfg = client.put(f"/api/clips/{cid}/preset", json={"preset": pid}).json()["config"]
        assert cfg["preset"] == pid
        plan = client.get(f"/api/clips/{cid}/edit-plan").json()["plan"]
        assert plan["preset"] == pid and plan["segments"][0]["start"] == 0
        assert plan["segments"][-1]["end"] == pytest.approx(14.0, abs=0.05)
    assert client.put(f"/api/clips/{cid}/preset", json={"preset": "nope"}).status_code == 422

    client.put(f"/api/clips/{cid}/preset", json={"preset": "gaming_dynamic"})
    job = client.post(f"/api/clips/{cid}/edit-plan", json={"force": True}).json()["job_id"]
    done = wait_job(client, job)
    assert done["status"] == "completed", done
    st = client.get(f"/api/clips/{cid}/edit-plan").json()
    assert st["stored"] and not st["stale"]
    plan = st["plan"]
    boom = [s for s in plan["segments"] if s["start"] <= 12.2 <= s["end"]][0]   # burst at 45 s = 12 s in clip
    assert boom["effect"] != "none" and boom["reason"]
    assert any(s["effect"] == "none" for s in plan["segments"])
    # every auto-detected clip of the analysis can be planned (compatibility with clip detection)
    for c in client.get("/api/clips", params={"video_id": vid}).json():
        r = client.get(f"/api/clips/{c['id']}/edit-plan")
        assert r.status_code == 200 and r.json()["plan"]["segments"]
    assert client.get("/api/clips/does-not-exist/edit-plan").status_code == 404
    from backend.editing.effects import CATEGORIES
    assert [x["category"] for x in client.get("/api/sfx").json()] == list(CATEGORIES)


# ------------------------------------------------------------------ preview: logo opacity/position, subtitles
def test_preview_logo_opacity_position_and_subtitles(client, game_clip):
    _, cid = game_clip
    upload_logo(client, logo_png())
    base = client.get(f"/api/clips/{cid}/edit").json()["config"]
    cfg = {**base, "preset": "gaming_dynamic", "subtitles": False, "zoom": False, "effects": False, "intro": False}

    def preview(**kw):
        return jpeg(client.post(f"/api/clips/{cid}/preview-frame", json={"t": 1.0, "config": {**cfg, **kw}}))

    off = preview(logo=False)
    for pos, opacity in (("top-left", 1.0), ("bottom-right", 0.5)):
        p = client.put("/api/brand-kit/settings", json={"position": pos, "size": 0.2, "opacity": opacity,
                                                         "margin": 40}).json()["placement"]
        on = preview(logo=True)
        # preview is 540x960 = half scale; sample the inner part of the logo box
        x0, y0, x1, y1 = [v // 2 for v in (p["x"] + 30, p["y"] + 20, p["x"] + p["w"] - 30, p["y"] + p["h"] - 20)]
        exp = off[y0:y1, x0:x1] * (1 - opacity) + MAGENTA * opacity
        assert np.abs(on[y0:y1, x0:x1] - exp).mean() < 18, (pos, opacity)
        # elsewhere the frame is untouched
        assert np.abs(on[480:500, 200:300] - off[480:500, 200:300]).mean() < 8   # JPEG / pipeline noise only
    # subtitles toggle: speech at the start of this clip → text in the lower-middle band
    with_subs = preview(subtitles=True, logo=False, subtitle_preset="gaming")
    band = slice(int(960 * 0.62) - 50, int(960 * 0.62) + 50)
    assert np.abs(with_subs[band] - off[band]).mean() > 6
    assert np.abs(with_subs[100:200] - off[100:200]).mean() < 3


# ------------------------------------------------------------------ full render
def test_render_gaming_dynamic_with_logo_and_sfx(client, game_clip):
    from backend.core.config import get_settings

    _, cid = game_clip
    upload_logo(client, logo_png())
    client.put("/api/brand-kit/settings", json={"position": "top-left", "size": 0.2, "opacity": 1.0, "margin": 40})
    cfg = {**client.get(f"/api/clips/{cid}/edit").json()["config"]}
    client.put(f"/api/clips/{cid}/preset", json={"preset": "gaming_dynamic"})
    cfg = {**client.get(f"/api/clips/{cid}/edit").json()["config"], "quality": "draft", "fps": "auto", "logo": True}
    job = client.post(f"/api/clips/{cid}/render", json={"config": cfg})
    assert job.status_code == 202, job.text
    done = wait_job(client, job.json()["job_id"], timeout=400)
    assert done["status"] == "completed", done
    r = client.get("/api/renders", params={"clip_id": cid}).json()[0]
    stats = r["stats"]
    mp4 = get_settings().renders_dir / r["id"] / "clip.mp4"

    info = probe(mp4)
    v = next(s for s in info["streams"] if s["codec_type"] == "video")
    a = next(s for s in info["streams"] if s["codec_type"] == "audio")
    assert (v["codec_name"], v["width"], v["height"]) == ("h264", 1080, 1920)   # 16:9 → 9:16
    assert v["r_frame_rate"] == "30/1" and stats["fps"] == 30                   # "auto" = source 30 fps
    assert a["codec_name"] == "aac"
    dur = float(info["format"]["duration"])
    assert dur == pytest.approx(r["duration"], abs=0.1) and dur == pytest.approx(stats["expected_duration"], abs=0.1)
    added = sum((t["out_end"] - t["out_start"]) for t in stats["time_effects"])
    if not stats["time_effects"]:
        assert dur == pytest.approx(14.0 - stats["cut_seconds"], abs=0.3)
    else:   # slow motion / speed ramp lengthen the clip, bounded by the plan validator (≤ 30 %)
        assert 14.0 - stats["cut_seconds"] < dur <= (14.0 - stats["cut_seconds"]) * 1.3 + 0.2 and added > 0
    assert stats["preset"] == "gaming_dynamic" and stats["plan"]["effects"]
    assert stats["sfx"] and stats["tracking"] in ("action", "center")
    assert stats["logo"] == {"corner": "top-left", "x": 76, "y": 230, "w": 216, "h": 96, "opacity": 1.0}
    assert (get_settings().renders_dir / r["id"] / "plan.json").exists()

    # logo pixels in the encoded video, at its exact place, on several frames
    for t in (0.5, dur / 2, dur - 0.6):
        f = frame_at(mp4, t).astype(np.float64)
        inner = f[230 + 15:230 + 96 - 15, 76 + 15:76 + 216 - 15]
        assert np.abs(inner - MAGENTA).mean() < 25, t
    # audio is really there (not silence) and the file plays to the end
    full = subprocess.run(["ffmpeg", "-v", "error", "-i", str(mp4), "-f", "null", "-"], capture_output=True, text=True)
    assert full.returncode == 0 and not full.stderr.strip()
    vol = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(mp4), "-af", "volumedetect", "-vn", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    assert float(vol.split("max_volume:")[1].split("dB")[0]) > -20
    # the download endpoint serves it
    f = client.get(f"/api/renders/{r['id']}/file", params={"download": True})
    assert f.status_code == 200 and "attachment" in f.headers["content-disposition"]


def test_render_podcast_clean_tracks_the_face(client, webcam_video, media_dir):
    from backend.core.config import get_settings

    src = unique_copy(webcam_video, media_dir / "podcast.mp4", "podcast-face")
    with src.open("rb") as fh:
        r = client.post("/api/videos/upload", files=[("files", (src.name, fh, "video/mp4"))], data={"game": "Podcast"})
    vid = r.json()["videos"][0]["id"]
    assert wait_job(client, r.json()["job_ids"][0])["status"] == "completed"
    assert wait_job(client, client.post(f"/api/videos/{vid}/analyze", json={}).json()["job_id"])["status"] == "completed"
    cid = client.post(f"/api/videos/{vid}/clips", json={"start": 2.0, "end": 8.0, "category": "storytelling",
                                                        "suggested_title": "Podcast test"}).json()["id"]
    client.put(f"/api/clips/{cid}/preset", json={"preset": "podcast_clean"})
    cfg = {**client.get(f"/api/clips/{cid}/edit").json()["config"], "layout": "full", "quality": "draft",
           "logo": False, "subtitles": False}
    done = wait_job(client, client.post(f"/api/clips/{cid}/render", json={"config": cfg}).json()["job_id"])
    assert done["status"] == "completed", done
    r = client.get("/api/renders", params={"clip_id": cid}).json()[0]
    assert r["stats"]["tracking"] == "faces"
    assert set(r["stats"]["plan"]["effects"]) <= {"subtle_zoom", "caption_emphasis"} and not r["stats"]["sfx"]
    # the facecam sits on the left of the 16:9 frame: the vertical crop must show it (skin tones, not testsrc)
    f = frame_at(get_settings().renders_dir / r["id"] / "clip.mp4", 2.0)
    face_area = f[1300:1750, 180:800]   # facecam (x 60-480, y 700-1020 of 1920x1080) after the 1.78x crop
    ycrcb = cv2.cvtColor(face_area, cv2.COLOR_BGR2YCrCb)
    skin = ((ycrcb[..., 1] > 135) & (ycrcb[..., 1] < 180) & (ycrcb[..., 2] > 85) & (ycrcb[..., 2] < 135)).mean()
    assert skin > 0.1, skin


def test_render_errors_are_reported(client, game_clip):
    _, cid = game_clip
    assert client.post(f"/api/clips/{cid}/render", json={"config": {"zoom_strength": 9}}).status_code == 422
    assert client.post(f"/api/clips/{cid}/render", json={"config": {"preset": "unknown"}}).status_code == 422
    assert client.post("/api/clips/missing/render", json={}).status_code == 404
    assert client.put(f"/api/clips/{cid}/edit", json={"fps": 120}).status_code == 422
