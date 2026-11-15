from backend.core.config import get_settings


def test_scan_and_cleanup_only_orphans(client, tmp_path, media_dir):
    from tests.conftest import make_video

    s = get_settings()
    # a managed video that is in the library must survive
    src = make_video(media_dir / "keep.mp4", seconds=2, tag="maint-keep")
    with src.open("rb") as fh:
        vid = client.post("/api/videos/upload", files=[("files", ("keep.mp4", fh, "video/mp4"))]).json()["videos"][0]
    orphan_video = s.videos_dir / "orphan_upload.mp4"
    orphan_video.write_bytes(b"x" * 1000)
    orphan_cache = s.cache_dir / "deadbeef"
    orphan_cache.mkdir(parents=True, exist_ok=True)
    (orphan_cache / "audio.wav").write_bytes(b"y" * 2000)
    orphan_render = s.renders_dir / "notarender"
    orphan_render.mkdir(parents=True, exist_ok=True)
    (orphan_render / "clip.mp4").write_bytes(b"z" * 3000)
    outside = tmp_path / "outside.mp4"
    outside.write_bytes(b"o")

    scan = client.get("/api/maintenance/scan").json()
    assert scan["orphan_videos"]["count"] >= 1 and scan["orphan_videos"]["bytes"] >= 1000
    assert scan["orphan_cache"]["count"] >= 1 and scan["orphan_renders"]["count"] >= 1

    assert client.post("/api/maintenance/cleanup", json={"categories": ["orphan_videos"]}).status_code == 422
    r = client.post("/api/maintenance/cleanup", json={"categories": ["orphan_videos", "orphan_cache", "orphan_renders",
                                                                    "database"], "confirm": True}).json()
    assert r["freed_bytes"] >= 6000 and r["removed"] >= 3
    assert not orphan_video.exists() and not orphan_cache.exists() and not orphan_render.exists()
    assert outside.exists()
    v = client.get(f"/api/videos/{vid['id']}").json()
    from pathlib import Path

    assert Path(v["file_path"]).exists()  # library files untouched
