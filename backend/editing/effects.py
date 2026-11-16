"""Sound effects library + FFmpeg mixing.

Only audio you are allowed to use:
- built-in: synthesised by ``generate_builtin`` (pure numpy, no samples from anyone else; released by
  CLIPNOVA as CC0) into ``assets/sfx/<category>.wav``;
- your own: files you have the rights to, placed in ``data/sfx/<category>/`` (wav/mp3/ogg/flac/m4a).
  They take precedence over the built-in ones (first file in name order).
"""

from __future__ import annotations

import logging
import math
import wave
from pathlib import Path

import numpy as np

from backend.core.config import PROJECT_ROOT, get_settings

log = logging.getLogger(__name__)

CATEGORIES = ("whoosh", "impact", "bass_drop", "riser", "explosion", "hit", "transition", "ui", "cinematic", "gaming",
              "pop", "ding")
BUILTIN_DIR = PROJECT_ROOT / "assets" / "sfx"
USER_EXT = {".wav", ".mp3", ".ogg", ".flac", ".m4a"}
SR = 48000
DURATION = {"whoosh": 0.5, "impact": 0.75, "pop": 0.12, "riser": 1.3, "ding": 1.0, "bass_drop": 1.6,
            "explosion": 1.8, "hit": 0.35, "transition": 0.6, "ui": 0.18, "cinematic": 2.2, "gaming": 0.45}
DESCRIPTION = {
    "whoosh": "passaggio d'aria, per zoom e movimenti", "impact": "colpo sordo, per zoom rapidi e impatti",
    "bass_drop": "caduta di basso sub, per il culmine a tempo con la musica",
    "riser": "salita di tensione, prima di un culmine", "explosion": "esplosione con coda, per lampi ed esplosioni",
    "hit": "colpo secco e corto, per eliminazioni e fermo immagine",
    "transition": "swish digitale breve, per i tagli", "ui": "click/bip d'interfaccia, per testi e grafiche",
    "cinematic": "boom cinematico con riverbero, per momenti epici",
    "gaming": "arpeggio 8-bit, per gag e momenti da videogioco",
    "pop": "pop breve, per momenti divertenti", "ding": "campanello, per un risultato o una sorpresa"}


def user_dir() -> Path:
    return get_settings().data_dir / "sfx"


# ------------------------------------------------------------------ synthesis (deterministic)
def _lowpass(x: np.ndarray, n: int) -> np.ndarray:
    if n <= 1:
        return x
    k = np.ones(n) / n
    return np.convolve(x, k, mode="same")


def _synth(category: str) -> np.ndarray:
    legacy = {"whoosh": 0, "impact": 1, "pop": 2, "riser": 3, "ding": 4}   # 1.2 seeds: same files as before
    rng = np.random.default_rng(20261116 + legacy.get(category, 100 + CATEGORIES.index(category)))
    n = int(DURATION[category] * SR)
    t = np.arange(n) / SR
    if category == "whoosh":
        noise = rng.standard_normal(n)
        low, high = _lowpass(noise, 60), noise - _lowpass(noise, 6)
        sweep = np.clip(t / t[-1], 0, 1)
        body = low * (1 - sweep) * 6 + high * sweep * 0.6
        env = np.sin(np.pi * np.clip(t / t[-1], 0, 1)) ** 2
        y = _lowpass(body, 3) * env
    elif category == "impact":
        f = 38 + 50 * np.exp(-t * 18)                        # pitch drop
        phase = 2 * np.pi * np.cumsum(f) / SR
        thump = np.sin(phase) * np.exp(-t * 6.5)
        click = rng.standard_normal(n) * np.exp(-t * 180) * 0.6
        rumble = _lowpass(rng.standard_normal(n), 120) * np.exp(-t * 5) * 4
        y = np.tanh(1.8 * (thump + click + rumble))
    elif category == "pop":
        f = 900 * np.exp(-t * 22) + 220
        y = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 45) * np.clip(t * SR / 40, 0, 1)
    elif category == "riser":
        f = 180 * (1 + 6 * (t / t[-1]) ** 2)
        tone = np.sin(2 * np.pi * np.cumsum(f) / SR) * 0.5
        noise = (rng.standard_normal(n) - _lowpass(rng.standard_normal(n), 8)) * 0.35
        env = (t / t[-1]) ** 2.2
        y = (tone + noise * (t / t[-1])) * env
        y[-int(0.02 * SR):] *= np.linspace(1, 0, int(0.02 * SR))
    elif category == "bass_drop":
        f = 110 * np.exp(-t * 2.6) + 32                       # long sub sweep down
        y = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 1.6)
        y = np.tanh(2.2 * (y + 0.25 * np.sin(4 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 3)))
        y *= np.clip(t * SR / 200, 0, 1)
    elif category == "explosion":
        noise = rng.standard_normal(n)
        body = _lowpass(noise, 40) * 6 * np.exp(-t * 2.2)        # rumble
        crack = (noise - _lowpass(noise, 4)) * np.exp(-t * 30) * 1.5
        thump = np.sin(2 * np.pi * np.cumsum(30 + 60 * np.exp(-t * 12)) / SR) * np.exp(-t * 4)
        y = np.tanh(1.5 * (body + crack + thump))
    elif category == "hit":
        f = 160 * np.exp(-t * 30) + 70
        y = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 16)
        y += (rng.standard_normal(n) - _lowpass(rng.standard_normal(n), 3)) * np.exp(-t * 90) * 0.8
        y = np.tanh(2.0 * y)
    elif category == "transition":
        noise = rng.standard_normal(n)
        sweep = t / t[-1]
        hp = noise - _lowpass(noise, 3)
        y = (_lowpass(noise, 12) * (1 - sweep) * 3 + hp * sweep) * np.sin(np.pi * sweep) ** 1.5
        y += 0.25 * np.sin(2 * np.pi * np.cumsum(400 + 2400 * sweep ** 2) / SR) * np.sin(np.pi * sweep) ** 2
    elif category == "ui":
        y = np.zeros(n)
        for k, (f0, st) in enumerate(((1760.0, 0.0), (2349.3, 0.06))):
            i0 = int(st * SR)
            tt = t[: n - i0]
            y[i0:] += np.sign(np.sin(2 * np.pi * f0 * tt)) * 0.3 * np.exp(-tt * 40) * np.clip(tt * SR / 30, 0, 1)
        y = _lowpass(y, 3)
    elif category == "cinematic":
        noise = rng.standard_normal(n)
        boom = np.sin(2 * np.pi * np.cumsum(45 + 40 * np.exp(-t * 6)) / SR) * np.exp(-t * 1.8)
        tail = _lowpass(noise, 25) * np.exp(-t * 1.4) * 2.5               # reverb-like tail
        shimmer = sum(np.sin(2 * np.pi * f * t) * 0.05 for f in (220, 330, 440)) * np.exp(-t * 1.2)
        y = np.tanh(1.6 * (boom + tail + shimmer))
    elif category == "gaming":
        y = np.zeros(n)
        notes = (523.25, 659.25, 783.99, 1046.5)                          # C major arpeggio, square wave
        step = int(0.09 * SR)
        for k, f0 in enumerate(notes):
            i0 = k * step
            if i0 >= n:
                break
            tt = np.arange(min(step + int(0.05 * SR), n - i0)) / SR
            y[i0:i0 + len(tt)] += np.sign(np.sin(2 * np.pi * f0 * tt)) * 0.35 * np.exp(-tt * 12)
    elif category == "ding":
        y = sum(a * np.sin(2 * np.pi * f * t) * np.exp(-t * d)
                for f, a, d in ((1318.5, 1.0, 4.5), (2637.0, 0.35, 7), (3951.0, 0.15, 10)))
        y *= np.clip(t * SR / 60, 0, 1)
    else:
        raise ValueError(category)
    y = y / (np.max(np.abs(y)) or 1.0) * 10 ** (-6 / 20)   # peak −6 dBFS
    return y.astype(np.float32)


def write_wav(path: Path, y: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = (np.clip(y, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


def generate_builtin(out_dir: Path = BUILTIN_DIR, force: bool = False) -> list[Path]:
    paths = []
    for c in CATEGORIES:
        p = out_dir / f"{c}.wav"
        if force or not p.exists():
            write_wav(p, _synth(c))
        paths.append(p)
    return paths


def sfx_file(category: str) -> Path | None:
    """User file for the category if present, else the built-in one (generated on first use)."""
    if category not in CATEGORIES:
        return None
    d = user_dir() / category
    if d.is_dir():
        for p in sorted(d.iterdir()):
            if p.is_file() and p.suffix.lower() in USER_EXT and not p.is_symlink():
                return p
    p = BUILTIN_DIR / f"{category}.wav"
    if not p.exists():
        try:
            generate_builtin()
        except OSError as e:
            log.warning("Cannot write built-in SFX: %s", e)
            return None
    return p if p.exists() else None


def library() -> list[dict]:
    out = []
    for c in CATEGORIES:
        p = sfx_file(c)
        out.append({"category": c, "available": p is not None, "description": DESCRIPTION.get(c, ""),
                    "source": "user" if p and p.parent.name == c and p.parent.parent == user_dir() else "builtin",
                    "name": p.name if p else None})
    return out


# ------------------------------------------------------------------ FFmpeg mixing
def mix_filters(cues: list[tuple[float, str, float]], first_input: int, main_label: str, out_label: str,
                total: float) -> tuple[list[str], list[str]]:
    """cues: (output time s, category, volume 0..1). Returns (extra input args, filter_complex parts).

    Every sound is a separate ``-i`` input (no paths inside the filter string), delayed to its time
    and mixed over the main track without renormalising it; a limiter guards against clipping."""
    inputs: list[str] = []
    parts: list[str] = []
    labels: list[str] = []
    k = first_input
    for t, cat, vol in cues:
        f = sfx_file(cat)
        if f is None or t >= total - 0.05 or vol <= 0:
            continue
        ms = max(0, int(round(t * 1000)))
        inputs += ["-i", str(f)]
        lab = f"sfx{len(labels)}"
        parts.append(f"[{k}:a]aresample=48000,aformat=channel_layouts=stereo,volume={vol:.3f},"
                     f"adelay={ms}|{ms}[{lab}]")
        labels.append(lab)
        k += 1
    if not labels:
        return [], [f"[{main_label}]anull[{out_label}]"]
    mix_in = "".join(f"[{x}]" for x in [main_label, *labels])
    parts.append(f"{mix_in}amix=inputs={len(labels) + 1}:normalize=0:duration=first:dropout_transition=0,"
                 f"alimiter=limit=0.95:level=disabled,atrim=0:{total:.3f}[{out_label}]")
    return inputs, parts


def db_peak(x: np.ndarray) -> float:
    m = float(np.max(np.abs(x))) if len(x) else 0.0
    return 20 * math.log10(m) if m > 0 else -120.0
