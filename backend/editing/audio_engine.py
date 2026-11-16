"""Audio Engine: the clip's soundtrack bed (music + sound effects) on the *output* timeline, in numpy.

The bed is rendered to a WAV and mixed by FFmpeg over the original audio (already cut, time-remapped
and loudness-normalised by the renderer), followed by a limiter. Doing the bed in numpy keeps every
decision exact and testable:

- **music placement / beat sync** — the track position at the clip's climax lands on the track's drop
  (built-in tracks: exact; imported: estimate) or, failing that, on a beat; when the track is shorter
  than needed it loops on its bar-aligned loop region with short crossfades;
- **automatic level** — gain = target level (preset, user volume) − measured loudness of the track's
  loud part, plus the asset's own trim;
- **ducking** — the music drops by ``duck_db`` while someone speaks (word timings from the transcript,
  mapped to the output), anticipating each phrase by 0.15 s and releasing in 0.4 s;
- **fades** — in/out with an equal-power curve;
- **sound effects** — placed at their output time, never stacked: a sound that starts inside the first
  0.3 s of another is attenuated by 6 dB; each SFX also dips the music by 3 dB for 0.25 s so it reads;
- **safety** — the bed is soft-limited at −3 dBFS; the final mix has an FFmpeg limiter at −0.5 dBFS.
"""

from __future__ import annotations

import logging
import math
import wave
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from backend.editing.audio_library import decode, loud_part_db

log = logging.getLogger(__name__)

SR = 48000
CTRL = 200            # control-rate (Hz) for gain envelopes


@dataclass
class MusicSpec:
    path: Path
    level_db: float
    duck_db: float
    fade_in: float
    fade_out: float
    bpm: float | None = None
    beat_offset: float = 0.0
    drop_time: float | None = None
    loop_start: float | None = None
    loop_end: float | None = None
    loudness_db: float | None = None
    gain_db: float = 0.0
    sync_out: float | None = None     # output time of the climax (None = start of the track)


@dataclass
class SoundSpec:
    t: float                          # output time
    path: Path
    volume: float                     # 0..1
    gain_db: float = 0.0
    category: str = ""


@dataclass
class BedResult:
    audio: np.ndarray                 # (n, 2) float32
    report: dict = field(default_factory=dict)


def db(x: float) -> float:
    return 10 ** (x / 20)


def merge_regions(regions: list[tuple[float, float]], gap: float = 0.5) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for a, b in sorted(regions):
        if out and a - out[-1][1] <= gap:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def duck_curve(total: float, speech: list[tuple[float, float]], duck_db: float, attack: float = 0.15,
               release: float = 0.4) -> np.ndarray:
    """Gain in dB at CTRL Hz: 0 outside speech, duck_db inside, linear ramps (attack before, release after)."""
    n = int(math.ceil(total * CTRL)) + 1
    t = np.arange(n) / CTRL
    g = np.zeros(n)
    if duck_db >= 0:
        return g
    for a, b in merge_regions(speech):
        ramp_in = np.clip((t - (a - attack)) / attack, 0, 1)
        ramp_out = np.clip(((b + release) - t) / release, 0, 1)
        g = np.minimum(g, duck_db * np.minimum(ramp_in, ramp_out))
    return g


def music_positions(spec: MusicSpec, track_len: float, total: float) -> tuple[float, str]:
    """Track position at output time 0, and how the sync was achieved."""
    if spec.sync_out is None:
        return 0.0, "inizio della traccia"
    s = spec.sync_out
    if spec.drop_time is not None and spec.drop_time >= s:
        return spec.drop_time - s, "drop della traccia sul culmine"
    if spec.bpm:
        beat = 60.0 / spec.bpm
        bar = 4 * beat
        # earliest bar line (else beat) at or after the climax time, so the track starts at pos ≥ 0
        k = math.ceil((s - spec.beat_offset) / bar - 1e-9)
        pos = spec.beat_offset + k * bar
        return max(0.0, pos - s), "battere della traccia sul culmine"
    return 0.0, "inizio della traccia (tempo sconosciuto)"


def assemble(track: np.ndarray, sr: int, start: float, length: float, loop: tuple[float, float] | None,
             xfade: float = 0.03) -> tuple[np.ndarray, int]:
    """`length` seconds of the track from `start`, then looping on [loop) with short crossfades."""
    need = int(round(length * sr))
    n = len(track)
    if loop is None or loop[1] - loop[0] < 1.0:
        loop = (0.0, n / sr)
    ls, le = int(loop[0] * sr), min(n, int(loop[1] * sr))
    xf = int(xfade * sr)
    out = np.zeros((need, track.shape[1]), np.float32)
    pos = min(int(round(start * sr)), max(0, n - 1))
    first = track[pos:(le if pos < le else n)]
    w = min(len(first), need)
    out[:w] = first[:w]
    loops = 0
    body = track[ls:le]
    while w < need and len(body) > xf + 1:
        seg = body.copy()
        if xf and w >= xf:
            fade = np.linspace(0, 1, xf, dtype=np.float32)[:, None]
            out[w - xf:w] *= 1 - fade          # the end of the previous pass fades out
            seg[:xf] *= fade                   # while the loop start fades in, overlapped
            w -= xf
        take = min(len(seg), need - w)
        out[w:w + take] += seg[:take]
        w += take
        loops += 1
        if loops > 500:
            break
    return out, loops


def load_sound(path: Path) -> np.ndarray:
    if path.suffix.lower() == ".wav":
        try:
            with wave.open(str(path)) as w:
                if w.getsampwidth() == 2 and w.getframerate() == SR:
                    y = np.frombuffer(w.readframes(w.getnframes()), "<i2").astype(np.float32) / 32768
                    y = y.reshape(-1, w.getnchannels())
                    return np.repeat(y, 2, axis=1) if y.shape[1] == 1 else y[:, :2]
        except (wave.Error, OSError):
            pass
    return decode(path, sr=SR, channels=2, max_s=15)


def build_bed(total: float, music: MusicSpec | None, sounds: list[SoundSpec],
              speech: list[tuple[float, float]]) -> BedResult:
    n = int(round(total * SR))
    bed = np.zeros((n, 2), np.float32)
    rep: dict = {"music": None, "sounds": [], "duration": round(total, 3)}
    t_ctrl = np.arange(int(math.ceil(total * CTRL)) + 1) / CTRL
    sfx_dip = np.zeros_like(t_ctrl)
    for s in sounds:
        sfx_dip = np.minimum(sfx_dip, np.where((t_ctrl >= s.t - 0.02) & (t_ctrl <= s.t + 0.25), -3.0, 0.0))

    if music is not None and music.path.exists() and total > 0.2:
        track = decode(music.path, sr=SR, channels=2)
        track_len = len(track) / SR
        start, how = music_positions(music, track_len, total)
        loop = (music.loop_start, music.loop_end) if music.loop_start is not None and music.loop_end else None
        y, loops = assemble(track, SR, start, total, loop)
        measured = music.loudness_db if music.loudness_db is not None else loud_part_db(track, SR)
        gain_db = music.level_db - measured + music.gain_db
        duck = duck_curve(total, speech, music.duck_db)
        env_db = gain_db + duck + sfx_dip
        env = db(env_db)
        # fades (equal power)
        if music.fade_in > 0:
            env *= np.sin(0.5 * np.pi * np.clip(t_ctrl / music.fade_in, 0, 1))
        if music.fade_out > 0:
            env *= np.sin(0.5 * np.pi * np.clip((total - t_ctrl) / music.fade_out, 0, 1))
        g = np.interp(np.arange(n) / SR, t_ctrl, env).astype(np.float32)[:, None]
        bed += y[:n] * g
        sync_pos = None
        if music.sync_out is not None:
            sync_pos = start + music.sync_out
            if loop and sync_pos >= loop[1]:
                sync_pos = loop[0] + (sync_pos - loop[0]) % (loop[1] - loop[0])
        on_beat = None
        if sync_pos is not None and music.bpm:
            beat = 60 / music.bpm
            ph = (sync_pos - music.beat_offset) % beat
            on_beat = round(min(ph, beat - ph), 3)
        rep["music"] = {"start_in_track": round(start, 3), "sync": how, "loops": loops,
                        "gain_db": round(gain_db, 1), "measured_db": round(measured, 1),
                        "duck_db": music.duck_db, "ducked_s": round(float(np.sum(duck < -1)) / CTRL, 2),
                        "sync_out": music.sync_out, "track_pos_at_sync": round(sync_pos, 3) if sync_pos else None,
                        "beat_error_s": on_beat}

    placed: list[tuple[float, float]] = []
    for s in sorted(sounds, key=lambda s: s.t):
        if not s.path.exists() or s.volume <= 0 or s.t >= total - 0.03:
            continue
        y = load_sound(s.path)
        vol = s.volume * db(s.gain_db)
        stacked = any(a <= s.t < a + 0.3 for a, _ in placed)
        if stacked:
            vol *= db(-6)
        i = max(0, int(round(s.t * SR)))
        k = min(len(y), n - i)
        if k <= 0:
            continue
        bed[i:i + k] += y[:k] * vol
        placed.append((s.t, s.t + k / SR))
        rep["sounds"].append({"t": round(s.t, 3), "category": s.category, "volume": round(vol, 3),
                              "attenuated": stacked, "file": s.path.name})

    peak = float(np.max(np.abs(bed))) if n else 0.0
    ceiling = db(-3)
    if peak > ceiling:   # soft knee: tanh above the ceiling, keeps transients readable
        bed = (np.tanh(bed / ceiling) * ceiling).astype(np.float32)
    rep["peak_db"] = round(20 * math.log10(peak), 1) if peak > 0 else None
    return BedResult(bed, rep)


def write_wav(path: Path, y: np.ndarray, sr: int = SR) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = (np.clip(y, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(y.shape[1])
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())
