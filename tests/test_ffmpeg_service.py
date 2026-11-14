import pytest

from backend.core.exceptions import MediaError
from backend.services import ffmpeg
from tests.conftest import make_video


def test_probe_reads_metadata(sample_video):
    info = ffmpeg.probe(sample_video)
    assert (info.width, info.height) == (1280, 720)
    assert info.fps == 30
    assert info.duration == pytest.approx(3, abs=0.2)
    assert info.has_audio and info.audio_codec == "aac" and info.video_codec == "h264"


def test_probe_rejects_non_video(media_dir):
    bad = media_dir / "bad.mp4"
    bad.write_text("not a video")
    with pytest.raises(MediaError):
        ffmpeg.probe(bad)


def test_thumbnail(sample_video, media_dir):
    out = ffmpeg.generate_thumbnail(sample_video, media_dir / "t.jpg", at_seconds=1)
    assert out.stat().st_size > 1000


def test_run_ffmpeg_progress_and_cancel(media_dir):
    src = make_video(media_dir / "long.mp4", seconds=20, size="640x360", audio=False)
    seen = []
    ffmpeg.run_ffmpeg(["-i", str(src), "-c:v", "libx264", "-preset", "ultrafast", "-y", str(media_dir / "o.mp4")],
                      duration=20, on_progress=seen.append)
    assert seen and max(seen) > 0.5

    calls = {"n": 0}

    def cancel_soon():
        calls["n"] += 1
        return calls["n"] > 2

    with pytest.raises(ffmpeg.FFmpegCancelled):
        ffmpeg.run_ffmpeg(["-re", "-i", str(src), "-f", "null", "-"], duration=20, should_cancel=cancel_soon)
