"""Audio library: music tracks and sound effects with license, provenance and analysis.

- Built-in assets (origin "builtin", CC0): the six procedural tracks of ``music_synth`` (generated on
  first use into ``data/audio/builtin``) and the synthesised SFX of ``effects`` (``assets/sfx``).
- Imported assets (origin "user"): any audio FFmpeg can decode. Import requires a declared license, the
  confirmation that you hold the rights, an attribution for CC BY and a source for third-party licenses.
  Files are stored under ``data/audio/user`` with a random name and served only through the API.
- Analysis on import: duration, loudness (RMS dBFS of the loud part), tempo and beat phase (onset
  autocorrelation), the "drop" (largest bar-to-bar loudness rise) and a loop region on bar lines.
  Tempo/drop of imported tracks are estimates; the built-in ones are exact (they come from the score).
"""

from __future__ import annotations

import logging
import secrets
import subprocess
import threading
from pathlib import Path

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.core.config import get_settings
from backend.core.exceptions import ValidationFailed
from backend.editing import effects, music_synth
from backend.editing.plan import MUSIC_MOODS, SFX_CATEGORIES
from backend.models.entities import AudioAsset

log = logging.getLogger(__name__)

LICENSES = {
    "cc0": "CC0 / pubblico dominio",
    "cc_by": "Creative Commons BY (attribuzione obbligatoria)",
    "royalty_free": "Royalty-free con licenza (es. libreria di stock)",
    "licensed": "Licenza acquistata / concessa per iscritto",
    "own_work": "Opera mia (composta/registrata da me)",
}
BUILTIN_LICENSE = "cc0"
AUDIO_EXT = {".wav", ".mp3", ".ogg", ".flac", ".m4a", ".aac", ".opus"}
_lock = threading.Lock()


def audio_dir() -> Path:
    return get_settings().data_dir / "audio"


# ------------------------------------------------------------------ decoding & analysis
def decode(path: Path, sr: int = 48000, channels: int = 2, max_s: float | None = None) -> np.ndarray:
    """Float32 (n, channels) through FFmpeg (any format)."""
    cmd = [get_settings().ffmpeg_bin, "-hide_banner", "-loglevel", "error", "-nostdin", "-i", str(path)]
    if max_s:
        cmd += ["-t", f"{max_s:.3f}"]
    cmd += ["-vn", "-ac", str(channels), "-ar", str(sr), "-f", "f32le", "pipe:1"]
    proc = subprocess.run(cmd, capture_output=True, timeout=300)
    if proc.returncode != 0:
        raise ValidationFailed(f"File audio non leggibile: {proc.stderr.decode(errors='ignore')[-200:]}",
                               code="invalid_audio")
    y = np.frombuffer(proc.stdout, np.float32)
    return y[: len(y) // channels * channels].reshape(-1, channels).copy()


def rms_db(y: np.ndarray) -> float:
    v = float(np.sqrt(np.mean(np.square(y, dtype=np.float64)))) if len(y) else 0.0
    return 20 * np.log10(v) if v > 1e-9 else -120.0


def loud_part_db(y: np.ndarray, sr: int) -> float:
    """RMS of the loud part (75th percentile of 0.4 s windows): the level the track 'sits' at."""
    mono = y.mean(axis=1) if y.ndim == 2 else y
    hop = int(0.4 * sr)
    if len(mono) < hop:
        return rms_db(mono)
    w = mono[: len(mono) // hop * hop].reshape(-1, hop)
    db = 10 * np.log10(np.mean(w.astype(np.float64) ** 2, axis=1) + 1e-12)
    return float(np.percentile(db, 75))


def tempo(y: np.ndarray, sr: int) -> tuple[float | None, float]:
    """(BPM, first beat s) from the onset envelope: autocorrelation over 70-180 BPM with a mild prior
    toward 120, then the phase whose beats collect the most onset energy."""
    mono = y.mean(axis=1) if y.ndim == 2 else y
    hop = 512
    n = len(mono) // hop
    if n < 200:
        return None, 0.0
    frames = mono[: n * hop].reshape(n, hop).astype(np.float64)
    # spectral-flux-like onset: positive change of log energy in 3 bands
    spec = np.abs(np.fft.rfft(frames * np.hanning(hop), axis=1))
    bands = [spec[:, 1:8].sum(1), spec[:, 8:40].sum(1), spec[:, 40:].sum(1)]
    onset = sum(np.maximum(0, np.diff(np.log1p(b * 10), prepend=np.log1p(b[0] * 10))) for b in bands)
    onset = onset - np.convolve(onset, np.ones(16) / 16, mode="same")
    onset = np.maximum(onset, 0)
    if onset.max() <= 0:
        return None, 0.0
    fps = sr / hop
    ac = np.correlate(onset, onset, mode="full")[len(onset) - 1:]
    best, best_s = None, -1.0
    for bpm in np.arange(70, 180.01, 0.25):
        lag = 60 * fps / bpm
        i = int(lag)
        frac = lag - i
        if i + 1 >= len(ac):
            continue
        v = ac[i] * (1 - frac) + ac[i + 1] * frac
        for mult in (2, 4):  # beats further away reinforce the right period
            j = lag * mult
            k = int(j)
            if k + 1 < len(ac):
                v += 0.5 * (ac[k] * (1 - (j - k)) + ac[k + 1] * (j - k))
        v *= np.exp(-0.5 * (np.log2(bpm / 120) / 0.9) ** 2)
        if v > best_s:
            best, best_s = bpm, v
    if best is None:
        return None, 0.0
    # refine tempo and phase together with a comb over the whole track (a 0.2 % tempo error drifts by a
    # tenth of a second over a minute, so the coarse autocorrelation peak is not enough for beat sync)
    L = len(onset)
    best_score, phase = -1.0, 0.0
    for bpm in np.arange(best - 1.0, best + 1.0001, 0.02):
        period = 60 * fps / bpm
        k = np.arange(0, int((L - 1) / period))
        if len(k) < 4:
            continue
        for p in np.arange(0, period, 0.5):
            pos = p + k * period
            i = pos.astype(int)
            f = pos - i
            ok = i + 1 < L
            sc = float((onset[i[ok]] * (1 - f[ok]) + onset[i[ok] + 1] * f[ok]).sum())
            if sc > best_score:
                best_score, best, phase = sc, float(bpm), p / fps
    return round(float(best), 2), round(phase, 3)


def drop_and_loop(y: np.ndarray, sr: int, bpm: float | None, offset: float, duration: float
                  ) -> tuple[float | None, float | None, float | None]:
    """Drop = largest loudness rise from one bar to the next (> 4 dB, after the first 2 bars);
    loop region = drop (or first quarter) → 2 bars before the end, on bar lines."""
    if not bpm:
        return None, None, None
    bar = 4 * 60 / bpm
    nbars = int((duration - offset) / bar)
    if nbars < 6:
        return None, None, None
    mono = y.mean(axis=1) if y.ndim == 2 else y
    db = [rms_db(mono[int((offset + b * bar) * sr): int((offset + (b + 1) * bar) * sr)]) for b in range(nbars)]
    rises = [(db[b] - max(db[b - 1], db[b - 2]), b) for b in range(2, nbars)]
    best = max(rises, default=(0, 0))
    drop = round(offset + best[1] * bar, 3) if best[0] > 3 else None
    start_bar = best[1] if drop is not None else max(1, nbars // 4)
    end_bar = max(start_bar + 2, nbars - 2)
    return drop, round(offset + start_bar * bar, 3), round(offset + end_bar * bar, 3)


def analyse_file(path: Path) -> dict:
    sr = 22050
    y = decode(path, sr=sr, channels=1)
    duration = len(y) / sr
    if duration < 0.05:
        raise ValidationFailed("Il file audio è vuoto o troppo corto", code="invalid_audio")
    loud = loud_part_db(y, sr)
    bpm, off = tempo(y, sr) if duration >= 8 else (None, 0.0)
    drop, ls, le = drop_and_loop(y, sr, bpm, off, duration)
    mono = y[:, 0]
    energy = float(np.clip((loud + 30) / 22, 0, 1))
    return {"duration": round(duration, 3), "loudness_db": round(loud, 1), "bpm": bpm, "beat_offset": off,
            "drop_time": drop, "loop_start": ls, "loop_end": le, "energy": round(energy, 2),
            "peak_db": round(20 * np.log10(float(np.max(np.abs(mono))) + 1e-9), 1)}


# ------------------------------------------------------------------ built-in assets
def _write_flac(path: Path, y: np.ndarray, sr: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = (np.clip(y, -1, 1) * 32767).astype("<i2").tobytes()
    tmp = path.with_suffix(".tmp.flac")
    subprocess.run([get_settings().ffmpeg_bin, "-hide_banner", "-loglevel", "error", "-y", "-f", "s16le",
                    "-ar", str(sr), "-ac", str(y.shape[1]), "-i", "pipe:0", str(tmp)], input=pcm, check=True,
                   timeout=300)
    tmp.replace(path)


def ensure_builtin(db: Session) -> None:
    """Register (and generate when missing) the built-in tracks and sound effects. Idempotent."""
    with _lock:
        rows = {(a.kind, a.category): a for a in db.scalars(select(AudioAsset).where(AudioAsset.origin == "builtin"))}
        changed = False
        for mood in MUSIC_MOODS:
            path = audio_dir() / "builtin" / f"{mood}.flac"
            ti = music_synth.info(music_synth.SPECS[mood])
            if not path.exists():
                log.info("Generating built-in music track: %s", mood)
                y, ti = music_synth.render(mood)
                _write_flac(path, y, music_synth.SR)
            row = rows.get(("music", mood))
            if row is None:
                row = AudioAsset(kind="music", category=mood, origin="builtin", license=BUILTIN_LICENSE)
                db.add(row)
            row.title = f"{ti.title} ({mood})"
            row.path = str(path)
            row.original_name = path.name
            row.duration, row.bpm, row.beat_offset = ti.duration, ti.bpm, ti.beat_offset
            row.drop_time, row.loop_start, row.loop_end = ti.drop_time, ti.loop_start, ti.loop_end
            if row.loudness_db is None or row.loudness_db == -13.0 or row.file_size != path.stat().st_size:
                # measured on the file itself (the engine sets the music level from this)
                row.loudness_db = round(loud_part_db(decode(path, sr=22050, channels=1), 22050), 1)
            row.energy = round(min(1.0, (ti.bpm - 70) / 80), 2)
            row.file_size = path.stat().st_size
            row.attribution = "CLIPNOVA (traccia originale procedurale)"
            row.notes = "Generata da backend/editing/music_synth.py, CC0"
            changed = True
        for cat in SFX_CATEGORIES:
            path = effects.BUILTIN_DIR / f"{cat}.wav"
            if not path.exists():
                effects.generate_builtin()
            row = rows.get(("sfx", cat))
            if row is None:
                row = AudioAsset(kind="sfx", category=cat, origin="builtin", license=BUILTIN_LICENSE,
                                 title=f"{cat} (CLIPNOVA)", path=str(path), original_name=path.name,
                                 duration=effects.DURATION.get(cat, 0.5), loudness_db=-6.0,
                                 attribution="CLIPNOVA (sintesi originale)", notes=effects.DESCRIPTION.get(cat, ""))
                db.add(row)
                changed = True
            if row.path != str(path):
                row.path = str(path)
                changed = True
            if path.exists() and row.file_size != path.stat().st_size:
                row.file_size = path.stat().st_size
                changed = True
        if changed:
            db.commit()


def as_dict(a: AudioAsset) -> dict:
    return {"id": a.id, "kind": a.kind, "category": a.category, "title": a.title, "origin": a.origin,
            "original_name": a.original_name, "file_size": a.file_size, "duration": a.duration, "bpm": a.bpm,
            "beat_offset": a.beat_offset, "drop_time": a.drop_time, "loop_start": a.loop_start,
            "loop_end": a.loop_end, "loudness_db": a.loudness_db, "energy": a.energy, "gain_db": a.gain_db,
            "license": a.license, "license_label": LICENSES.get(a.license, a.license), "attribution": a.attribution,
            "source_url": a.source_url, "notes": a.notes, "enabled": a.enabled, "path": a.path,
            "available": Path(a.path).exists(), "url": f"/api/audio/{a.id}/file",
            "created_at": a.created_at.isoformat() + "Z" if a.created_at else None}


def catalog(kind: str | None = None, db: Session | None = None) -> list[dict]:
    """Usable assets (enabled, licensed, file present) as plain dicts."""
    from backend.database.session import session_scope

    def run(s: Session) -> list[dict]:
        ensure_builtin(s)
        stmt = select(AudioAsset).where(AudioAsset.enabled.is_(True))
        if kind:
            stmt = stmt.where(AudioAsset.kind == kind)
        return [as_dict(a) for a in s.scalars(stmt.order_by(AudioAsset.created_at)) if a.license and
                Path(a.path).exists()]

    if db is not None:
        return run(db)
    with session_scope() as s:
        return run(s)


def resolve_sfx(category: str, seed: int = 0, sounds: list[dict] | None = None) -> tuple[Path, float] | None:
    """(file, gain dB) for a sound category: your enabled licensed files first (variety by seed), then the
    legacy data/sfx/<category>/ folder, then the built-in sound."""
    pool = [s for s in (sounds or []) if s["category"] == category and s["origin"] == "user"]
    if pool:
        pick = sorted(pool, key=lambda s: s["id"])[seed % len(pool)]
        return Path(pick["path"]), float(pick.get("gain_db") or 0.0)
    p = effects.sfx_file(category)
    if p is None:
        return None
    gain = next((float(s.get("gain_db") or 0) for s in (sounds or []) if s["category"] == category
                 and s["origin"] == "builtin"), 0.0)
    return p, gain


# ------------------------------------------------------------------ import
def import_file(db: Session, data: bytes, filename: str, *, kind: str, category: str, title: str, license: str,
                attribution: str = "", source_url: str = "", notes: str = "", rights_confirmed: bool = False
                ) -> AudioAsset:
    s = get_settings()
    if kind not in ("music", "sfx"):
        raise ValidationFailed("Tipo non valido: music o sfx", code="invalid_kind")
    valid_cat = MUSIC_MOODS if kind == "music" else SFX_CATEGORIES
    if category not in valid_cat:
        raise ValidationFailed(f"Categoria non valida per {kind}: {', '.join(valid_cat)}", code="invalid_category")
    if license not in LICENSES:
        raise ValidationFailed("Indica la licenza del file (CC0, CC BY, royalty-free, licenza, opera tua)",
                               code="license_required")
    if not rights_confirmed:
        raise ValidationFailed("Conferma di avere i diritti per usare questo file nei tuoi video",
                               code="rights_not_confirmed")
    if license == "cc_by" and len(attribution.strip()) < 3:
        raise ValidationFailed("CC BY richiede l'attribuzione (autore e titolo)", code="attribution_required")
    if license in ("cc_by", "royalty_free", "licensed") and len((source_url or notes).strip()) < 4:
        raise ValidationFailed("Indica la fonte (URL o riferimento della licenza)", code="source_required")
    ext = Path(filename or "").suffix.lower()
    if ext not in AUDIO_EXT:
        raise ValidationFailed(f"Formato non supportato ({ext or '?'}): {', '.join(sorted(AUDIO_EXT))}",
                               code="invalid_audio")
    if len(data) > s.audio_import_max_mb * 1024 * 1024:
        raise ValidationFailed(f"File troppo grande (max {s.audio_import_max_mb:.0f} MB)", code="too_large")
    dest_dir = audio_dir() / "user"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{secrets.token_hex(12)}{ext}"
    dest.write_bytes(data)
    try:
        info = analyse_file(dest)
        if info["duration"] > s.audio_import_max_s:
            raise ValidationFailed(f"Audio troppo lungo (max {s.audio_import_max_s / 60:.0f} min)", code="too_long")
        if kind == "sfx" and info["duration"] > 12:
            raise ValidationFailed("Un effetto sonoro deve durare al massimo 12 s", code="too_long")
        if kind == "music" and info["duration"] < 8:
            raise ValidationFailed("Una traccia musicale deve durare almeno 8 s", code="too_short")
    except Exception:
        dest.unlink(missing_ok=True)
        raise
    if kind == "sfx":
        info.update({"bpm": None, "drop_time": None, "loop_start": None, "loop_end": None})
    a = AudioAsset(kind=kind, category=category, title=(title or Path(filename).stem)[:160], origin="user",
                   path=str(dest), original_name=Path(filename).name[:255], file_size=len(data),
                   duration=info["duration"], bpm=info["bpm"], beat_offset=info["beat_offset"],
                   drop_time=info["drop_time"], loop_start=info["loop_start"], loop_end=info["loop_end"],
                   loudness_db=info["loudness_db"], energy=info["energy"], license=license,
                   attribution=attribution.strip()[:500], source_url=source_url.strip()[:500],
                   notes=notes.strip()[:1000], enabled=True)
    db.add(a)
    db.commit()
    return a


def delete_asset(db: Session, a: AudioAsset) -> None:
    if a.origin == "builtin":
        raise ValidationFailed("Gli asset di serie non si eliminano: puoi disattivarli", code="builtin")
    root = (audio_dir() / "user").resolve()
    p = Path(a.path).resolve()
    if p.parent == root:
        p.unlink(missing_ok=True)
    db.delete(a)
    db.commit()
