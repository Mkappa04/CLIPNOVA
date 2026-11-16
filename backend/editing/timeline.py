"""Output timeline: which parts of a clip are kept (silence removal) and time mapping.

All times here are clip-relative seconds (0 = clip start). Segment edges are
quantised to the output frame grid so audio and video cut on the same instant.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Segment:
    start: float  # clip-relative source time
    end: float
    out_start: float  # position in the output (excluding intro)

    @property
    def duration(self) -> float:
        return self.end - self.start


def _q(t: float, fps: int) -> float:
    return round(round(t * fps) / fps, 6)


def compute_segments(
    duration: float, fps: int, *, words: list[tuple[float, float]] | None = None,
    rms_db: np.ndarray | None = None, window_s: float = 0.5, rms_offset: float = 0.0,
    remove_silences: bool = False, strategy: str = "quiet", min_silence_s: float = 0.8, padding_s: float = 0.15,
    keep: list[tuple[float, float]] | None = None,
) -> list[Segment]:
    """Kept segments. `words` are clip-relative (start, end); `rms_db` covers the whole video
    with `rms_offset` = clip start in video time. `keep`: pauses the editing plan wants to keep
    (e.g. the dramatic pause before a punchline) — never cut."""
    if not remove_silences or not words:
        return [Segment(0.0, _q(duration, fps), 0.0)]

    words = sorted(words)
    gaps: list[tuple[float, float]] = []
    prev_end = 0.0
    for s, e in words:
        if s - prev_end >= min_silence_s:
            gaps.append((prev_end, s))
        prev_end = max(prev_end, e)
    if duration - prev_end >= min_silence_s:
        gaps.append((prev_end, duration))

    if strategy == "quiet" and rms_db is not None and len(rms_db):
        lo = max(0, int(rms_offset / window_s))
        hi = min(len(rms_db), int((rms_offset + duration) / window_s) + 1)
        clip_db = rms_db[lo:hi]
        if len(clip_db):
            threshold = float(np.median(clip_db)) - 6.0

            def quiet(a: float, b: float) -> bool:
                i0 = int((rms_offset + a) / window_s)
                i1 = max(i0 + 1, int((rms_offset + b) / window_s))
                seg = rms_db[i0:i1]
                return len(seg) > 0 and float(seg.mean()) < threshold

            gaps = [g for g in gaps if quiet(*g)]

    if keep:
        gaps = [g for g in gaps if not any(min(g[1], kb) - max(g[0], ka) > 0.5 * min(g[1] - g[0], kb - ka)
                                           for ka, kb in keep)]

    # Remove each gap minus padding on both sides
    cuts = []
    for a, b in gaps:
        a2 = a + padding_s if a > 0 else 0.0
        b2 = b - padding_s if b < duration else duration
        if b2 - a2 >= max(0.2, min_silence_s - 2 * padding_s):
            cuts.append((_q(a2, fps), _q(b2, fps)))

    segments: list[Segment] = []
    cursor, out = 0.0, 0.0
    for a, b in cuts:
        if a > cursor:
            segments.append(Segment(cursor, a, out))
            out += a - cursor
        cursor = b
    end = _q(duration, fps)
    if end > cursor:
        segments.append(Segment(cursor, end, out))
    return segments or [Segment(0.0, end, 0.0)]


def output_duration(segments: list[Segment]) -> float:
    return sum(s.duration for s in segments)


def map_time(t: float, segments: list[Segment]) -> float | None:
    """Clip-relative source time → output time (None if the instant was cut)."""
    for s in segments:
        if s.start - 1e-6 <= t <= s.end + 1e-6:
            return s.out_start + (t - s.start)
    return None


def map_interval(a: float, b: float, segments: list[Segment]) -> tuple[float, float] | None:
    """Map a source interval to the output, clamping it to the kept part that contains most of it."""
    best: tuple[float, float] | None = None
    best_len = 0.0
    for s in segments:
        lo, hi = max(a, s.start), min(b, s.end)
        if hi - lo > best_len:
            best_len = hi - lo
            best = (s.out_start + lo - s.start, s.out_start + hi - s.start)
    return best


def cut_points(segments: list[Segment]) -> list[float]:
    """Output times where a jump cut happens (for transitions)."""
    return [s.out_start for s in segments[1:]]
