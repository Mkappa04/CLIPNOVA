"""Audio analysis on a 16 kHz mono WAV: loudness, spectral flux, peaks, silences.

Processed in streaming chunks so multi-hour recordings stay within a few MB of RAM.
"""

from __future__ import annotations

import wave
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

EPS = 1e-10


@dataclass
class AudioFeatures:
    window_s: float
    rms_db: np.ndarray            # loudness per window (dBFS)
    excess_db: np.ndarray         # loudness above the local (30 s) median
    flux: np.ndarray              # spectral flux (onsets / sudden sounds)
    centroid_hz: np.ndarray       # spectral centroid (brightness: shouting, explosions)
    peaks: list[dict] = field(default_factory=list)
    silences: list[tuple[float, float]] = field(default_factory=list)
    stats: dict = field(default_factory=dict)


def empty_features(n_windows: int, window_s: float) -> AudioFeatures:
    z = np.zeros(n_windows, dtype=np.float32)
    return AudioFeatures(window_s, z - 90, z.copy(), z.copy(), z.copy(), stats={"has_audio": False})


def rolling_median(x: np.ndarray, win: int) -> np.ndarray:
    """Rolling median via block medians + interpolation (fast for long signals)."""
    if len(x) == 0:
        return x
    step = max(1, win // 4)
    centers, meds = [], []
    for c in range(0, len(x), step):
        lo, hi = max(0, c - win // 2), min(len(x), c + win // 2 + 1)
        centers.append(c)
        meds.append(float(np.median(x[lo:hi])))
    return np.interp(np.arange(len(x)), centers, meds).astype(np.float32)


def analyze_audio(
    wav_path: Path, window_s: float = 0.5, *,
    on_progress: Callable[[float], None] | None = None, should_cancel: Callable[[], bool] | None = None,
) -> AudioFeatures:
    with wave.open(str(wav_path), "rb") as wf:
        if wf.getsampwidth() != 2 or wf.getnchannels() != 1:
            raise ValueError("Expected 16-bit mono WAV")
        sr = wf.getframerate()
        total = wf.getnframes()
        hop = int(sr * window_s)
        n_win = max(1, total // hop)
        rms_db = np.empty(n_win, dtype=np.float32)
        flux = np.zeros(n_win, dtype=np.float32)
        centroid = np.zeros(n_win, dtype=np.float32)
        freqs = np.fft.rfftfreq(hop, 1 / sr).astype(np.float32)
        window_fn = np.hanning(hop).astype(np.float32)
        prev_mag: np.ndarray | None = None
        chunk_windows = 240  # 2 minutes per read at 0.5 s windows

        for start in range(0, n_win, chunk_windows):
            if should_cancel and should_cancel():
                raise InterruptedError
            count = min(chunk_windows, n_win - start)
            raw = wf.readframes(count * hop)
            samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
            usable = (len(samples) // hop) * hop
            frames = samples[:usable].reshape(-1, hop)
            got = frames.shape[0]
            rms = np.sqrt(np.mean(frames ** 2, axis=1) + EPS)
            rms_db[start:start + got] = 20 * np.log10(rms + EPS)
            mag = np.abs(np.fft.rfft(frames * window_fn, axis=1)).astype(np.float32)
            centroid[start:start + got] = (mag @ freqs) / (mag.sum(axis=1) + EPS)
            # spectral flux on log-magnitude, positive changes only
            logmag = np.log1p(mag)
            prev = np.vstack([prev_mag[None, :] if prev_mag is not None else logmag[:1], logmag[:-1]])
            flux[start:start + got] = np.maximum(logmag - prev, 0).mean(axis=1)
            prev_mag = logmag[-1]
            if got < count:
                rms_db[start + got:] = -90
                n_win = start + got
                break
            if on_progress:
                on_progress(min(1.0, (start + count) / n_win))

    rms_db, flux, centroid = rms_db[:n_win], flux[:n_win], centroid[:n_win]
    baseline = rolling_median(rms_db, int(30 / window_s))
    excess = np.maximum(rms_db - baseline, 0).astype(np.float32)

    feats = AudioFeatures(window_s, rms_db, excess, flux, centroid)
    feats.peaks = find_peaks(excess, rms_db, window_s)
    feats.silences = find_silences(rms_db, window_s)
    voiced = rms_db > -60
    feats.stats = {
        "has_audio": True,
        "median_db": round(float(np.median(rms_db)), 1),
        "p95_db": round(float(np.percentile(rms_db, 95)), 1),
        "peaks": len(feats.peaks),
        "silence_ratio": round(float(1 - voiced.mean()), 3),
    }
    return feats


def find_peaks(excess: np.ndarray, rms_db: np.ndarray, window_s: float,
               min_excess_db: float = 6.0, min_distance_s: float = 2.0) -> list[dict]:
    """Local maxima of loudness above the local baseline."""
    radius = max(1, int(min_distance_s / window_s))
    peaks = []
    for i in np.flatnonzero(excess >= min_excess_db):
        lo, hi = max(0, i - radius), min(len(excess), i + radius + 1)
        if excess[i] == excess[lo:hi].max() and (not peaks or i - peaks[-1]["i"] > radius):
            peaks.append({"i": int(i), "time": round(i * window_s, 2),
                          "excess_db": round(float(excess[i]), 1), "db": round(float(rms_db[i]), 1)})
    return peaks


def find_silences(rms_db: np.ndarray, window_s: float, min_len_s: float = 1.5) -> list[tuple[float, float]]:
    """Runs of windows well below the overall level (pauses, quiet menus)."""
    if len(rms_db) == 0:
        return []
    thresh = min(float(np.median(rms_db)) - 18.0, -45.0)
    quiet = rms_db < thresh
    out, start = [], None
    for i, q in enumerate(np.append(quiet, False)):
        if q and start is None:
            start = i
        elif not q and start is not None:
            if (i - start) * window_s >= min_len_s:
                out.append((round(start * window_s, 2), round(i * window_s, 2)))
            start = None
    return out
