"""AI Editing Planner: decides, for one clip, where to zoom, emphasise words, add a sound, keep or cut
pauses, and — just as important — where to leave the video alone ("none").

1. Evidence → candidates (deterministic): audio spikes (shouting, crowd, explosions), reaction keywords,
   the semantic hook quote, the detected clip peak, motion/flash spikes. Every candidate has a time, a
   kind and a strength 0..1 with the evidence written out.
2. Decision:
   - rules (always available, no GPU/network): the preset policy maps each strong candidate to an effect;
   - local LLM (Ollama, optional, free): reads the transcript and the candidate list and picks, per
     candidate id, an effect from the allowed set or "none". It can only choose among the candidates,
     so it never invents timestamps. Any failure → the rules plan is used.
3. Hard limits (always, after either decision): allowed effects, effects per minute, minimum gap,
   max duration, intensity range, SFX budget. Gaps are filled with explicit "none" segments.

The plan is an ``EditPlan`` (Pydantic): validated timestamps, clamped intensities, no overlaps.
Times are clip-relative source seconds (before pause removal).
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import re
from collections import Counter
from dataclasses import dataclass, field

import httpx
import numpy as np
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from backend.clip_detection.lexicon import find_hits, normalize
from backend.core.config import get_settings
from backend.editing.config import EditConfig
from backend.editing.presets import VISUAL_ZOOMS, Effect, PlannerPolicy, SfxCategory, get_preset

log = logging.getLogger(__name__)

PLAN_VERSION = 1
REACTION_CATEGORIES = {"funny", "rage", "epic", "fail", "reaction", "clutch", "unexpected"}
STOPWORDS = set("""
il lo la i gli le un uno una di a da in con su per tra fra e o ma se che chi non si mi ti ci vi ne è sono era
del dello della dei degli delle al allo alla ai agli alle dal dallo dalla dai dagli dalle nel nello nella nei
negli nelle sul sullo sulla sui sugli sulle questo questa quello quella come cosa anche più poi già ancora
molto tutto tutti ho hai ha abbiamo avete hanno sei siamo siete io tu lui lei noi voi loro qui qua là lì
allora quindi però perché dove quando mentre proprio tipo cioè boh ecco vabbè okay ok sì no
the a an of to in on at for and or but if that this these those is are was were be been being have has had
i you he she we they it me my your our their its so just like really very yeah uh um oh
what who how why when where there here then than with from about into out up down off over again
get got go going gonna wanna can could would should will just don't i'm it's that's you're
""".split())


# ------------------------------------------------------------------ plan model
class SfxCue(BaseModel):
    category: SfxCategory
    volume: float = Field(0.5, ge=0, le=1)
    at: float = Field(0.0, ge=0, description="Clip-relative time of the sound")


class PlanSegment(BaseModel):
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    effect: Effect = "none"
    intensity: float = 0.0
    reason: str = ""
    sfx: SfxCue | None = None
    candidate: int | None = None

    @field_validator("intensity", mode="before")
    @classmethod
    def _clamp(cls, v) -> float:
        try:
            return float(min(1.0, max(0.0, float(v))))
        except (TypeError, ValueError):
            return 0.0

    @field_validator("reason")
    @classmethod
    def _short(cls, v: str) -> str:
        return " ".join(str(v).split())[:200]

    @model_validator(mode="after")
    def _order(self) -> PlanSegment:
        if self.end <= self.start:
            raise ValueError(f"segment end {self.end} <= start {self.start}")
        if self.effect == "none":
            self.intensity = 0.0
            self.sfx = None
        return self


class EmphasisWord(BaseModel):
    start: float = Field(ge=0)
    end: float = Field(ge=0)
    word: str
    reason: str = ""


class PauseDecision(BaseModel):
    start: float = Field(ge=0)
    end: float = Field(ge=0)
    action: str = Field(pattern="^(cut|keep)$")
    reason: str = ""


class EditPlan(BaseModel):
    version: int = PLAN_VERSION
    preset: str
    source: str = Field("rules", pattern="^(rules|llm)$")
    duration: float = Field(gt=0)
    segments: list[PlanSegment] = []
    emphasis: list[EmphasisWord] = []
    pauses: list[PauseDecision] = []
    candidates: list[dict] = []
    notes: list[str] = []
    key: str = ""

    @model_validator(mode="after")
    def _normalise(self) -> EditPlan:
        """Clamp to [0, duration], drop invalid/overlapping effect segments, fill gaps with 'none'."""
        d = self.duration
        effects: list[PlanSegment] = []
        for s in sorted((s for s in self.segments if s.effect != "none"), key=lambda s: s.start):
            a, b = max(0.0, min(s.start, d)), max(0.0, min(s.end, d))
            if b - a < 0.15:
                continue
            if effects and a < effects[-1].end:  # overlap: keep the earlier one
                continue
            seg = s.model_copy(update={"start": round(a, 3), "end": round(b, 3)})
            if seg.sfx is not None:
                seg.sfx.at = round(min(max(seg.sfx.at, 0.0), d - 0.05), 3)
            effects.append(seg)
        nones = [s for s in self.segments if s.effect == "none" and s.reason]

        def gap_reason(a: float, b: float) -> str:
            rs: list[str] = []
            for s in nones:
                if a <= (s.start + s.end) / 2 <= b and s.reason not in rs:
                    rs.append(s.reason)
            return " | ".join(rs[:2]) if rs else "Nessun momento forte: video invariato"

        out: list[PlanSegment] = []
        cursor = 0.0
        for s in effects:
            if s.start - cursor >= 0.05:
                out.append(PlanSegment(start=round(cursor, 3), end=s.start, effect="none",
                                       reason=gap_reason(cursor, s.start)))
            out.append(s)
            cursor = s.end
        if d - cursor >= 0.05 or not out:
            end = round(d, 3) if d - cursor >= 0.05 else round(max(d, cursor + 0.05), 3)
            out.append(PlanSegment(start=round(cursor, 3), end=end, effect="none", reason=gap_reason(cursor, d)))
        self.segments = out
        self.emphasis = sorted((w for w in self.emphasis if 0 <= w.start < d and w.end > w.start),
                               key=lambda w: w.start)
        return self

    # convenience views for the renderer
    def effect_segments(self, *kinds: str) -> list[PlanSegment]:
        return [s for s in self.segments if s.effect in kinds]

    def sfx_cues(self) -> list[SfxCue]:
        return [s.sfx for s in self.segments if s.sfx is not None]

    def kept_pauses(self) -> list[tuple[float, float]]:
        return [(p.start, p.end) for p in self.pauses if p.action == "keep"]

    def summary(self) -> dict:
        c = Counter(s.effect for s in self.segments)
        return {"source": self.source, "preset": self.preset, "effects": {k: v for k, v in c.items() if k != "none"},
                "none_segments": c.get("none", 0), "emphasis": len(self.emphasis),
                "sfx": len(self.sfx_cues()), "kept_pauses": len(self.kept_pauses())}


# ------------------------------------------------------------------ inputs & candidates
@dataclass
class PlannerInput:
    duration: float
    words: list[dict]                      # clip-relative {"start","end","word"}
    window_s: float = 0.5
    rms_db: np.ndarray | None = None       # clip window slices
    excess_db: np.ndarray | None = None
    motion: np.ndarray | None = None
    flash: np.ndarray | None = None
    peak: float | None = None              # clip-relative
    category: str = ""
    game: str = ""
    language: str = "it"
    hook: str = ""
    word_counts: dict[str, int] = field(default_factory=dict)  # whole-video token frequencies (rarity)
    total_words: int = 0


@dataclass
class Candidate:
    id: int
    t: float
    kind: str               # reaction | highlight | action
    strength: float
    evidence: list[str]
    category: str = ""      # lexicon category if any (funny, rage, …)
    span: tuple[float, float] | None = None  # explicit extent (hook quote)

    def as_dict(self) -> dict:
        return {"id": self.id, "t": round(self.t, 2), "kind": self.kind, "strength": round(self.strength, 2),
                "evidence": "; ".join(self.evidence), "category": self.category}


def _peaks(x: np.ndarray, min_value: float, min_dist: int) -> list[int]:
    """Local maxima ≥ min_value, at least min_dist samples apart (strongest first)."""
    if x is None or len(x) < 3:
        return []
    idx = [i for i in range(len(x)) if x[i] >= min_value
           and x[i] >= x[max(0, i - 1)] and x[i] >= x[min(len(x) - 1, i + 1)]]
    chosen: list[int] = []
    for i in sorted(idx, key=lambda i: -x[i]):
        if all(abs(i - j) >= min_dist for j in chosen):
            chosen.append(i)
    return chosen


def _z(x: np.ndarray) -> np.ndarray:
    med = float(np.median(x))
    mad = float(np.median(np.abs(x - med))) or 1e-6
    return (x - med) / (1.4826 * mad)


def _speech_near(words: list[dict], t: float, r: float = 1.0) -> bool:
    return any(w["start"] - r <= t <= w["end"] + r for w in words)


def find_candidates(inp: PlannerInput) -> list[Candidate]:
    raw: list[Candidate] = []
    ws = inp.window_s
    d = inp.duration

    def add(t, kind, strength, ev, category="", span=None):
        if 0.3 <= t <= d - 0.3 or span:
            raw.append(Candidate(0, float(t), kind, float(min(1.0, max(0.0, strength))), [ev], category, span))

    # 1. audio spikes over the local loudness (shouting, crowd roar, explosions)
    if inp.excess_db is not None and len(inp.excess_db):
        ex = inp.excess_db
        for i in _peaks(ex, 6.0, max(1, int(2.0 / ws))):
            v = float(ex[i])
            j = i  # anchor on the attack: first window of the burst above half the peak
            while j > 0 and ex[j - 1] >= v * 0.5 and i - j < int(3.0 / ws):
                j -= 1
            t = j * ws + ws / 2
            speech = _speech_near(inp.words, t)
            add(t, "reaction" if speech else "action", (v - 4) / 14,
                f"picco audio +{v:.0f} dB" + (" con voce (urlo/reazione)" if speech else " senza voce"))
    # 2. reaction keywords
    if inp.words:
        hits, laughs = find_hits([(w["start"], w["word"]) for w in inp.words], inp.game)
        for h in hits:
            if h.category in REACTION_CATEGORIES:
                add(h.time, "reaction", 0.5, f"parola chiave “{h.keyword}” ({h.category})", h.category)
        for t in laughs:
            add(t, "reaction", 0.55, "risata", "funny")
    # 3. semantic hook quote (the line the local LLM judged as the payoff)
    if inp.hook and inp.words:
        span = _locate_quote(inp.words, inp.hook)
        if span:
            add(span[0], "highlight", 0.7, f"battuta chiave: “{inp.hook[:60]}”", span=span)
    # 4. detected clip peak
    if inp.peak is not None and 0 <= inp.peak <= d:
        add(inp.peak, "highlight", 0.6, "picco della clip (rilevamento)")
    # 5. visual action: motion / flash spikes
    for arr, label in ((inp.motion, "movimento improvviso"), (inp.flash, "lampo/esplosione")):
        if arr is not None and len(arr) >= 8 and float(np.std(arr)) > 1e-6:
            z = _z(arr.astype(np.float64))
            for i in _peaks(z, 4.0, max(1, int(3.0 / ws))):
                add(i * ws + ws / 2, "action", min(0.9, 0.35 + z[i] / 20), f"{label} (z={z[i]:.1f})")

    # merge candidates closer than 1 s: strongest kind wins, evidence accumulates, agreement boosts
    raw.sort(key=lambda c: c.t)
    merged: list[Candidate] = []
    for c in raw:
        m = merged[-1] if merged else None
        if m and abs(c.t - m.t) <= 1.0 and not (c.span and m.span):
            n_before = len(m.evidence)
            if c.strength > m.strength:
                m.t, m.kind = c.t, c.kind
            m.strength = min(1.0, max(m.strength, c.strength) + 0.1 * min(n_before, 2))
            m.evidence += [e for e in c.evidence if e not in m.evidence]
            m.category = m.category or c.category
            m.span = m.span or c.span
        else:
            merged.append(c)
    for i, c in enumerate(merged):
        c.id = i
    return merged


def _locate_quote(words: list[dict], quote: str) -> tuple[float, float] | None:
    q = normalize(quote).split()
    toks = [normalize(w["word"]) for w in words]
    if not q:
        return None
    n = len(q)
    for i in range(len(toks) - n + 1):
        if toks[i:i + n] == q:
            return words[i]["start"], words[i + n - 1]["end"]
    # partial: first 4 words
    k = min(4, n)
    for i in range(len(toks) - k + 1):
        if toks[i:i + k] == q[:k]:
            return words[i]["start"], words[min(len(words) - 1, i + n - 1)]["end"]
    return None


# ------------------------------------------------------------------ rules decision
def _allowed(policy: PlannerPolicy, cfg: EditConfig) -> set[str]:
    allowed = set(policy.allowed_effects)
    if not cfg.zoom:
        allowed -= set(VISUAL_ZOOMS)
    if not cfg.effects:
        allowed -= {"flash", "shake"}
    if not (cfg.caption_emphasis and cfg.subtitles):
        allowed.discard("caption_emphasis")
    return allowed


def _choose_effect(c: Candidate, policy: PlannerPolicy, allowed: set[str]) -> str:
    pref = {"reaction": policy.reaction_effect, "highlight": policy.highlight_effect,
            "action": policy.action_effect}[c.kind]
    if c.kind == "reaction" and c.strength >= 0.9 and "shake" in allowed:
        pref = "shake"
    if c.kind == "action" and c.strength >= 0.85 and "flash" in allowed and any("lampo" in e for e in c.evidence):
        pref = "flash"
    if pref in allowed:
        return pref
    for alt in ("subtle_zoom", "punch_zoom", "progressive_zoom", "caption_emphasis"):
        if alt in allowed and pref != "none":
            return alt
    return "none"


def _extent(effect: str, c: Candidate, policy: PlannerPolicy, d: float) -> tuple[float, float]:
    t = c.t
    if c.span and effect in ("progressive_zoom", "subtle_zoom", "caption_emphasis"):
        a, b = c.span[0] - (1.2 if effect == "progressive_zoom" else 0.2), c.span[1] + 0.3
    elif effect == "punch_zoom":
        a, b = t - 0.12, t + 1.4
    elif effect == "progressive_zoom":
        a, b = t - 1.6, t + 0.6
    elif effect == "flash":
        a, b = t - 0.05, t + 0.35
    elif effect == "shake":
        a, b = t - 0.05, t + 0.6
    else:
        a, b = t - 0.4, t + 1.6
    b = min(b, a + policy.max_effect_s)
    return max(0.0, a), min(d, b)


def _sfx_for(effect: str, c: Candidate) -> str | None:
    if c.category == "funny":
        return "pop"
    if c.category in ("clutch", "epic") and effect not in ("punch_zoom", "shake"):
        return "ding"
    return {"punch_zoom": "impact", "shake": "impact", "flash": "impact", "progressive_zoom": "riser",
            "subtle_zoom": "whoosh"}.get(effect)


def decide_rules(cands: list[Candidate], policy: PlannerPolicy, cfg: EditConfig, d: float) -> list[dict]:
    """Decision per candidate: {"id", "effect", "intensity", "sfx", "reason"} (budget applied later)."""
    allowed = _allowed(policy, cfg)
    out = []
    for c in cands:
        if c.strength < policy.min_strength:
            out.append({"id": c.id, "effect": "none", "reason": f"Troppo debole ({c.strength:.2f}): lascio il video normale"})
            continue
        eff = _choose_effect(c, policy, allowed)
        if eff == "none":
            out.append({"id": c.id, "effect": "none", "reason": "Nessun effetto adatto consentito dal preset"})
            continue
        sfx = _sfx_for(eff, c) if c.strength >= policy.sfx_min_strength else None
        out.append({"id": c.id, "effect": eff, "intensity": 0.35 + 0.65 * c.strength, "sfx": sfx,
                    "reason": "; ".join(c.evidence)})
    return out


# ------------------------------------------------------------------ limits (applied to any decision)
def enforce(decisions: list[dict], cands: list[Candidate], policy: PlannerPolicy, cfg: EditConfig,
            d: float) -> tuple[list[PlanSegment], list[str], dict[int, str]]:
    """Returns (effect segments, notes, why each other candidate got 'none')."""
    by_id = {c.id: c for c in cands}
    allowed = _allowed(policy, cfg)
    notes: list[str] = []
    max_effects = max(1, int(math.floor(policy.max_effects_per_min * d / 60 + 0.5))) if policy.max_effects_per_min else 0
    max_sfx = int(math.floor(policy.sfx_per_min * d / 60 + 0.5)) if (cfg.sfx and policy.sfx_per_min) else 0
    if cfg.sfx and policy.sfx_per_min and d >= 8:
        max_sfx = max(1, max_sfx)
    # strongest first so the budget goes to the best moments
    order = sorted((x for x in decisions if x.get("id") in by_id), key=lambda x: -by_id[x["id"]].strength)
    chosen: list[PlanSegment] = []
    sfx_times: list[float] = []
    why: dict[int, str] = {}
    for dec in order:
        c = by_id[dec["id"]]
        eff = dec.get("effect", "none")
        if eff == "none":
            why[c.id] = dec.get("reason") or "Nessun effetto necessario"
            continue
        if eff not in allowed:
            notes.append(f"Effetto '{eff}' non consentito (candidato {c.id}): ignorato")
            why[c.id] = f"Effetto '{eff}' non consentito dal preset/impostazioni"
            continue
        if len(chosen) >= max_effects:
            why[c.id] = f"Limite di {max_effects} effetti per questa clip già raggiunto"
            continue
        a, b = _extent(eff, c, policy, d)
        if b - a < 0.15:
            why[c.id] = "Troppo vicino al bordo della clip"
            continue
        if any(a < s.end + policy.min_gap_s and b > s.start - policy.min_gap_s for s in chosen):
            why[c.id] = f"A meno di {policy.min_gap_s:.0f} s da un effetto più forte: evito effetti continui"
            continue
        intensity = float(np.clip(float(dec.get("intensity", 0.6)), 0.0, 1.0)) * policy.intensity_scale * \
            (0.4 + 0.6 * cfg.intensity) / 0.76  # cfg.intensity 0.6 → ×1
        sfx = None
        cat = dec.get("sfx")
        if cat and max_sfx and len(sfx_times) < max_sfx and c.strength >= policy.sfx_min_strength * 0.9:
            at = c.t if eff != "progressive_zoom" else a
            if all(abs(at - t) >= policy.sfx_min_gap_s for t in sfx_times):
                sfx = SfxCue(category=cat, volume=round(cfg.sfx_volume * (0.6 + 0.4 * c.strength), 2),
                             at=round(max(0.0, at - (0.0 if cat != "riser" else 0.0)), 3))
                sfx_times.append(at)
        chosen.append(PlanSegment(start=a, end=b, effect=eff, intensity=min(1.0, intensity),
                                  reason=dec.get("reason") or "; ".join(c.evidence), sfx=sfx, candidate=c.id))
    return chosen, notes, why


# ------------------------------------------------------------------ emphasis & pauses
def choose_emphasis(inp: PlannerInput, cands: list[Candidate], policy: PlannerPolicy, cfg: EditConfig,
                    forced: list[int] | None = None) -> list[EmphasisWord]:
    if not (cfg.subtitles and cfg.caption_emphasis) or not inp.words or policy.emphasis_per_min <= 0:
        return []
    n_max = max(1, int(policy.emphasis_per_min * inp.duration / 60 + 0.5))
    total = max(1, inp.total_words)
    scored: list[tuple[float, int, str]] = []
    strong_times = [c.t for c in cands if c.strength >= policy.min_strength]
    for i, w in enumerate(inp.words):
        tok = normalize(w["word"])
        if not tok or tok in STOPWORDS or (len(tok) < 4 and not tok.isdigit()):
            continue
        count = inp.word_counts.get(tok, 1)
        rarity = math.log((total + 1) / count) / math.log(total + 1)   # 0 common … 1 unique in the video
        score = rarity
        reason = "parola rara nel video"
        if tok.isdigit() or any(ch.isdigit() for ch in tok):
            score += 0.3
            reason = "numero"
        if any(abs(w["start"] - t) <= 1.2 for t in strong_times):
            score += 0.35
            reason = "parola nel momento più forte"
        scored.append((score, i, reason))
    if forced:
        for i in forced:
            if 0 <= i < len(inp.words):
                tok = normalize(inp.words[i]["word"])
                if tok and tok not in STOPWORDS and (len(tok) >= 4 or tok.isdigit()):
                    scored.append((10.0, i, "scelta dall'AI planner"))
    picked: list[EmphasisWord] = []
    used: set[int] = set()
    for score, i, reason in sorted(scored, key=lambda x: -x[0]):
        if len(picked) >= n_max or score < 0.55:
            break
        w = inp.words[i]
        if i in used or any(abs(w["start"] - p.start) < 1.5 for p in picked):
            continue
        used.add(i)
        picked.append(EmphasisWord(start=w["start"], end=w["end"], word=w["word"].strip(), reason=reason))
    return picked


def decide_pauses(inp: PlannerInput, cands: list[Candidate], policy: PlannerPolicy, cfg: EditConfig,
                  forced_keep: list[int] | None = None) -> list[PauseDecision]:
    if not cfg.remove_silences or not inp.words:
        return []
    words = sorted(inp.words, key=lambda w: w["start"])
    out: list[PauseDecision] = []
    prev = 0.0
    gaps = []
    for w in words:
        if w["start"] - prev >= cfg.min_silence_s:
            gaps.append((prev, w["start"]))
        prev = max(prev, w["end"])
    if inp.duration - prev >= cfg.min_silence_s:
        gaps.append((prev, inp.duration))
    strong = [c for c in cands if c.strength >= max(0.6, policy.min_strength)]
    # same rule as the timeline (timeline.compute_segments): with the "quiet" strategy only pauses that are
    # also quiet are cut — a pause filled with game audio / music stays
    quiet_thr = None
    if cfg.silence_strategy == "quiet" and inp.rms_db is not None and len(inp.rms_db):
        quiet_thr = float(np.median(inp.rms_db)) - 6.0

    def loud(a: float, b: float) -> bool:
        if quiet_thr is None:
            return False
        i0 = int(a / inp.window_s)
        i1 = max(i0 + 1, int(b / inp.window_s))
        seg = inp.rms_db[i0:i1]
        return len(seg) > 0 and float(seg.mean()) >= quiet_thr

    for gi, (a, b) in enumerate(gaps):
        if loud(a, b):
            out.append(PauseDecision(start=round(a, 3), end=round(b, 3), action="keep",
                                     reason="Pausa nel parlato ma con audio (gioco/musica): non la taglio"))
            continue
        keep_reason = ""
        if policy.keep_dramatic_pauses and b - a <= 1.6 and a > 0.3:
            nxt = [c for c in strong if b - 0.2 <= c.t <= b + 1.0]
            if nxt:
                keep_reason = "Pausa drammatica prima del culmine: la tengo"
        if forced_keep and gi in forced_keep and b - a <= 2.0:
            keep_reason = keep_reason or "L'AI planner tiene questa pausa (ritmo/battuta)"
        out.append(PauseDecision(start=round(a, 3), end=round(b, 3), action="keep" if keep_reason else "cut",
                                 reason=keep_reason or "Pausa senza contenuto: taglio"))
    return out


# ------------------------------------------------------------------ local LLM refinement
LLM_PROMPT = """Sei un montatore professionista di video verticali ({preset}). Clip di {dur:.0f} s{game}.
Decidi QUANDO applicare un effetto e QUANDO NON applicarlo. Un buon montaggio usa pochi effetti, solo dove servono:
scegli "none" per dialoghi normali, spiegazioni, momenti deboli. Non mettere effetti a caso.

Effetti consentiti: {allowed}
- subtle_zoom: zoom leggero, per sottolineare una frase importante
- progressive_zoom: zoom lento che costruisce tensione verso un culmine
- punch_zoom: zoom rapido su urla, sorprese, reazioni forti
- caption_emphasis: solo evidenziare il sottotitolo
- flash / shake: solo per impatti fortissimi (esplosioni, urla estreme)
Massimo {max_effects} effetti in tutta la clip. Effetti sonori ({sfx_cats}): {sfx_rule}

TRASCRIZIONE (indice parola: testo, con secondi):
{transcript}

MOMENTI CANDIDATI (trovati dall'analisi audio/testo/video):
{candidates}
{pauses}
Rispondi SOLO con JSON:
{{"decisions": [{{"id": <id candidato>, "effect": "<effetto o none>", "intensity": <0.0-1.0>, "sfx": "<categoria o none>", "reason": "<motivo breve in italiano>"}}],
  "emphasis_words": [<indici delle parole più importanti da evidenziare, max {max_emph}>]{pause_field}}}
Includi una decisione per OGNI candidato."""


def _llm_model() -> str | None:
    from backend.clip_detection import semantic

    st = semantic.status()
    return st["model"] if st.get("available") else None


def decide_llm(inp: PlannerInput, cands: list[Candidate], policy: PlannerPolicy, cfg: EditConfig,
               pauses: list[PauseDecision], *, client: httpx.Client | None = None,
               model: str | None = None) -> tuple[list[dict], list[int], list[int]]:
    """Returns (decisions, emphasis word indices, pause indices to keep). Raises on any failure."""
    from backend.clip_detection import semantic

    allowed = sorted(_allowed(policy, cfg)) + ["none"]
    lines, cur, cur_t = [], [], None
    for i, w in enumerate(inp.words):
        if cur_t is None:
            cur_t = w["start"]
        cur.append(f"{i}:{w['word'].strip()}")
        if len(cur) >= 12:
            lines.append(f"({cur_t:.1f}s) " + " ".join(cur))
            cur, cur_t = [], None
    if cur:
        lines.append(f"({cur_t:.1f}s) " + " ".join(cur))
    transcript = "\n".join(lines)[:5000] or "(nessun parlato)"
    cand_txt = "\n".join(f"[{c.id}] {c.t:.1f}s {c.kind} forza={c.strength:.2f}: {'; '.join(c.evidence)}"
                         for c in cands)
    max_effects = max(1, int(policy.max_effects_per_min * inp.duration / 60 + 0.5))
    sfx_on = cfg.sfx and policy.sfx_per_min > 0
    pause_txt, pause_field = "", ""
    if pauses:
        pause_txt = "\nPAUSE (di default vengono tagliate):\n" + "\n".join(
            f"<{i}> {p.start:.1f}-{p.end:.1f}s" for i, p in enumerate(pauses)) + "\n"
        pause_field = ',\n  "keep_pauses": [<indici delle pause da NON tagliare perché danno ritmo a una battuta>]'
    preset = get_preset(cfg.preset)
    prompt = LLM_PROMPT.format(
        preset=preset.name, dur=inp.duration, game=f" ({inp.game})" if inp.game else "",
        allowed=", ".join(allowed), max_effects=max_effects,
        sfx_cats="whoosh, impact, pop, riser, ding",
        sfx_rule=("al massimo uno ogni pochi secondi, solo sui momenti più forti, altrimenti \"none\"" if sfx_on
                  else "disattivati: usa sempre \"none\""),
        transcript=transcript, candidates=cand_txt, pauses=pause_txt, pause_field=pause_field,
        max_emph=max(1, int(policy.emphasis_per_min * inp.duration / 60 + 0.5)))
    model = model or _llm_model()
    if not model:
        raise RuntimeError("LLM locale non disponibile")
    own = client is None
    client = client or httpx.Client(timeout=get_settings().llm_timeout_s)
    try:
        raw = semantic._generate(client, model, prompt, temperature=0.2, keep_alive=0)
    finally:
        if own:
            client.close()
    if not isinstance(raw, dict) or not isinstance(raw.get("decisions"), list):
        raise ValueError("risposta LLM senza 'decisions'")
    ids = {c.id for c in cands}
    decisions = []
    for d in raw["decisions"]:
        if not isinstance(d, dict):
            continue
        try:
            cid = int(re.sub(r"\D", "", str(d.get("id"))) or -1)
        except ValueError:
            continue
        eff = str(d.get("effect", "none")).strip().lower()
        if cid not in ids or eff not in allowed:
            continue
        sfx = str(d.get("sfx", "none")).strip().lower()
        decisions.append({"id": cid, "effect": eff, "intensity": d.get("intensity", 0.6),
                          "sfx": sfx if sfx in ("whoosh", "impact", "pop", "riser", "ding") and sfx_on else None,
                          "reason": "AI: " + str(d.get("reason", ""))[:180]})
    emph = [int(x) for x in raw.get("emphasis_words", []) if str(x).isdigit()]
    keep = [int(x) for x in raw.get("keep_pauses", []) if str(x).isdigit()]
    return decisions, emph, keep


# ------------------------------------------------------------------ entry point
def plan_key(inp: PlannerInput, cfg: EditConfig) -> str:
    p = get_preset(cfg.preset)
    relevant = {k: getattr(cfg, k) for k in ("preset", "intensity", "planner", "zoom", "effects", "caption_emphasis",
                                             "subtitles", "sfx", "sfx_volume", "remove_silences", "min_silence_s")}
    h = hashlib.sha1(json.dumps({"v": PLAN_VERSION, "cfg": relevant, "policy": p.policy.model_dump(),
                                 "d": round(inp.duration, 2), "peak": inp.peak, "hook": inp.hook,
                                 "w": [(round(w["start"], 2), w["word"]) for w in inp.words]},
                                sort_keys=True, default=str).encode()).hexdigest()
    return h[:16]


def make_plan(inp: PlannerInput, cfg: EditConfig, *, client: httpx.Client | None = None,
              model: str | None = None) -> EditPlan:
    preset = get_preset(cfg.preset)
    policy = preset.policy
    d = max(0.2, inp.duration)
    cands = find_candidates(inp)
    pauses = decide_pauses(inp, cands, policy, cfg)
    notes: list[str] = []
    source = "rules"
    emph_forced: list[int] | None = None
    decisions = decide_rules(cands, policy, cfg, d)
    if cfg.planner == "auto" and cands and _allowed(policy, cfg):
        try:
            llm_dec, emph_forced, keep = decide_llm(inp, cands, policy, cfg, pauses, client=client, model=model)
            if llm_dec:
                decided = {x["id"] for x in llm_dec}
                # candidates the LLM skipped: explicit none (it was asked to answer for all)
                decisions = llm_dec + [{"id": c.id, "effect": "none", "reason": "AI: nessuna decisione → none"}
                                       for c in cands if c.id not in decided]
                source = "llm"
                if keep:
                    pauses = decide_pauses(inp, cands, policy, cfg, forced_keep=keep)
            else:
                notes.append("L'AI planner non ha restituito decisioni valide: uso le regole")
        except (httpx.HTTPError, ValueError, KeyError, RuntimeError, TypeError) as e:
            log.info("LLM planner unavailable (%s): rules plan", e)
            notes.append(f"AI planner locale non disponibile ({str(e)[:80]}): piano a regole")
    segments, limit_notes, why = enforce(decisions, cands, policy, cfg, d)
    notes += limit_notes
    none_reasons = [PlanSegment(start=max(0.0, min(c.t, d - 0.2)), end=min(d, max(c.t, 0.0) + 0.2), effect="none",
                                reason=f"{c.evidence[0]} → none: {why.get(c.id, 'nessun effetto necessario')}")
                    for c in cands if c.id not in {s.candidate for s in segments}]
    emphasis = choose_emphasis(inp, cands, policy, cfg, forced=emph_forced)
    if not cands:
        notes.append("Nessun momento forte trovato: nessun effetto (scelta voluta)")
    try:
        return EditPlan(preset=preset.id, source=source, duration=d, segments=segments + none_reasons,
                        emphasis=emphasis, pauses=pauses, candidates=[c.as_dict() for c in cands],
                        notes=notes[:20], key=plan_key(inp, cfg))
    except ValidationError as e:  # should never happen: fall back to a plan with no effects at all
        log.error("Invalid plan, using an empty one: %s", e)
        return EditPlan(preset=preset.id, duration=d, notes=["Piano non valido: nessun effetto"],
                        key=plan_key(inp, cfg))


def empty_plan(d: float, preset: str = "custom") -> EditPlan:
    return EditPlan(preset=preset, duration=max(0.2, d), notes=["Nessun piano: video senza effetti"])


# ------------------------------------------------------------------ renderer helpers
def _smooth(v: float) -> float:
    v = min(1.0, max(0.0, v))
    return v * v * (3 - 2 * v)


def zoom_envelope(plan: EditPlan, t: float) -> float:
    """0..1 zoom amount at clip-relative t (× EditConfig.zoom_strength in the compositor)."""
    e = 0.0
    for s in plan.segments:
        if s.effect not in VISUAL_ZOOMS or t < s.start or t > s.end + 0.6:
            continue
        a, b, k = s.start, s.end, s.intensity
        if s.effect == "punch_zoom":
            ramp_in, out = 0.12, 0.45
            v = _smooth((t - a) / ramp_in) if t < b else 1 - _smooth((t - b) / out)
            amp = k
        elif s.effect == "progressive_zoom":
            out = 0.5
            v = ((t - a) / max(0.1, b - a)) if t < b else 1 - _smooth((t - b) / out)
            v = min(1.0, max(0.0, v)) ** 1.2 if t < b else v
            amp = k * 0.9
        else:  # subtle
            ramp_in, out = 0.6, 0.7
            v = _smooth((t - a) / ramp_in) if t < b else 1 - _smooth((t - b) / out)
            amp = k * 0.55
        e = max(e, max(0.0, v) * amp)
    return float(min(1.0, e))


def flash_amount(plan: EditPlan, t: float) -> float:
    for s in plan.effect_segments("flash"):
        if s.start <= t <= s.start + 0.3:
            x = (t - s.start) / 0.3
            return float(s.intensity * 0.85 * (1 - x) ** 2)
    return 0.0


def shake_offset(plan: EditPlan, t: float) -> tuple[int, int]:
    for s in plan.effect_segments("shake"):
        if s.start <= t <= s.end:
            decay = 1 - (t - s.start) / max(0.05, s.end - s.start)
            amp = 22 * s.intensity * decay
            return int(amp * math.sin(t * 63.0)), int(amp * 0.7 * math.cos(t * 51.0))
    return 0, 0
