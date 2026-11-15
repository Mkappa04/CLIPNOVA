import shutil
from datetime import timedelta

import pytest

from backend.automation.watcher import is_temp_name, watcher
from backend.core.timeutil import utcnow
from tests.conftest import make_video

NO_PIPELINE = {"analyze": False, "render_top_n": 0, "detect_webcam": False}


def add_folder(client, path, **kw):
    body = {"name": "test", "path": str(path), "pipeline": NO_PIPELINE, "extensions": [".mp4", ".mkv", ".mov"], **kw}
    r = client.post("/api/watch-folders", json=body)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def files(client, fid):
    return {f["name"]: f for f in client.get("/api/watch-folders/files", params={"folder_id": fid}).json()}


def ticks(*offsets, base=None):
    base = base or utcnow()
    for o in offsets:
        watcher.tick(now=base + timedelta(seconds=o))
    return base


def test_temp_names():
    assert is_temp_name("rec.mp4.part") and is_temp_name("~$x.mp4") and is_temp_name(".hidden.mp4")
    assert not is_temp_name("2026-11-15 20-00-00.mp4")


def test_waits_until_written_and_finalised(client, tmp_path, media_dir):
    src = make_video(media_dir / "w_src.mp4", seconds=7, tag="test_watcher-7")
    folder = tmp_path / "obs"
    folder.mkdir()
    fid = add_folder(client, folder)
    target = folder / "recording.mp4"
    data = src.read_bytes()
    target.write_bytes(data[: len(data) // 2])            # OBS still writing (no moov atom yet)
    base = ticks(0)
    assert files(client, fid)["recording.mp4"]["status"] == "waiting"
    ticks(30, base=base)                                   # size stable but not a finalised MP4
    f = files(client, fid)["recording.mp4"]
    assert f["status"] == "waiting" and "finalizzato" in f["reason"]
    target.write_bytes(data)                               # recording finished
    ticks(31, 33, 60, base=base)
    f = files(client, fid)["recording.mp4"]
    assert f["status"] in ("ready", "processing", "done"), f
    (folder / "clip.mp4.part").write_bytes(b"x")
    ticks(90, base=base)
    assert "clip.mp4.part" not in files(client, fid)


def test_obs_remux_and_duplicates(client, tmp_path, media_dir):
    src = make_video(media_dir / "remux_src.mkv", seconds=6, tag="test_watcher-6")
    folder = tmp_path / "remux"
    folder.mkdir()
    fid = add_folder(client, folder)
    shutil.copy(src, folder / "session.mkv")
    base = ticks(0, 15)
    assert files(client, fid)["session.mkv"]["status"] == "waiting"   # waiting for a possible remux
    # OBS remuxes to mp4 → only the mp4 is imported
    subprocess_remux(folder / "session.mkv", folder / "session.mp4")
    ticks(16, 40, 80, base=base)
    fs = files(client, fid)
    assert fs["session.mkv"]["status"] == "skipped" and "Remux" in fs["session.mkv"]["reason"]
    assert fs["session.mp4"]["status"] in ("ready", "processing", "done")

    # the same content under another name is never imported twice
    shutil.copy(folder / "session.mp4", folder / "copy of session.mp4")
    ticks(100, 130, base=base)
    dup = files(client, fid)["copy of session.mp4"]
    assert dup["status"] == "duplicate" and "Già importato" in dup["reason"]


def test_mkv_alone_imported_after_grace(client, tmp_path, media_dir):
    src = make_video(media_dir / "alone.mkv", seconds=5, tag="test_watcher-5")
    folder = tmp_path / "mkv"
    folder.mkdir()
    fid = add_folder(client, folder)
    shutil.copy(src, folder / "game.mkv")
    base = ticks(0, 15)
    assert files(client, fid)["game.mkv"]["status"] == "waiting"
    ticks(200, base=base)
    assert files(client, fid)["game.mkv"]["status"] in ("ready", "processing", "done")


def test_folder_validation(client, tmp_path):
    r = client.post("/api/watch-folders", json={"path": r"C:\Questa\Cartella\NonEsiste"})
    assert r.status_code == 422 and "/mnt/c/Questa/Cartella/NonEsiste" in r.json()["message"]
    from backend.core.config import get_settings

    r = client.post("/api/watch-folders", json={"path": str(get_settings().videos_dir)})
    assert r.status_code == 422
    r = client.post("/api/watch-folders", json={"path": str(tmp_path), "extensions": [".exe"]})
    assert r.status_code == 422


def subprocess_remux(src, dst):
    import subprocess

    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(src), "-c", "copy", str(dst)],
                   check=True)
