"""Output timeline: which parts of a clip are kept (silence removal) and time mapping.

All times here are clip-relative seconds (0 = clip start). Segment edges are
quantised to the output frame grid so audio and video cut on the same instant.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Segment:
    start: float  # clip-relative source time
    end: float
    out_start: float  # position in the output (excluding intro)
    speed: float = 1.0   # playback speed (< 1 = slow motion); out duration = (end - start) / speed
    hold: float = 0.0    # freeze frame: start == end, the frame at `start` is held for `hold` seconds
    kind: str = ""       # "" | slow_motion | speed_ramp | freeze_frame

    @property
    def duration(self) -> float:
        """Source duration."""
        return self.end - self.start

    @property
    def out_duration(self) -> float:
        return self.hold if self.hold > 0 else (self.end - self.start) / self.speed

    @property
    def out_end(self) -> float:
        return self.out_start + self.out_duration


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
    return sum(s.out_duration for s in segments)


def map_time(t: float, segments: list[Segment], last: bool = False) -> float | None:
    """Clip-relative source time → output time (None if the instant was cut). At a freeze frame the
    instant exists twice (before and after the hold): first occurrence by default, `last` for the other."""
    hit = None
    for s in segments:
        if s.hold > 0:
            if abs(t - s.start) <= 1e-6:
                hit = s.out_start if hit is None else hit
                if last:
                    hit = s.out_end
            continue
        if s.start - 1e-6 <= t <= s.end + 1e-6:
            v = s.out_start + (t - s.start) / s.speed
            if not last:
                return v if hit is None else hit
            hit = v
    return hit


def _runs(segments: list[Segment]) -> list[list[Segment]]:
    """Groups of segments contiguous in the source (speed changes and freezes do not break a run)."""
    runs: list[list[Segment]] = []
    for s in segments:
        if runs and abs(s.start - runs[-1][-1].end) < 1e-6:
            runs[-1].append(s)
        else:
            runs.append([s])
    return runs


def map_interval(a: float, b: float, segments: list[Segment]) -> tuple[float, float] | None:
    """Map a source interval to the output, clamping it to the kept run that contains most of it."""
    best: tuple[float, float] | None = None
    best_len = 0.0
    for run in _runs(segments):
        lo, hi = max(a, run[0].start), min(b, run[-1].end)
        if hi - lo > best_len:
            o0, o1 = map_time(lo, run), map_time(hi, run, last=True)
            if o0 is not None and o1 is not None:
                best_len = hi - lo
                best = (o0, o1)
    return best


def inverse(t_out: float, segments: list[Segment]) -> tuple[float, Segment]:
    """Output time (body, no intro) → (clip-relative source time, segment). Monotonic in t_out."""
    for s in segments:
        if t_out < s.out_end - 1e-9:
            if s.hold > 0:
                return s.start, s
            return s.start + max(0.0, t_out - s.out_start) * s.speed, s
    s = segments[-1]
    return s.end, s


def cut_points(segments: list[Segment]) -> list[float]:
    """Output times where a jump cut happens (the source jumps forward)."""
    return [b.out_start for a, b in zip(segments, segments[1:]) if b.start - a.end > 1e-6]


def cuts_with_source(segments: list[Segment]) -> list[tuple[float, float, float]]:
    """(output time, source time before the cut, source time after it) for every jump cut."""
    return [(b.out_start, a.end, b.start) for a, b in zip(segments, segments[1:]) if b.start - a.end > 1e-6]


def _ease(x: float) -> float:
    return 0.5 - 0.5 * math.cos(math.pi * x)


def apply_time_effects(segments: list[Segment], effects: list, fps: int, ramp_steps: int = 8) -> list[Segment]:
    """Split the kept segments at the time effects and give each piece its speed; insert freeze holds.

    Output durations are quantised to whole frames and the speed is re-derived from them, so the video
    (inverse) and the audio (atempo per piece) use exactly the same mapping: no A/V drift."""
    pieces: list[tuple[float, float, float, float, str]] = []   # (start, end, speed, hold, kind)
    for seg in segments:
        cuts = [(seg.start, seg.end, 1.0, 0.0, "")]
        for e in effects:
            kind = e.kind
            nxt = []
            for a, b, sp, hold, k in cuts:
                if hold > 0 or k:
                    nxt.append((a, b, sp, hold, k))
                    continue
                if kind == "freeze_frame":
                    t = e.start
                    if a < t < b:
                        nxt += [(a, t, sp, 0.0, ""), (t, t, 1.0, e.hold, "freeze_frame"), (t, b, sp, 0.0, "")]
                    else:
                        nxt.append((a, b, sp, hold, k))
                    continue
                lo, hi = max(a, e.start), min(b, e.end)
                if hi - lo < 0.05:
                    nxt.append((a, b, sp, hold, k))
                    continue
                if lo > a:
                    nxt.append((a, lo, 1.0, 0.0, ""))
                if kind == "slow_motion":
                    nxt.append((lo, hi, e.speed, 0.0, kind))
                else:  # speed ramp: 1 → speed → 1 with an eased curve, in steps
                    span = e.end - e.start
                    for i in range(ramp_steps):
                        x0 = e.start + span * i / ramp_steps
                        x1 = e.start + span * (i + 1) / ramp_steps
                        p0, p1 = max(lo, x0), min(hi, x1)
                        if p1 - p0 < 1e-3:
                            continue
                        mid = (i + 0.5) / ramp_steps
                        depth = math.sin(math.pi * mid) ** 1.5
                        nxt.append((p0, p1, 1.0 - (1.0 - e.speed) * depth, 0.0, kind))
                if hi < b:
                    nxt.append((hi, b, 1.0, 0.0, ""))
            cuts = nxt
        pieces += cuts
    out: list[Segment] = []
    o = 0.0
    for a, b, sp, hold, k in pieces:
        if hold > 0:
            dur = max(1, round(hold * fps)) / fps
            out.append(Segment(a, a, round(o, 6), 1.0, dur, k))
            o += dur
            continue
        if b - a < 1e-4:
            continue
        frames = max(1, round((b - a) / sp * fps))
        dur = frames / fps
        out.append(Segment(a, b, round(o, 6), (b - a) / dur, 0.0, k))
        o += dur
    return out
