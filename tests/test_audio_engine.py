"""Audio Engine + library: built-in music, tempo/beat analysis, beat sync, ducking, loops, SFX stacking,
import with mandatory license (API)."""

import io
import wave

import numpy as np
import pytest

from backend.editing import audio_engine as ae
from backend.editing import audio_library as al
from backend.editing import music_synth as ms


@pytest.fixture(scope="module")
def tracks(tmp_path_factory):
    d = tmp_path_factory.mktemp("music")
    out = {}
    for mood in ("gaming", "chill", "dramatic"):
        y, ti = ms.render(mood)
        p = d / f"{mood}.flac"
        al._write_flac(p, y, ms.SR)
        out[mood] = (p, ti)
    return out


def test_builtin_tracks_have_the_declared_structure(tracks):
    for mood, (p, ti) in tracks.items():
        info = al.analyse_file(p)
        assert info["duration"] == pytest.approx(ti.duration, abs=0.05)
        assert info["bpm"] == pytest.approx(ti.bpm, abs=0.5), mood          # tempo recovered from the audio
        beat = 60 / ti.bpm
        ph = info["beat_offset"] % beat
        assert min(ph, beat - ph) < 0.03, mood                                # beats where the score puts them
        assert -16 < info["loudness_db"] < -4


def speech_level(y, a, b):
    s = y[int(a * ae.SR):int(b * ae.SR)].mean(1)
    return 20 * np.log10(np.sqrt(np.mean(s ** 2)) + 1e-9)


def test_bed_beat_sync_ducking_fades_and_loop(tracks):
    p, ti = tracks["gaming"]
    total = 90.0                     # longer than the track (55 s): must loop
    spec = ae.MusicSpec(path=p, level_db=-20, duck_db=-12, fade_in=0.6, fade_out=1.5, bpm=ti.bpm,
                        drop_time=ti.drop_time, loop_start=ti.loop_start, loop_end=ti.loop_end, sync_out=9.0)
    res = ae.build_bed(total, spec, [], speech=[(20.0, 26.0)])
    y = res.audio
    m = res.report["music"]
    assert y.shape == (int(total * ae.SR), 2) and m["loops"] >= 1
    assert m["sync"].startswith("drop") and m["beat_error_s"] < 0.01         # the drop lands on the climax
    assert m["track_pos_at_sync"] == pytest.approx(ti.drop_time, abs=0.01)
    free, ducked = speech_level(y, 12, 18), speech_level(y, 21, 25)
    assert free == pytest.approx(-20, abs=3)                                  # automatic level
    assert free - ducked == pytest.approx(12, abs=3)                          # ducking under speech
    assert speech_level(y, 0, 0.05) < free - 15                               # fade in
    assert np.abs(y[-200:]).max() < 0.01                                      # fade out
    assert np.abs(y).max() <= ae.db(-3) + 1e-3                                # never above −3 dBFS
    # no click at the loop seam: the jump there is no bigger than what the music itself does
    seam = ti.loop_end - m["start_in_track"]
    dif = np.abs(np.diff(y[:, 0]))
    around = dif[int((seam - 0.02) * ae.SR):int((seam + 0.02) * ae.SR)]
    assert around.max() <= 1.5 * np.percentile(dif[int(12 * ae.SR):int(18 * ae.SR)], 99.99)


def test_sync_without_drop_uses_a_bar_line(tracks):
    p, ti = tracks["chill"]
    spec = ae.MusicSpec(path=p, level_db=-24, duck_db=-8, fade_in=1, fade_out=1, bpm=ti.bpm, beat_offset=0.0,
                        drop_time=1.0, sync_out=12.0)          # drop earlier than the climax → next bar line
    res = ae.build_bed(20.0, spec, [], [])
    m = res.report["music"]
    assert m["sync"].startswith("battere") and m["beat_error_s"] < 0.01
    assert (m["track_pos_at_sync"] / ti.bar_s) == pytest.approx(round(m["track_pos_at_sync"] / ti.bar_s), abs=1e-3)


def test_sound_effects_are_placed_and_never_stacked(tmp_path):
    from backend.editing.effects import sfx_file

    sounds = [ae.SoundSpec(t=1.0, path=sfx_file("impact"), volume=0.8, category="impact"),
              ae.SoundSpec(t=1.1, path=sfx_file("hit"), volume=0.8, category="hit"),
              ae.SoundSpec(t=3.0, path=sfx_file("whoosh"), volume=0.5, category="whoosh")]
    res = ae.build_bed(5.0, None, sounds, [])
    y = res.audio.mean(1)
    onset = np.argmax(np.abs(y) > 0.01) / ae.SR
    assert onset == pytest.approx(1.0, abs=0.01)
    att = {s["category"]: s["attenuated"] for s in res.report["sounds"]}
    assert att == {"impact": False, "hit": True, "whoosh": False}
    assert np.abs(y[int(2.95 * ae.SR):int(3.4 * ae.SR)]).max() > 0.01


def wav_bytes(seconds=10.0, bpm=120.0) -> bytes:
    sr = 22050
    t = np.arange(int(seconds * sr)) / sr
    y = 0.05 * np.sin(2 * np.pi * 220 * t)
    for k in np.arange(0, seconds, 60 / bpm):
        i = int(k * sr)
        n = min(2000, len(y) - i)
        y[i:i + n] += 0.6 * np.exp(-np.arange(n) / 300) * np.sin(2 * np.pi * 60 * np.arange(n) / sr)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((np.clip(y, -1, 1) * 32767).astype("<i2").tobytes())
    return buf.getvalue()


def test_library_import_requires_a_license(client):
    meta = client.get("/api/audio/meta").json()
    assert {m["id"] for m in meta["moods"]} == {"cinematic", "dynamic", "electronic", "chill", "dramatic", "gaming"}
    lib = client.get("/api/audio").json()
    assert sum(a["kind"] == "music" and a["origin"] == "builtin" for a in lib) == 6
    assert all(a["license"] == "cc0" for a in lib if a["origin"] == "builtin")
    for a in lib:     # built-in tracks: level measured on the file (the engine derives the music gain from it)
        if a["kind"] == "music" and a["origin"] == "builtin":
            assert a["loudness_db"] == pytest.approx(al.analyse_file(al.audio_dir() / "builtin" / f"{a['category']}.flac")
                                                     ["loudness_db"], abs=0.2)
    data = wav_bytes(12.0, 120.0)

    def post(**form):
        f = {"kind": "music", "category": "dynamic", "title": "Beat", **form}
        return client.post("/api/audio", files={"file": ("beat.wav", data, "audio/wav")},
                           data={k: str(v) for k, v in f.items()})
    assert post(rights_confirmed=True).json()["error"] == "license_required"
    assert post(license="cc0").json()["error"] == "rights_not_confirmed"
    assert post(license="cc_by", rights_confirmed=True, source_url="https://x.y").json()["error"] == \
        "attribution_required"
    assert post(license="royalty_free", rights_confirmed=True).json()["error"] == "source_required"
    assert post(license="cc0", rights_confirmed=True, category="polka").json()["error"] == "invalid_category"
    bad = client.post("/api/audio", files={"file": ("x.mp3", b"not audio at all" * 50, "audio/mpeg")},
                      data={"kind": "music", "category": "dynamic", "license": "cc0", "rights_confirmed": "true"})
    assert bad.status_code == 422
    r = post(license="own_work", rights_confirmed=True)
    assert r.status_code == 201, r.text
    a = r.json()
    assert a["origin"] == "user" and a["bpm"] == pytest.approx(120, abs=1.5) and a["duration"] == pytest.approx(12, abs=0.1)
    assert "path" not in a
    f = client.get(f"/api/audio/{a['id']}/file")
    assert f.status_code == 200 and f.content[:4] == b"RIFF"
    assert client.patch(f"/api/audio/{a['id']}", json={"gain_db": -4, "enabled": False}).json()["gain_db"] == -4
    builtin = next(x for x in lib if x["origin"] == "builtin")
    assert client.delete(f"/api/audio/{builtin['id']}", params={"confirm": True}).status_code == 422
    assert client.delete(f"/api/audio/{a['id']}").status_code == 422          # confirmation required
    assert client.delete(f"/api/audio/{a['id']}", params={"confirm": True}).json() == {"deleted": a["id"]}
    effects = client.get("/api/editing/effects").json()
    assert len(effects["effects"]) == 14 and {x["id"] for x in effects["looks"]} >= {"cinematic", "teal_orange"}
