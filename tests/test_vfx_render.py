"""Visual Effects Engine (pixels), time remapping, and a real FFmpeg render with slow motion + freeze frame +
music: output duration, audio/video sync of an event after the remapping, soundtrack present."""

import subprocess

import numpy as np
import pytest

from backend.editing import vfx
from backend.editing.config import EditConfig
from backend.editing.plan import EditPlan, Look, MusicCue, TimeEffect
from backend.editing.timeline import Segment, apply_time_effects, inverse, map_interval, map_time, output_duration


def img(color=(60, 120, 180), w=108, h=192) -> np.ndarray:
    return np.full((h, w, 3), color, np.uint8)


# ------------------------------------------------------------------ effects
def test_grade_and_vignette():
    base = img()
    assert np.array_equal(vfx.Grade("cinematic", 0.0)(base), base)               # intensity 0 = identity
    warm = vfx.Grade("warm", 1.0)(base).astype(int)
    assert warm[..., 2].mean() > base[..., 2].mean() and warm[..., 0].mean() < base[..., 0].mean()
    bw = vfx.Grade("bw", 1.0)(base)
    assert np.ptp(bw[0, 0].astype(int)) <= 2                                       # no colour left
    v = vfx.Grade("none", 0, vignette=1.0, size=(108, 192))(np.full((192, 108, 3), 200, np.uint8))
    assert v[0, 0].mean() < v[96, 54].mean() - 40                                  # corners darker


def test_glitch_flash_freeze_and_transitions():
    rng = np.random.default_rng(0)
    frame = rng.integers(0, 255, (192, 108, 3)).astype(np.uint8)
    g1, g2 = vfx.glitch(frame, 0.8, 7), vfx.glitch(frame, 0.8, 7)
    assert np.array_equal(g1, g2) and not np.array_equal(g1, frame)               # deterministic, visible
    assert np.array_equal(vfx.glitch(frame, 0.0, 7), frame)
    assert vfx.flash(frame, 0.9).mean() > 220
    fz = vfx.freeze_look(frame, 0.8)
    assert np.abs(fz.astype(int) - frame).mean() > 5 and fz[13:17, 30:70].mean() > 200   # white edge
    for kind in ("zoom_blur", "flash", "glitch", "dip"):
        at_cut = vfx.transition(frame, kind, 0.0, seed=1)
        assert not np.array_equal(at_cut, frame), kind
        assert np.array_equal(vfx.transition(frame, kind, 1.0), frame)            # nothing at the edges
    assert vfx.transition(frame, "dip", 0.0).max() == 0
    assert len(vfx.CATALOG) == 14


# ------------------------------------------------------------------ time remapping
def test_time_effects_mapping_is_exact_and_invertible():
    segs = [Segment(0, 4, 0), Segment(5, 10, 4)]
    fx = [TimeEffect(kind="slow_motion", start=1, end=2, speed=0.5), TimeEffect(kind="freeze_frame", start=6, hold=0.5),
          TimeEffect(kind="speed_ramp", start=7, end=9, speed=0.4)]
    out = apply_time_effects(segs, fx, 30)
    assert all(abs(s.out_duration * 30 - round(s.out_duration * 30)) < 1e-6 for s in out)   # frame grid
    assert output_duration(out) > 9 + 1 + 0.5
    assert map_time(1.5, out) == pytest.approx(2.0)                      # 1 + 0.5 / 0.5
    assert map_time(6.0, out, last=True) - map_time(6.0, out) == pytest.approx(0.5)
    assert map_time(4.5, out) is None                                    # inside the cut
    a, b = map_interval(0.5, 3.0, out)
    assert (a, b) == pytest.approx((0.5, 4.0))                           # spans the slow motion
    prev = -1.0
    for k in range(int(output_duration(out) * 30)):
        t, seg = inverse(k / 30, out)
        assert t >= prev - 1e-9
        prev = t
        if seg.hold == 0:
            assert map_time(t, out) == pytest.approx(k / 30, abs=1e-6) or seg.start == t


# ------------------------------------------------------------------ real render
@pytest.fixture(scope="module")
def event_video(tmp_path_factory):
    """10 s dark video with a white flash AND a 1 kHz beep at exactly 5.0 s."""
    p = tmp_path_factory.mktemp("vfx") / "event.mp4"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                    "-f", "lavfi", "-i", "color=c=0x202020:s=640x360:r=30:d=10,"
                                         "drawbox=x=0:y=0:w=iw:h=ih:color=white:t=fill:enable='between(t,5,5.099)'",
                    "-f", "lavfi", "-i", "sine=f=1000:d=10,volume=4,volume=0:enable='not(between(t,5,5.1))'",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(p)], check=True)
    return p


def decode_video_brightness(path) -> np.ndarray:
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vf", "scale=54:96", "-f", "rawvideo",
                          "-pix_fmt", "gray", "pipe:1"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, 96 * 54).mean(1)


def decode_audio(path, sr=48000) -> np.ndarray:
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(sr), "-f", "f32le",
                          "pipe:1"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.float32)


def test_render_slow_motion_freeze_music_keeps_av_sync(event_video, tmp_path):
    from backend.editing import music_synth
    from backend.editing.audio_library import _write_flac
    from backend.editing.renderer import ClipSource, render

    y, ti = music_synth.render("chill")
    mp = tmp_path / "chill.flac"
    _write_flac(mp, y, music_synth.SR)
    cfg = EditConfig(crop_mode="center", subtitles=False, transitions=False, normalize_audio=False, zoom=False,
                     quality="draft", fps=30, music="auto", look="none")
    plan = EditPlan(preset="custom", duration=10.0,
                    time_effects=[TimeEffect(kind="slow_motion", start=1.0, end=3.0, speed=0.5),
                                  TimeEffect(kind="freeze_frame", start=4.0, hold=0.5)],
                    look=Look(grade="cinematic", intensity=0.6, vignette=0.3),
                    music=MusicCue(asset_id="t", mood="chill", path=str(mp), bpm=ti.bpm, drop_time=ti.drop_time,
                                   level_db=-40, duck_db=0, fade_in=0.2, fade_out=0.5, sync_at=5.0))
    cs = ClipSource(clip_id="e2e", video_id="no-analysis-e2e", src=event_video, start=0.0, end=10.0, peak_time=None,
                    title="t", width=640, height=360, has_audio=True, webcam=None, subtitles=[], config=cfg, fps=30)
    stats = render(cs, tmp_path / "out", edit=plan)
    out = tmp_path / "out" / "clip.mp4"
    expected = 10.0 + 2.0 + 0.5                        # slow motion adds 2 s, the freeze 0.5 s
    assert stats["expected_duration"] == pytest.approx(expected, abs=0.05)
    assert stats["duration"] == pytest.approx(expected, abs=0.1)
    assert not (tmp_path / "out" / "bed.tmp.wav").exists()                     # temporary file cleaned
    event_out = 5.0 + 2.0 + 0.5                        # the 5.0 s event after the remapping
    bright = decode_video_brightness(out)
    t_video = np.argmax(bright) / 30
    a = decode_audio(out)
    t_audio = np.argmax(np.abs(a) > 0.3) / 48000
    assert t_video == pytest.approx(event_out, abs=0.05)
    assert t_audio == pytest.approx(event_out, abs=0.05)
    assert abs(t_video - t_audio) <= 1.5 / 30                                 # audio and video stay in sync
    # music under the silent parts (the original audio is silent there), at the requested low level
    quiet = a[int(9.0 * 48000):int(9.8 * 48000)]
    lvl = 20 * np.log10(np.sqrt(np.mean(quiet ** 2)) + 1e-12)
    assert -55 < lvl < -30
    assert stats["soundtrack"]["music"]["sync"] and stats["music"]["mood"] == "chill"
    assert {t["kind"] for t in stats["time_effects"]} == {"slow_motion", "freeze_frame"}
