"""Built-in music: original tracks synthesised from scratch (numpy), released by CLIPNOVA as CC0.

Six moods — cinematic, dynamic, electronic, chill, dramatic, gaming — each with its own tempo, key,
chord progression and instruments (kick/snare/hats, sub and saw bass, detuned pads, plucked arpeggios,
square leads, taiko hits, string-like drones). Every track has the same arrangement on a bar grid,
which is what makes beat sync exact:

    intro 4 bars · build 4 (snare roll + riser) · DROP 8 · break 4 · main 8 · outro 4

``TrackInfo`` gives the BPM, the first downbeat (0.0), the drop time and the loop region (drop → end of
main), so the audio engine can land the drop on the clip's climax and loop seamlessly on bar lines.

These are functional, deterministic beds — not a substitute for produced music: import licensed tracks
in the audio library and the Director will prefer them.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np

SR = 44100
BARS = {"intro": 4, "build": 4, "drop": 8, "break": 4, "main": 8, "outro": 4}


@dataclass(frozen=True)
class Spec:
    mood: str
    title: str
    bpm: float
    root: int                 # MIDI note of the key root
    minor: bool
    progression: tuple[int, ...]   # scale degrees (0-based), one chord per bar
    drums: str                # four | half | trap | soft | taiko | none
    lead: str                 # square | pluck | piano | strings | none
    swing: float = 0.0


SPECS = {
    "cinematic": Spec("cinematic", "Horizon Line", 90, 50, True, (0, 5, 2, 6), "taiko", "strings"),
    "dynamic": Spec("dynamic", "Full Throttle", 128, 52, True, (0, 5, 3, 4), "four", "pluck"),
    "electronic": Spec("electronic", "Neon Circuit", 124, 45, True, (0, 3, 5, 4), "four", "pluck"),
    "chill": Spec("chill", "Slow Afternoon", 84, 53, False, (0, 5, 3, 4), "soft", "piano", swing=0.12),
    "dramatic": Spec("dramatic", "Last Stand", 80, 48, True, (0, 6, 5, 4), "taiko", "strings"),
    "gaming": Spec("gaming", "Pixel Rush", 140, 57, True, (0, 5, 6, 4), "trap", "square"),
}


@dataclass
class TrackInfo:
    mood: str
    title: str
    bpm: float
    duration: float
    beat_offset: float
    drop_time: float
    loop_start: float
    loop_end: float
    bar_s: float

    def as_dict(self) -> dict:
        return asdict(self)


def _ma(x: np.ndarray, n: int) -> np.ndarray:
    """Moving-average low-pass (cumulative sum: O(N))."""
    if n <= 1:
        return x
    c = np.cumsum(np.concatenate([np.zeros(n), x]))
    return (c[n:] - c[:-n]) / n


def _hz(midi: float) -> float:
    return 440.0 * 2 ** ((midi - 69) / 12)


def _scale(minor: bool) -> list[int]:
    return [0, 2, 3, 5, 7, 8, 10] if minor else [0, 2, 4, 5, 7, 9, 11]


def _chord(spec: Spec, degree: int) -> list[int]:
    sc = _scale(spec.minor)
    return [spec.root + sc[(degree + k) % 7] + 12 * ((degree + k) // 7) for k in (0, 2, 4)]


def _saw(f: float, n: int, phase: float = 0.0) -> np.ndarray:
    t = np.arange(n) / SR
    x = (t * f + phase) % 1.0
    return 2 * x - 1


def _adsr(n: int, a: float, r: float) -> np.ndarray:
    env = np.ones(n)
    na, nr = min(n, int(a * SR)), min(n, int(r * SR))
    if na:
        env[:na] = np.linspace(0, 1, na)
    if nr:
        env[n - nr:] *= np.linspace(1, 0, nr)
    return env


class _Mix:
    def __init__(self, n: int) -> None:
        self.L = np.zeros(n)
        self.R = np.zeros(n)

    def add(self, i: int, y: np.ndarray, gain: float = 1.0, pan: float = 0.0) -> None:
        if i >= len(self.L) or i < 0:
            return
        y = y[: len(self.L) - i] * gain
        self.L[i:i + len(y)] += y * (1 - max(0.0, pan))
        self.R[i:i + len(y)] += y * (1 + min(0.0, pan))


# ------------------------------------------------------------------ instruments
def kick(rng) -> np.ndarray:
    n = int(0.38 * SR)
    t = np.arange(n) / SR
    f = 45 + 95 * np.exp(-t * 28)
    return np.tanh(1.6 * np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 7.5))


def snare(rng) -> np.ndarray:
    n = int(0.24 * SR)
    t = np.arange(n) / SR
    noise = rng.standard_normal(n)
    body = (noise - _ma(noise, 6)) * np.exp(-t * 20) * 0.7
    tone = np.sin(2 * np.pi * 190 * t) * np.exp(-t * 30) * 0.5
    return body + tone


def hat(rng, open_: bool = False) -> np.ndarray:
    n = int((0.25 if open_ else 0.06) * SR)
    t = np.arange(n) / SR
    noise = rng.standard_normal(n)
    hp = noise - _ma(noise, 3)
    return hp * np.exp(-t * (14 if open_ else 70)) * 0.35


def taiko(rng) -> np.ndarray:
    n = int(0.9 * SR)
    t = np.arange(n) / SR
    f = 60 + 50 * np.exp(-t * 14)
    y = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 4.5)
    y += _ma(rng.standard_normal(n), 30) * np.exp(-t * 9) * 3
    return np.tanh(1.4 * y)


def crash(rng) -> np.ndarray:
    n = int(2.2 * SR)
    t = np.arange(n) / SR
    noise = rng.standard_normal(n)
    return (noise - _ma(noise, 2)) * np.exp(-t * 2.2) * 0.25


def pluck(f: float, dur: float) -> np.ndarray:
    n = int(dur * SR)
    t = np.arange(n) / SR
    y = _saw(f, n) * 0.6 + _saw(f * 1.006, n, 0.3) * 0.4
    y = _ma(y, 6) * np.exp(-t * 9)
    return y * _adsr(n, 0.004, 0.02)


def square(f: float, dur: float) -> np.ndarray:
    n = int(dur * SR)
    t = np.arange(n) / SR
    y = np.sign(np.sin(2 * np.pi * f * t)) * 0.5 + np.sign(np.sin(2 * np.pi * f * 2 * t)) * 0.1
    return _ma(y, 4) * np.exp(-t * 3) * _adsr(n, 0.004, 0.03)


def piano(f: float, dur: float) -> np.ndarray:
    n = int(dur * SR)
    t = np.arange(n) / SR
    y = sum(a * np.sin(2 * np.pi * f * k * t) * np.exp(-t * (2.5 + k)) for k, a in ((1, 1.0), (2, 0.35), (3, 0.12)))
    return y * _adsr(n, 0.005, 0.08)


def pad(freqs: list[float], dur: float, bright: int = 40) -> tuple[np.ndarray, np.ndarray]:
    n = int(dur * SR)
    L = np.zeros(n)
    R = np.zeros(n)
    for f in freqs:
        L += _saw(f * 0.997, n) + _saw(f * 1.004, n, 0.5)
        R += _saw(f * 1.003, n, 0.25) + _saw(f * 0.995, n, 0.75)
    env = _adsr(n, min(0.6, dur * 0.3), min(0.5, dur * 0.25))
    return _ma(L, bright) * env, _ma(R, bright) * env


def bass(f: float, dur: float, sub: bool = True) -> np.ndarray:
    n = int(dur * SR)
    t = np.arange(n) / SR
    y = np.sin(2 * np.pi * f * t) * 0.8 + (_ma(_saw(f, n), 20) * 0.35 if not sub else 0)
    return np.tanh(1.3 * y) * _adsr(n, 0.005, 0.05)


def riser(rng, dur: float) -> np.ndarray:
    n = int(dur * SR)
    t = np.arange(n) / SR
    x = t / dur
    noise = rng.standard_normal(n)
    y = (noise - _ma(noise, 3)) * x ** 2 * 0.35
    y += np.sin(2 * np.pi * np.cumsum(200 + 1400 * x ** 2) / SR) * x ** 2.5 * 0.15
    return y


# ------------------------------------------------------------------ arrangement
def info(spec: Spec) -> TrackInfo:
    bar = 4 * 60.0 / spec.bpm
    total_bars = sum(BARS.values())
    drop = (BARS["intro"] + BARS["build"]) * bar
    loop_end = (total_bars - BARS["outro"]) * bar
    return TrackInfo(spec.mood, spec.title, spec.bpm, round(total_bars * bar, 4), 0.0, round(drop, 4),
                     round(drop, 4), round(loop_end, 4), round(bar, 6))


def render(mood: str) -> tuple[np.ndarray, TrackInfo]:
    """Stereo float32 (n, 2) at 44.1 kHz, peak −1 dBFS."""
    spec = SPECS[mood]
    ti = info(spec)
    rng = np.random.default_rng(20261116 + list(SPECS).index(mood))
    beat = 60.0 / spec.bpm
    bar = ti.bar_s
    n = int(ti.duration * SR) + SR
    mix = _Mix(n)
    K, S, H, HO, T, C = kick(rng), snare(rng), hat(rng), hat(rng, True), taiko(rng), crash(rng)
    sections: list[tuple[str, int]] = []
    for name, bars in BARS.items():
        sections += [(name, i) for i in range(bars)]
    for b, (sec, i_in) in enumerate(sections):
        t0 = b * bar
        chord = _chord(spec, spec.progression[b % len(spec.progression)])
        full = sec in ("drop", "main")
        light = sec in ("intro", "break", "outro")
        fade = 1.0 if sec != "outro" else 1 - i_in / BARS["outro"]
        # pads (always), brighter in the full sections
        pl, pr = pad([_hz(m) for m in chord], bar + 0.25, bright=30 if full else 60)
        g = (0.10 if full else 0.13) * fade
        mix.add(int(t0 * SR), pl, g, -0.3)
        mix.add(int(t0 * SR), pr, g, 0.3)
        # bass: root on each beat (full) or long note
        root = _hz(chord[0] - 24)
        if full or sec == "build":
            for k in range(4):
                mix.add(int((t0 + k * beat) * SR), bass(root, beat * 0.9, sub=spec.drums != "four"), 0.32 * fade)
        elif sec != "intro":
            mix.add(int(t0 * SR), bass(root, bar * 0.95), 0.22 * fade)
        # drums
        if spec.drums != "none":
            for k in range(4):
                tb = t0 + k * beat
                sw = spec.swing * beat if k % 2 else 0.0
                if spec.drums in ("four", "trap") and (full or (sec == "build" and k % 2 == 0)):
                    mix.add(int(tb * SR), K, 0.55 * fade)
                if spec.drums == "half" and full and k in (0, 2):
                    mix.add(int(tb * SR), K, 0.55)
                if spec.drums == "soft" and not light and k in (0, 2):
                    mix.add(int(tb * SR), K, 0.35)
                if spec.drums == "taiko" and (full or sec == "build") and (k == 0 or (full and k == 2)):
                    mix.add(int(tb * SR), T, 0.5 * fade)
                if full and k in (1, 3) and spec.drums != "taiko":
                    mix.add(int(tb * SR), S, 0.35)
                if spec.drums == "soft" and sec == "main" and k in (1, 3):
                    mix.add(int(tb * SR), S, 0.18)
                # hats: 8ths (16ths for trap in full sections)
                sub = 4 if spec.drums == "trap" and full else 2
                if spec.drums != "taiko" and not (sec == "intro" and i_in < 2):
                    for h in range(sub):
                        th = tb + h * beat / sub + (sw if h % 2 else 0)
                        mix.add(int(th * SR), HO if (h == sub - 1 and k == 3 and full) else H,
                                (0.5 if h % 2 else 0.35) * fade, 0.25)
            if sec == "build":   # snare roll accelerating into the drop
                hits = 4 * (2 ** min(2, i_in))
                for h in range(hits):
                    mix.add(int((t0 + h * bar / hits) * SR), S, 0.12 + 0.25 * (i_in + h / hits) / BARS["build"])
        # lead / melody
        arp = [chord[0], chord[1], chord[2], chord[1] + 12, chord[2], chord[1], chord[0] + 12, chord[2]]
        if spec.lead in ("pluck", "square") and (full or sec == "break"):
            step = beat / 2
            for k in range(8):
                f = _hz(arp[k] + 12)
                y = pluck(f, step * 1.6) if spec.lead == "pluck" else square(f, step * 0.9)
                mix.add(int((t0 + k * step) * SR), y, 0.11 if spec.lead == "pluck" else 0.08, 0.35 * (1 if k % 2 else -1))
        elif spec.lead == "piano" and sec != "intro":
            for k in range(4):
                f = _hz(arp[(k * 2 + b) % 8] + 12)
                mix.add(int((t0 + k * beat + (spec.swing * beat if k % 2 else 0)) * SR), piano(f, beat * 1.8), 0.16 * fade)
        elif spec.lead == "strings" and sec != "intro":
            sl, sr_ = pad([_hz(chord[0] + 12), _hz(chord[2] + 12)], bar + 0.3, bright=90)
            trem = 1 + 0.15 * np.sin(2 * np.pi * 5.5 * np.arange(len(sl)) / SR)
            mix.add(int(t0 * SR), sl * trem, 0.07 * fade * (1.4 if full else 1), -0.5)
            mix.add(int(t0 * SR), sr_ * trem, 0.07 * fade * (1.4 if full else 1), 0.5)
        if sec == "build" and i_in == 0:
            mix.add(int(t0 * SR), riser(rng, BARS["build"] * bar), 0.5)
    # crash + sub boom on the drop and on the main section
    for sec_start in (ti.drop_time, (BARS["intro"] + BARS["build"] + BARS["drop"] + BARS["break"]) * bar):
        mix.add(int(sec_start * SR), C, 0.6)
        mix.add(int(sec_start * SR), bass(_hz(spec.root - 24), 1.2), 0.4)
    y = np.stack([mix.L, mix.R], axis=1)[: int(ti.duration * SR)]
    y = np.tanh(y * 1.2) / np.tanh(1.2)
    peak = float(np.max(np.abs(y))) or 1.0
    y = y / peak * 10 ** (-1 / 20)
    return y.astype(np.float32), ti
