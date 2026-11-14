"""Test fixtures: isolated data dir, synthetic videos generated with ffmpeg."""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

import pytest

_TMP = Path(os.environ.get("CLIPNOVA_TEST_TMP", "/tmp")) / f"clipnova-test-{os.getpid()}"
os.environ["CLIPNOVA_DATA_DIR"] = str(_TMP / "data")
os.environ["CLIPNOVA_LOG_LEVEL"] = "WARNING"
os.environ.pop("CLIPNOVA_DATABASE_URL", None)
# Small Whisper models + shared model cache so tests don't re-download weights
os.environ["CLIPNOVA_WHISPER_MODEL"] = "tiny"
os.environ["CLIPNOVA_WHISPER_CPU_MODEL"] = "tiny"
os.environ["CLIPNOVA_MODELS_PATH"] = str(Path(__file__).resolve().parents[1] / "data" / "models")

DATA = Path(__file__).parent / "data"


@pytest.fixture(scope="session")
def media_dir() -> Path:
    d = _TMP / "media"
    d.mkdir(parents=True, exist_ok=True)
    return d


def make_video(path: Path, seconds: float = 3, size: str = "1280x720", rate: int = 30, audio: bool = True) -> Path:
    args = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", f"testsrc2=size={size}:rate={rate}:duration={seconds}"]
    if audio:
        args += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}", "-c:a", "aac", "-shortest"]
    args += ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(path)]
    subprocess.run(args, check=True)
    return path


@pytest.fixture(scope="session")
def sample_video(media_dir: Path) -> Path:
    return make_video(media_dir / "gta6 sample-clip.mp4")


@pytest.fixture(scope="session")
def gameplay_video(media_dir: Path) -> Path:
    """60 s synthetic gameplay: cuts at 20/35 s, English speech at 25 s, loud burst at 45 s."""
    out = media_dir / "gameplay.mp4"
    script = Path(__file__).resolve().parents[1] / "scripts" / "make_test_gameplay.sh"
    subprocess.run(["bash", str(script), str(DATA / "jfk.flac"), str(out)], check=True)
    return out


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient

    from backend.main import app

    with TestClient(app) as c:
        yield c


def wait_job(client, job_id: str, timeout: float = 180) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("completed", "failed", "cancelled"):
            return job
        time.sleep(0.1)
    raise AssertionError(f"Job {job_id} did not finish in {timeout}s")


@pytest.fixture(scope="session", autouse=True)
def _cleanup_tmp():
    yield
    import shutil

    shutil.rmtree(_TMP, ignore_errors=True)
