"""Configurable, explainable clip scoring.

All signals are heuristics computed from audio, video and transcript. They
estimate *where something is likely happening*; they do not understand the
game semantically. Every clip carries the evidence (signals, keywords) that
produced its score and category, so the user can judge it.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field

import numpy as np
from pydantic import BaseModel, Field

from backend.clip_detection.lexicon import Hit, find_hits
from backend.transcription.whisper_engine import Transcript

CATEGORIES = ["funny", "rage", "epic", "fail", "reaction", "clutch", "storytelling", "unexpected",
              "gameplay_highlight"]

LABELS = {
    "it": {"funny": "Momento divertente", "rage": "Rage", "epic": "Momento epico", "fail": "Fail",
           "reaction": "Reazione", "clutch": "Clutch", "storytelling": "Racconto", "unexpected": "Imprevisto",
           "gameplay_highlight": "Highlight di gameplay"},
    "en": {"funny": "Funny moment", "rage": "Rage", "epic": "Epic moment", "fail": "Fail",
           "reaction": "Reaction", "clutch": "Clutch", "storytelling": "Story time", "unexpected": "Unexpected",
           "gameplay_highlight": "Gameplay highlight"},
}
EMOJI = {"funny": "😂", "rage": "😡", "epic": "🔥", "fail": "💀", "reaction": "😱", "clutch": "😮‍💨",
         "storytelling": "🎙️", "unexpected": "🤯", "gameplay_highlight": "⚡"}


class ScoringWeights(BaseModel):
    audio_peak: float = Field(1.0, ge=0, le=5, description="Loudness spikes above the local level")
    audio_energy: float = Field(0.4, ge=0, le=5, description="Overall loudness / sudden sounds")
    speech_excitement: float = Field(0.8, ge=0, le=5, description="Fast and loud speech")
    keywords: float = Field(1.0, ge=0, le=5, description="Category keywords in the transcript")
    laughter: float = Field(1.2, ge=0, le=5, description="Laughter in the transcript")
    visual_motion: float = Field(0.6, ge=0, le=5, description="On-screen motion and flashes")
    scene_changes: float = Field(0.4, ge=0, le=5, description="Density of scene cuts")


class ScoringConfig(BaseModel):
    weights: ScoringWeights = Field(default_factory=ScoringWeights)
    min_clip_s: float = Field(20, ge=3, le=180)
    max_clip_s: float = Field(75, ge=5, le=600)
    pre_roll_s: float = Field(18, ge=0, le=120, description="Context kept before the peak")
    post_roll_s: float = Field(8, ge=0, le=120, description="Context kept after the peak")
    max_clips: int = Field(12, ge=1, le=100)
    min_score: float = Field(30, ge=0, le=100)
    min_gap_s: float = Field(1, ge=0, le=120)
    smoothing_s: float = Field(2, ge=0.5, le=30)
    reason_language: str = Field("it", pattern="^(it|en)$")
    use_semantic: bool = Field(True, description="Use the local-LLM judgement when available")
    semantic_min: float = Field(3.5, ge=0, le=10, description="Minimum LLM rating (0-10): the best moments are kept even when the video has no viral ones")
    semantic_weight: float = Field(0.7, ge=0, le=1, description="Share of the final score from the LLM rating")


# ----------------------------------------------------------------- helpers
def robust_norm(x: np.ndarray, lo_pct: float = 50, hi_pct: float = 98) -> np.ndarray:
    if len(x) == 0:
        return x
    lo, hi = np.percentile(x, lo_pct), np.percentile(x, hi_pct)
    if hi - lo < 1e-6:
        return np.zeros_like(x, dtype=np.float32)
    return np.clip((x - lo) / (hi - lo), 0, 1).astype(np.float32)


def spread(n: int, times: list[float], window_s: float, sigma_s: float = 2.0, weights: list[float] | None = None) -> np.ndarray:
    """Place impulses at `times` and blur them with a Gaussian (sigma in seconds)."""
    out = np.zeros(n, dtype=np.float32)
    for k, t in enumerate(times):
        i = int(t / window_s)
        if 0 <= i < n:
            out[i] += weights[k] if weights else 1.0
    if not times:
        return out
    r = max(1, int(3 * sigma_s / window_s))
    xs = np.arange(-r, r + 1) * window_s
    kernel = np.exp(-0.5 * (xs / sigma_s) ** 2)
    return np.convolve(out, kernel, mode="same").astype(np.float32)


def smooth(x: np.ndarray, window_s: float, span_s: float) -> np.ndarray:
    k = max(1, int(span_s / window_s))
    if k <= 1 or len(x) < k:
        return x
    return np.convolve(x, np.ones(k) / k, mode="same").astype(np.float32)


def saturate(x, scale: float = 1.0):
    return 1 - np.exp(-np.asarray(x) / scale)


# ----------------------------------------------------------------- timeline
@dataclass
class RawSignals:
    window_s: float
    duration: float
    rms_db: np.ndarray
    excess_db: np.ndarray
    flux: np.ndarray
    motion: np.ndarray
    flash: np.ndarray
    scenes: list[float]
    has_audio: bool = True


@dataclass
class Timeline:
    window_s: float
    duration: float
    features: dict[str, np.ndarray]
    interest: np.ndarray
    hits: list[Hit] = field(default_factory=list)
    laughs: list[float] = field(default_factory=list)
    words: list[tuple[float, float, str]] = field(default_factory=list)
    segments: list[tuple[float, float, str]] = field(default_factory=list)
    scenes: list[float] = field(default_factory=list)


def build_timeline(raw: RawSignals, transcript: Transcript | None, game: str, cfg: ScoringConfig) -> Timeline:
    n, ws = len(raw.rms_db), raw.window_s
    words = [(w.start, w.end, w.word) for s in (transcript.segments if transcript else []) for w in s.words]
    segments = [(s.start, s.end, s.text) for s in (transcript.segments if transcript else [])]
    hits, laughs = find_hits([(w[0], w[2]) for w in words], game)

    audio_peak = np.clip((raw.excess_db - 3.0) / 15.0, 0, 1).astype(np.float32)
    audio_energy = (0.6 * robust_norm(raw.rms_db) + 0.4 * robust_norm(raw.flux)).astype(np.float32)

    speech = np.zeros(n, dtype=np.float32)
    starts = []
    for s, e, _ in words:
        a, b = int(s / ws), int(e / ws)
        speech[max(0, a):min(n, b + 1)] = 1.0
        starts.append(s)
    rate = spread(n, starts, ws, sigma_s=1.5) / (1.5 * math.sqrt(2 * math.pi))  # ≈ words per second
    rate_norm = np.clip((rate - 1.5) / 3.0, 0, 1)
    speech_excitement = (speech * (0.5 * rate_norm + 0.5 * audio_peak)).astype(np.float32)

    kw_hits = [h for h in hits if h.category not in ("storytelling",)]
    # Rarity weighting: a cue said all the time in THIS video (Italian fillers like «ma che», «allora»)
    # carries almost no information; a rare one does.
    freq = Counter(h.keyword for h in kw_hits)
    kw_weights = [(0.5 if h.category == "gameplay_highlight" else 1.0) / (1.0 + math.log(freq[h.keyword]))
                  for h in kw_hits]
    keywords = saturate(spread(n, [h.time for h in kw_hits], ws, 2.0, kw_weights), 1.0).astype(np.float32)
    laughter = saturate(spread(n, laughs, ws, 2.0), 0.8).astype(np.float32)

    visual = np.clip(robust_norm(raw.motion) + 0.5 * robust_norm(raw.flash, 90, 99.5), 0, 1).astype(np.float32)
    cuts = spread(n, raw.scenes, ws, sigma_s=3.0) / (3.0 * math.sqrt(2 * math.pi) / ws)
    scene_changes = np.clip(cuts * 4.0, 0, 1).astype(np.float32)  # ~1 cut / 4 s saturates

    features = {"audio_peak": audio_peak, "audio_energy": audio_energy, "speech_excitement": speech_excitement,
                "keywords": keywords, "laughter": laughter, "visual_motion": visual, "scene_changes": scene_changes,
                "speech": speech}
    w = cfg.weights.model_dump()
    if not raw.has_audio:
        w["audio_peak"] = w["audio_energy"] = 0.0
    if transcript is None:
        w["speech_excitement"] = w["keywords"] = w["laughter"] = 0.0
    # "Top-3 evidence" combination: a moment scores high when a few signals agree strongly,
    # without being diluted by channels that are silent (e.g. an explosion with no speech).
    names = [k for k, v in w.items() if v > 0]
    if names:
        contrib = np.stack([features[k] * w[k] for k in names])            # (signals, windows)
        k = min(3, len(names))
        top_sum = -np.sort(-contrib, axis=0)[:k].sum(axis=0)
        norm = sum(sorted((w[k_] for k_ in names), reverse=True)[:k])
        interest = top_sum / max(norm, 1e-6)
    else:
        interest = np.zeros(n, dtype=np.float32)
    interest = smooth(np.asarray(interest, dtype=np.float32), ws, cfg.smoothing_s)
    return Timeline(ws, raw.duration, features, interest, hits, laughs, words, segments, list(raw.scenes))


# ----------------------------------------------------------------- clips
@dataclass
class DetectedClip:
    start: float
    end: float
    peak_time: float
    score: float
    confidence: float
    category: str
    category_scores: dict[str, float]
    signals: dict[str, float]
    keywords: list[str]
    transcript: str
    reason: str
    suggested_title: str

    @property
    def duration(self) -> float:
        return self.end - self.start


def _snap_bounds(peak: float, tl: Timeline, cfg: ScoringConfig) -> tuple[float, float]:
    start, end = peak - cfg.pre_roll_s, peak + cfg.post_roll_s
    # Do not cut sentences: extend to sentence boundaries when close enough
    for s, e, _ in tl.segments:
        if s < start < e and start - s <= 6:
            start = s
        if s < end < e and e - end <= 6:
            end = e + 0.3
    if not any(s < start < e for s, e, _ in tl.segments):
        near = [c for c in tl.scenes if abs(c - start) <= 3]
        if near:
            start = min(near, key=lambda c: abs(c - start))
    # Enforce min / max length around the peak (more context before than after)
    length = end - start
    if length < cfg.min_clip_s:
        missing = cfg.min_clip_s - length
        start -= missing * 0.6
        end += missing * 0.4
    elif length > cfg.max_clip_s:
        before = (cfg.max_clip_s) * 2 / 3
        start = max(start, peak - before)
        end = start + cfg.max_clip_s
    # Clamp to the video, shifting instead of shrinking when possible
    if start < 0:
        end, start = min(tl.duration, end - start), 0.0
    if end > tl.duration:
        start, end = max(0.0, start - (end - tl.duration)), tl.duration
    return round(start, 2), round(end, 2)


def _avoid_overlaps(start: float, end: float, peak: float, clips: list[DetectedClip], cfg: ScoringConfig,
                    duration: float) -> tuple[float, float]:
    """Trim a new clip so it never overlaps already selected ones, extending the free side if possible."""
    for c in clips:
        if start < c.end and end > c.start:
            if peak >= c.end:
                start = c.end
                end = min(duration, max(end, start + cfg.min_clip_s))
            elif peak <= c.start:
                end = c.start
                start = max(0.0, min(start, end - cfg.min_clip_s))
            else:
                return start, start  # peak inside an existing clip
    for c in clips:  # extension may have created a new overlap on the other side
        if start < c.end and end > c.start:
            if c.start >= peak:
                end = min(end, c.start)
            else:
                start = max(start, c.end)
    return round(start, 2), round(end, 2)


def _window(tl: Timeline, a: float, b: float) -> slice:
    return slice(max(0, int(a / tl.window_s)), max(1, int(math.ceil(b / tl.window_s))))


def _categorize(tl: Timeline, start: float, end: float, peak: float, signals: dict[str, float],
                has_transcript: bool) -> tuple[str, dict[str, float], float, list[str]]:
    clip_hits = [h for h in tl.hits if start <= h.time <= end]
    kw = {c: float(saturate(sum(1 for h in clip_hits if h.category == c), 1.5)) for c in CATEGORIES}
    laughs = sum(1 for t in tl.laughs if start <= t <= end)
    laugh = float(saturate(laughs, 1.0))
    e = tl.features["audio_energy"]
    pi = int(peak / tl.window_s)
    before = e[max(0, pi - 10):max(1, pi - 2)]
    sudden = float(np.clip((e[min(len(e) - 1, pi)] - (before.mean() if len(before) else 0)) * 2, 0, 1))
    speech_cov = float(tl.features["speech"][_window(tl, start, end)].mean())

    sc = {
        # Semantic categories need verbal evidence (keywords / laughter); signals only modulate them.
        "funny": 0.6 * laugh + 0.4 * kw["funny"],
        "rage": kw["rage"] * (0.6 + 0.4 * max(signals["speech_excitement"], signals["audio_peak"])),
        "fail": kw["fail"] * (0.7 + 0.3 * signals["audio_peak"]),
        "clutch": kw["clutch"] * (0.75 + 0.25 * signals["visual_motion"]),
        # Signal-driven categories
        "epic": 0.4 * kw["epic"] + 0.6 * (0.4 * signals["visual_motion"] + 0.3 * signals["audio_energy"]
                                           + 0.3 * signals["scene_changes"]),
        "reaction": 0.45 * kw["reaction"] + 0.35 * signals["speech_excitement"] + 0.2 * sudden,
        "storytelling": 0.5 * speech_cov * (1 - signals["audio_peak"]) + 0.5 * kw["storytelling"],
        "unexpected": 0.6 * sudden * (1 - speech_cov * 0.5) + 0.4 * kw["unexpected"],
        "gameplay_highlight": max(0.15, 0.4 * signals["visual_motion"] + 0.3 * signals["scene_changes"]
                                  + 0.3 * kw["gameplay_highlight"]),
    }
    sc = {k: round(float(v), 3) for k, v in sc.items()}
    ranked = sorted(sc.items(), key=lambda kv: kv[1], reverse=True)
    top, second = ranked[0][1], ranked[1][1]
    conf = float(np.clip(top * 0.7 + (top - second) * 0.6, 0.05, 0.95))
    if not has_transcript:
        conf *= 0.75
    keywords = sorted({h.keyword for h in clip_hits})
    if laughs:
        keywords.append(f"risate×{laughs}")
    return ranked[0][0], sc, round(conf, 2), keywords


def _quote(tl: Timeline, start: float, end: float, peak: float) -> str:
    # Only quote speech close to the peak: a sentence merely touching the clip edge is not "the moment"
    lo, hi = max(start, peak - 5), min(end, peak + 3)
    candidates = [(s, e, t) for s, e, t in tl.segments if e >= lo and s <= hi and t.strip()]
    if not candidates:
        return ""
    hit_times = [h.time for h in tl.hits if start <= h.time <= end]

    def rank(seg):
        s, e, _ = seg
        n_hits = sum(1 for t in hit_times if s <= t <= e)
        return (n_hits, -abs((s + e) / 2 - peak))

    text = max(candidates, key=rank)[2].strip().strip('"')
    if len(text) > 70:
        text = text[:70].rsplit(" ", 1)[0] + "…"
    return text


def _clip_text(tl: Timeline, start: float, end: float) -> str:
    words = [w for s, e, w in tl.words if s >= start - 0.05 and e <= end + 0.05]
    if words:
        return "".join(words).strip()
    return " ".join(t for s, e, t in tl.segments if e > start and s < end).strip()


def _fmt(t: float) -> str:
    return f"{int(t // 60)}:{int(t % 60):02d}"


def _reason(lang: str, tl: Timeline, start: float, end: float, peak: float, signals: dict[str, float],
            keywords: list[str], category: str, raw: RawSignals) -> str:
    it = lang == "it"
    lines = []
    pi = min(len(raw.excess_db) - 1, int(peak / tl.window_s))
    ex = float(raw.excess_db[max(0, pi - 4):pi + 5].max()) if len(raw.excess_db) else 0
    if signals["audio_peak"] > 0.2 and ex >= 4:
        lines.append(f"Picco audio di +{ex:.0f} dB sopra il livello medio a {_fmt(peak)}" if it
                     else f"Audio spike +{ex:.0f} dB above the local level at {_fmt(peak)}")
    if signals["speech_excitement"] > 0.3:
        lines.append("Parlato rapido e ad alto volume" if it else "Fast, loud speech")
    real_kw = [k for k in keywords if not k.startswith("risate")]
    if real_kw:
        shown = ", ".join(f"«{k}»" for k in real_kw[:6])
        lines.append(f"Keyword rilevate: {shown}" if it else f"Keywords detected: {shown}")
    laughs = sum(1 for t in tl.laughs if start <= t <= end)
    if laughs:
        lines.append(f"Risate nel parlato trascritto ({laughs})" if it else f"Laughter in the transcript ({laughs})")
    if signals["visual_motion"] > 0.4:
        lines.append("Forte movimento a schermo" if it else "Strong on-screen motion")
    cuts = sum(1 for c in raw.scenes if start <= c <= end)
    if cuts >= 2:
        lines.append(f"{cuts} cambi scena nella clip" if it else f"{cuts} scene changes in the clip")
    if not lines:
        lines.append("Segmento più intenso rispetto al resto del video" if it
                     else "More intense than the rest of the video")
    label = LABELS[lang][category]
    head = (f"Categoria stimata «{label}» (euristica, da verificare)." if it
            else f"Estimated category “{label}” (heuristic, please verify).")
    return head + "\n" + "\n".join(f"• {ln}" for ln in lines)


def detect_clips(raw: RawSignals, transcript: Transcript | None, game: str, cfg: ScoringConfig) -> tuple[Timeline, list[DetectedClip]]:
    tl = build_timeline(raw, transcript, game, cfg)
    curve = tl.interest.copy()
    if len(curve) == 0:
        return tl, []
    available = np.ones(len(curve), dtype=bool)
    edge = max(1, int(1.0 / tl.window_s))  # ignore the very first/last second (encoder artefacts)
    if len(curve) > 4 * edge:
        available[:edge] = False
        available[-edge:] = False
    clips: list[DetectedClip] = []

    while len(clips) < cfg.max_clips and available.any():
        masked = np.where(available, curve, -1)
        pi = int(masked.argmax())
        peak_val = float(masked[pi])
        if peak_val < 0:
            break
        peak = pi * tl.window_s
        start, end = _snap_bounds(peak, tl, cfg)
        start, end = _avoid_overlaps(start, end, peak, clips, cfg, tl.duration)
        if end - start < min(cfg.min_clip_s, tl.duration) * 0.6:
            available[_window(tl, peak - 1, peak + 1)] = False  # squeezed between clips: skip this peak
            continue
        seg = curve[_window(tl, start, end)]
        raw_score = 0.65 * peak_val + 0.35 * float(seg.mean() if len(seg) else 0)
        score = round(100 * float(saturate(raw_score * 2.2)), 1)
        # mask this region (plus gap) so the next peak is a different moment
        available[_window(tl, start - cfg.min_gap_s, end + cfg.min_gap_s)] = False
        if score < cfg.min_score:
            break
        around = _window(tl, peak - 3, peak + 3)
        signals = {k: round(float(v[around].mean()), 3) for k, v in tl.features.items() if k != "speech"}
        category, cat_scores, conf, kws = _categorize(tl, start, end, peak, signals, transcript is not None)
        quote = _quote(tl, start, end, peak)
        lang = cfg.reason_language
        title = f"“{quote}” {EMOJI[category]}" if quote else f"{game} · {LABELS[lang][category]} {EMOJI[category]}"
        clips.append(DetectedClip(
            start=start, end=end, peak_time=round(peak, 2), score=score, confidence=conf, category=category,
            category_scores=cat_scores, signals=signals, keywords=kws, transcript=_clip_text(tl, start, end),
            reason=_reason(lang, tl, start, end, peak, signals, kws, category, raw), suggested_title=title[:300],
        ))
    clips.sort(key=lambda c: c.start)
    return tl, clips


# ----------------------------------------------------------------- semantic (local LLM) selection
def semantic_clips(tl: Timeline, raw: RawSignals, semantic: dict, cfg: ScoringConfig, game: str) -> list[DetectedClip]:
    """Clips proposed by the local LLM, on whole thought units, blended with the signal score."""
    units = {u["id"]: u for u in semantic.get("units", [])}
    out: list[DetectedClip] = []
    lang = cfg.reason_language
    n_ranked = sum(1 for j in semantic.get("judgements", []) if "rank" in j)
    for j in semantic.get("judgements", []):
        if j["score"] < cfg.semantic_min or j["first"] not in units or j["last"] not in units:
            continue
        # Relative quality: the listwise rank spreads candidates from 2 to 10 (absolute ratings are often flat)
        rank_score = (10 - 8 * (j["rank"] - 1) / max(1, n_ranked - 1)) if "rank" in j else None
        llm10 = 0.5 * rank_score + 0.5 * j["score"] if rank_score is not None else j["score"]
        pref = j.get("pref")  # 0..1 affinity with the clips you approved/rejected (None = not enough examples)
        if pref is not None:
            llm10 = 0.5 * (2 + 8 * pref) + 0.5 * llm10
        first, last = j["first"], j["last"]
        # The LLM picked a whole thought: only pad very short spans (padding a complete story with filler hurts),
        # adding previous units first (context); trim spans that are too long from the start.
        min_len = min(cfg.min_clip_s, 12.0)
        while units[last]["end"] - units[first]["start"] < min_len:
            if first - 1 in units and (units[first]["start"] - units[first - 1]["start"]) < cfg.max_clip_s:
                first -= 1
            elif last + 1 in units:
                last += 1
            else:
                break
        while units[last]["end"] - units[first]["start"] > cfg.max_clip_s and first < last:
            first += 1
        start = max(0.0, units[first]["start"] - 0.3)
        end = min(tl.duration, units[last]["end"] + 0.8)  # a breath of reaction after the payoff
        seg = tl.interest[_window(tl, start, end)]
        sig = float(seg.mean()) if len(seg) else 0.0
        signal_score = 100 * float(saturate(sig * 2.2))
        w = cfg.semantic_weight
        score = round(w * llm10 * 10 + (1 - w) * signal_score, 1)
        hook = j.get("hook", "")
        peak = start + (end - start) / 2
        if hook:
            target = hook.lower().split()[0] if hook.split() else ""
            for ws, _we, word in tl.words:
                if start <= ws <= end and word.strip().lower().strip(",.!?") == target:
                    peak = ws
                    break
        around = _window(tl, peak - 3, peak + 3)
        signals = {k: round(float(v[around].mean()), 3) for k, v in tl.features.items() if k != "speech"}
        cat = j["category"] if j["category"] in CATEGORIES else "storytelling"
        conf = round(min(0.95, llm10 / 10 * (0.95 if j.get("standalone", True) else 0.65)), 2)
        rank_txt = (f", {j['rank']}° su {n_ranked} nel confronto" if lang == "it" else f", #{j['rank']} of {n_ranked}") \
            if "rank" in j else ""
        if pref is not None:
            level = "alta" if pref >= 0.66 else "media" if pref >= 0.33 else "bassa"
            rank_txt += (f", affinità con le tue scelte {level}" if lang == "it" else f", affinity with your picks {level}")
        head = (f"Valutazione AI locale {j['score']:.0f}/10{rank_txt} — {j.get('reason', '')}" if lang == "it"
                else f"Local AI rating {j['score']:.0f}/10{rank_txt} — {j.get('reason', '')}")
        sig_part = _reason(lang, tl, start, end, peak, signals, [], cat, raw).split("\n", 1)[-1]
        title = f"\u201c{hook}\u201d {EMOJI[cat]}" if hook else f"{game} · {LABELS[lang][cat]} {EMOJI[cat]}"
        out.append(DetectedClip(
            start=round(start, 2), end=round(end, 2), peak_time=round(peak, 2), score=score, confidence=conf,
            category=cat, category_scores={cat: round(j["score"] / 10, 3)}, signals=signals,
            keywords=[hook] if hook else [], transcript=_clip_text(tl, start, end),
            reason=head + "\n" + sig_part, suggested_title=title[:300]))
    return out


def hybrid_clips(raw: RawSignals, transcript: Transcript | None, game: str, cfg: ScoringConfig,
                 semantic: dict | None) -> tuple[Timeline, list[DetectedClip]]:
    """Semantic clips first; heuristic clips only fill gaps (e.g. explosions without speech)."""
    tl, heuristic = detect_clips(raw, transcript, game, cfg)
    if not (cfg.use_semantic and semantic and semantic.get("judgements")):
        return tl, heuristic
    chosen: list[DetectedClip] = []

    def free(c: DetectedClip) -> bool:
        return all(c.end <= o.start + 0.01 or c.start >= o.end - 0.01 for o in chosen)

    for c in sorted(semantic_clips(tl, raw, semantic, cfg, game), key=lambda c: -c.score):
        if len(chosen) < cfg.max_clips and c.score >= cfg.min_score and free(c):
            chosen.append(c)
    # heuristic moments the LLM cannot judge: little or no speech but strong audio/visual signals
    for c in sorted(heuristic, key=lambda c: -c.score):
        speechy = float(tl.features["speech"][_window(tl, c.start, c.end)].mean()) > 0.4
        if len(chosen) < cfg.max_clips and not speechy and c.score >= max(cfg.min_score, 55) and free(c):
            chosen.append(c)
    chosen.sort(key=lambda c: c.start)
    return tl, chosen


def clip_transcript(transcript: Transcript | None, start: float, end: float) -> str:
    if transcript is None:
        return ""
    words = [w.word for s in transcript.segments for w in s.words if w.start >= start - 0.05 and w.end <= end + 0.05]
    return "".join(words).strip()
