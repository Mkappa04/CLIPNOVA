import subprocess
import time

import pytest

from tests.conftest import wait_job


@pytest.fixture(scope="module")
def analyzed(client, gameplay_video):
    with gameplay_video.open("rb") as fh:
        r = client.post("/api/videos/upload", files=[("files", (gameplay_video.name, fh, "video/mp4"))],
                        data={"game": "GTA 6"})
    vid = r.json()["videos"][0]["id"]
    assert wait_job(client, r.json()["job_ids"][0])["status"] == "completed"
    job = client.post(f"/api/videos/{vid}/analyze", json={"language": "auto"})
    assert job.status_code == 202, job.text
    done = wait_job(client, job.json()["job_id"])
    assert done["status"] == "completed", done
    return vid, done


def test_analysis_results(client, analyzed):
    vid, job = analyzed
    assert job["result"]["clips"] >= 2 and job["message"].endswith("clip rilevate")
    v = client.get(f"/api/videos/{vid}").json()
    assert v["status"] == "analyzed" and v["analysis_status"] == "completed" and v["clip_count"] >= 2

    a = client.get(f"/api/videos/{vid}/analysis").json()
    assert a["analysis"]["language"] == "en"
    assert a["analysis"]["scenes"] == pytest.approx([20.0, 35.0], abs=0.6)
    assert set(a["analysis"]["stats"]["timings"]) >= {"prepare", "audio", "scenes", "motion", "transcription"}
    tl = a["timeline"]
    assert len(tl["interest"]) == len(tl["audio"]) > 50 and tl["scenes"]

    tr = client.get(f"/api/videos/{vid}/transcript").json()
    assert "country" in " ".join(s["text"] for s in tr["segments"]).lower()
    srt = client.get(f"/api/videos/{vid}/transcript", params={"format": "srt"})
    assert srt.status_code == 200 and "-->" in srt.text


def test_clips_cover_speech_and_burst(client, analyzed):
    vid, _ = analyzed
    clips = client.get("/api/clips", params={"video_id": vid, "sort": "start"}).json()
    peaks = [c["peak_time"] for c in clips]
    assert any(25 <= p <= 37 for p in peaks), peaks       # speech
    assert any(43 <= p <= 48 for p in peaks), peaks       # loud burst
    ordered = sorted(clips, key=lambda c: c["start"])
    for x, y in zip(ordered, ordered[1:]):
        assert x["end"] <= y["start"] + 0.01, f"overlapping clips {x['start']}-{x['end']} / {y['start']}-{y['end']}"
    burst = min(clips, key=lambda c: abs(c["peak_time"] - 45.5))
    assert "country" not in burst["suggested_title"].lower(), "burst title must not quote unrelated speech"
    for c in clips:
        assert c["video_title"] and c["game"] == "GTA 6"
        assert c["reason"] and c["suggested_title"] and 0 <= c["score"] <= 100
        assert c["end"] <= 60.01 and c["duration"] == pytest.approx(c["end"] - c["start"], abs=0.01)


def test_rescore_edit_preview_and_manual_clip(client, analyzed):
    vid, _ = analyzed
    rescored = client.post(f"/api/videos/{vid}/detect", json={"max_clips": 1, "min_clip_s": 10, "max_clip_s": 20})
    assert rescored.status_code == 200, rescored.text
    auto = [c for c in rescored.json() if c["origin"] == "auto"]
    assert len(auto) == 1 and 10 - 0.01 <= auto[0]["duration"] <= 20.01
    cid = auto[0]["id"]

    # Edit timestamps: transcript excerpt follows, invalid ranges rejected
    upd = client.patch(f"/api/clips/{cid}", json={"start": 24.0, "end": 36.0, "status": "review",
                                                  "suggested_title": "Test"})
    assert upd.status_code == 200
    body = upd.json()
    assert (body["start"], body["end"], body["status"]) == (24.0, 36.0, "review")
    assert "country" in body["transcript"].lower()
    assert client.patch(f"/api/clips/{cid}", json={"end": 24.5}).status_code == 422
    assert client.patch(f"/api/clips/{cid}", json={"end": 99}).status_code == 422

    # Preview is a valid 12 s H.264 MP4
    pv = client.get(f"/api/clips/{cid}/preview")
    assert pv.status_code == 200 and pv.headers["content-type"] == "video/mp4"
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_name",
                          "-of", "csv=p=0", "-i", "pipe:0"], input=pv.content, capture_output=True)
    assert b"h264" in out.stdout and b"aac" in out.stdout

    # A clip in review survives re-scoring
    client.post(f"/api/videos/{vid}/detect", json={})
    assert client.get(f"/api/clips/{cid}").json()["status"] == "review"

    manual = client.post(f"/api/videos/{vid}/clips", json={"start": 1, "end": 8, "category": "epic"})
    assert manual.status_code == 201 and manual.json()["origin"] == "manual"
    mid = manual.json()["id"]
    assert client.delete(f"/api/clips/{mid}").status_code == 422
    assert client.delete(f"/api/clips/{mid}", params={"confirm": True}).status_code == 200


def test_analysis_guards_and_cancel(client, analyzed, sample_video):
    vid, _ = analyzed
    # Second analysis while one is running -> 409; cancel restores the video status
    first = client.post(f"/api/videos/{vid}/analyze", json={"force": True}).json()["job_id"]
    assert client.post(f"/api/videos/{vid}/analyze", json={}).status_code == 409
    deadline = time.time() + 20
    while client.get(f"/api/jobs/{first}").json()["status"] == "queued" and time.time() < deadline:
        time.sleep(0.05)
    client.post(f"/api/jobs/{first}/cancel")
    assert wait_job(client, first)["status"] == "cancelled"
    assert client.get(f"/api/videos/{vid}").json()["status"] == "analyzed"


def test_delete_video_removes_analysis_cache(client, analyzed):
    from backend.clip_detection.pipeline import cache_dir

    vid, _ = analyzed
    assert cache_dir(vid).exists()
    client.delete(f"/api/videos/{vid}", params={"confirm": True, "delete_file": True})
    assert not cache_dir(vid).exists()
    assert client.get("/api/clips", params={"video_id": vid}).json() == []


def test_whisper_cpu_fallback(media_dir):
    from backend.transcription.whisper_engine import engine
    from tests.conftest import DATA

    wav = media_dir / "jfk.wav"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(DATA / "jfk.flac"),
                    "-ac", "1", "-ar", "16000", str(wav)], check=True)
    t = engine.transcribe(wav, force_device="cpu")
    assert t.device == "cpu" and "country" in t.text.lower()


def test_isolated_worker_transcribes_and_cancels(media_dir):
    from backend.transcription.whisper_engine import TranscriptionCancelled, transcribe_isolated
    from tests.conftest import DATA

    wav = media_dir / "jfk_iso.wav"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(DATA / "jfk.flac"),
                    "-ac", "1", "-ar", "16000", str(wav)], check=True)
    seen = []
    t = transcribe_isolated(wav, on_progress=lambda f, m: seen.append(m))
    assert "country" in t.text.lower() and seen

    with pytest.raises(TranscriptionCancelled):
        transcribe_isolated(wav, should_cancel=lambda: True)
