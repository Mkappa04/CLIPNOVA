"""AI Video Director: understands the clip, then decides *how much* editing it deserves and of what kind.

It works on top of the planner's candidates (moments with written-out evidence) and adds:

1. **Moment types** — funny, spectacular, competitive, narrative, emotional, informative, tension, or
   ``action_only``: on-screen movement with nothing else behind it. Movement alone does not make a moment
   interesting, so those candidates are demoted and normally get no effect.
2. **Clip reading** — energy (strength of the moments, speech pace, motion, scene cuts, audio bursts),
   speech coverage, whether the original audio already carries music (estimate), and comprehensibility:
   would a viewer who does not know the game or the context understand it? (semantic "autonomia",
   speech, visual description).
3. **Style** — the preset gives a base style and a budget; the Director goes calmer when the content
   asks for it (a quiet explanation in a "Gaming Dynamic" clip gets a minimal edit). Each style scales
   the budget: minimal 0.4, balanced 0.75, energetic 1, cinematic 0.7.
4. **Decisions beyond accents** — time effects (slow motion / speed ramp / freeze frame only where nobody
   is talking and the moment is strong), transitions on jump cuts, motion graphics (hook title when the
   clip needs context, callouts with verbatim words), standalone sounds (riser into a slow motion, bass
   drop on the climax), music (mood from the moments, licensed track from the library, beat-sync point,
   level and ducking), colour look.

Everything is deterministic given the inputs (a seed from the clip id gives variety between clips, not
between runs). The local LLM, when used, can only pick among these options (planner.decide_llm).
"""

from __future__ import annotations

import hashlib
import math
import re
from typing import TYPE_CHECKING, Any

import numpy as np

from backend.clip_detection.lexicon import normalize
from backend.editing.plan import (
    MUSIC_MOODS, DirectorSummary, Look, Moment, MusicCue, SoundCue, TextOverlay, TimeEffect, Transition, SfxCue,
    item_id)

if TYPE_CHECKING:
    from backend.editing.config import EditConfig
    from backend.editing.planner import Candidate, PlannerInput
    from backend.editing.presets import PlannerPolicy

BUDGET = {"minimal": 0.4, "balanced": 0.75, "energetic": 1.0, "cinematic": 0.7}

# lexicon category → moment type (lexicon: funny, rage, epic, fail, reaction, clutch, unexpected)
LEX_TYPE = {"funny": "funny", "fail": "funny", "rage": "tension", "epic": "spectacular", "clutch": "competitive",
            "unexpected": "spectacular", "reaction": "emotional"}
# clip category (detection) → prior
CATEGORY_TYPE = {"funny": "funny", "fail": "funny", "epic": "spectacular", "gameplay_highlight": "spectacular",
                 "clutch": "competitive", "rage": "tension", "reaction": "emotional", "storytelling": "narrative",
                 "educational": "informative", "informative": "informative", "unexpected": "spectacular"}
# semantic payoff (tipo_culmine) → type
PAYOFF_TYPE = {"battuta": "funny", "storia_con_finale": "narrative", "rivelazione": "informative",
               "reazione_forte": "emotional", "scontro": "competitive", "fatto_sorprendente": "spectacular"}
MOOD_FOR_TYPE = {"funny": ["gaming", "electronic", "chill"], "spectacular": ["dynamic", "electronic", "cinematic"],
                 "competitive": ["gaming", "dynamic", "electronic"], "tension": ["dramatic", "cinematic"],
                 "emotional": ["cinematic", "chill"], "narrative": ["cinematic", "chill"],
                 "informative": ["chill", "cinematic"], "action_only": ["dynamic", "electronic"]}
CONTINUATION = {"e", "ed", "ma", "quindi", "perché", "perche", "poi", "cioè", "and", "but", "so", "because", "then"}
STOP = {"che", "non", "per", "con", "una", "uno", "sono", "questo", "questa", "quello", "the", "and", "you", "that",
        "this", "what", "with", "have", "della", "dello", "delle", "degli", "nella", "anche", "come", "cosa"}


def seed_for(*parts: Any) -> int:
    return int(hashlib.sha1("|".join(map(str, parts)).encode()).hexdigest()[:8], 16)


# ------------------------------------------------------------------ reading the clip
def speech_coverage(words: list[dict], a: float, b: float) -> float:
    if b <= a:
        return 0.0
    covered = 0.0
    for w in words:
        covered += max(0.0, min(b, w["end"]) - max(a, w["start"]))
    return min(1.0, covered / (b - a))


def _frac(x: np.ndarray | None, thr: float, z: bool = False) -> float:
    if x is None or len(x) == 0:
        return 0.0
    x = np.asarray(x, np.float64)
    if z:
        med = float(np.median(x))
        mad = float(np.median(np.abs(x - med))) or 1e-6
        x = (x - med) / (1.4826 * mad)
    return float(np.mean(x > thr))


def original_music_likely(inp: PlannerInput) -> bool:
    """Estimate: a steady, fairly loud bed in the parts without speech (game soundtrack, intro music…)."""
    r = inp.rms_db
    if r is None or len(r) < 8:
        return False
    ws = inp.window_s
    idx_speech = np.zeros(len(r), bool)
    for w in inp.words:
        idx_speech[int(w["start"] / ws): int(w["end"] / ws) + 1] = True
    quiet = r[~idx_speech[: len(r)]]
    if len(quiet) < 0.3 * len(r) or len(quiet) < 6:
        return False
    loud_enough = float(np.median(quiet)) > -38.0
    steady = float(np.std(quiet)) < 3.0
    if idx_speech.any():
        loud_enough = loud_enough and float(np.median(quiet)) > float(np.median(r[idx_speech[: len(r)]])) - 12
    return bool(loud_enough and steady)


def classify(c: Candidate, inp: PlannerInput) -> str:
    """Moment type of one candidate, from every signal that points at it."""
    score: dict[str, float] = {}

    def add(t: str | None, w: float) -> None:
        if t:
            score[t] = score.get(t, 0.0) + w

    ev = " ".join(c.evidence).lower()
    add(LEX_TYPE.get(c.category), 2.0)
    if "risata" in ev:
        add("funny", 2.0)
    if "lampo" in ev or "esplosione" in ev:
        # a flash with a sound burst is an explosion / hit; a flash alone is often just a cut or a bright frame
        add("spectacular", 1.5 if "picco audio" in ev else 0.4)
    if "senza voce" in ev and "picco audio" in ev:
        add("spectacular", 1.0)
    if "urlo" in ev:
        add("emotional", 0.8)
        add("competitive", 0.4 if inp.category in ("clutch", "epic") else 0.0)
    if "battuta chiave" in ev or "picco della clip" in ev:
        add(PAYOFF_TYPE.get(str(inp.semantic.get("payoff_type", "")).lower()), 1.6)
        add(CATEGORY_TYPE.get(inp.category), 1.2)
    else:
        add(CATEGORY_TYPE.get(inp.category), 0.6)
    kind = str(inp.visual.get("kind", "")).lower()
    if "sport" in kind:
        add("competitive", 0.7)
        add("spectacular", 0.5)
    elif "podcast" in kind or "parla" in kind:
        add("narrative", 0.5)
        add("informative", 0.5)
    if c.kind == "highlight" and _speech_near(inp.words, c.t, 1.0):
        add("narrative", 0.5)
    # rising loudness over the 3 s before the moment = build-up
    r = inp.rms_db
    if r is not None and len(r) > 8:
        i = int(c.t / inp.window_s)
        j = max(0, i - int(3.0 / inp.window_s))
        if i - j >= 4 and float(np.mean(r[i - 2:i + 1])) - float(np.mean(r[j:j + 2])) > 6:
            add("tension", 0.9)
    only_motion = all("movimento improvviso" in e for e in c.evidence)
    if only_motion and not score:
        return "action_only"
    if not score:
        return "emotional" if c.kind == "reaction" else "spectacular" if c.kind == "action" else "narrative"
    return max(score.items(), key=lambda kv: (kv[1], kv[0]))[0]


def _speech_near(words: list[dict], t: float, r: float = 1.0) -> bool:
    return any(w["start"] - r <= t <= w["end"] + r for w in words)


def comprehensibility(inp: PlannerInput, coverage: float) -> float:
    c = 0.6
    auto = inp.semantic.get("standalone")
    if isinstance(auto, (int, float)) and not isinstance(auto, bool):
        c = 0.3 + 0.14 * (min(5.0, max(1.0, float(auto))) - 1)
    elif isinstance(auto, bool):
        c = 0.75 if auto else 0.4
    if coverage < 0.1 and not inp.visual:
        c -= 0.15
    if inp.visual and float(inp.visual.get("confidence", 0) or 0) >= 0.6 and inp.visual.get("action"):
        c += 0.05
    if inp.words and normalize(inp.words[0]["word"]) in CONTINUATION:
        c -= 0.1   # starts in the middle of a thought
    return round(min(1.0, max(0.0, c)), 2)


def analyse(inp: PlannerInput, cands: list[Candidate], policy: PlannerPolicy) -> DirectorSummary:
    """Classify the candidates (demoting movement-only ones in place) and read the clip as a whole."""
    d = max(0.2, inp.duration)
    moments: list[Moment] = []
    for c in cands:
        c.moment = classify(c, inp)
        if c.moment == "action_only":
            c.strength = round(c.strength * 0.55, 3)
            c.evidence.append("solo movimento: non basta a renderlo un momento interessante")
        moments.append(Moment(candidate=c.id, t=round(c.t, 2), type=c.moment, strength=round(c.strength, 2),
                              evidence="; ".join(c.evidence)[:200]))
    coverage = speech_coverage(inp.words, 0.0, d)
    wps = len(inp.words) / d
    strengths = sorted((c.strength for c in cands), reverse=True)[:3]
    top = float(np.mean(strengths)) if strengths else 0.0
    motion_frac = _frac(inp.motion, 1.5, z=True)
    excess_frac = _frac(inp.excess_db, 6.0)
    cuts = len([s for s in inp.scenes if 0 < s < d])
    energy = 0.45 * top + 0.2 * min(1.0, wps / 3.5) + 0.15 * min(1.0, motion_frac * 3) + \
        0.1 * min(1.0, cuts / max(1.0, d / 10) / 4) + 0.1 * min(1.0, excess_frac * 5)
    energy = round(min(1.0, energy), 2)

    weights: dict[str, float] = {}
    for m in moments:
        if m.type != "action_only":
            weights[m.type] = weights.get(m.type, 0.0) + m.strength
    dominant = max(weights.items(), key=lambda kv: kv[1])[0] if weights else None
    if dominant is None and CATEGORY_TYPE.get(inp.category):
        dominant = CATEGORY_TYPE[inp.category]

    base = policy.style
    style = base
    notes: list[str] = []
    strong = any(c.strength >= policy.min_strength for c in cands)
    if base != "minimal":
        if base == "energetic" and (energy < 0.22 or not strong):
            style = "minimal"
        elif base == "energetic" and (energy < 0.4 or dominant in ("informative", "narrative")):
            style = "balanced"
        elif base in ("balanced", "cinematic") and (energy < 0.2 or not strong):
            style = "minimal"
    if style != base:
        notes.append(f"Contenuto più calmo del preset: stile {style} invece di {base}")
    comp = comprehensibility(inp, coverage)
    if comp < 0.5:
        notes.append("La clip si capisce poco senza contesto: serve un titolo che la introduca")
    orig_music = original_music_likely(inp)
    if orig_music:
        notes.append("L'audio originale sembra avere già un fondo musicale (stima): musica più bassa")
    return DirectorSummary(style=style, energy=energy, comprehensibility=comp, dominant=dominant, moments=moments,
                           speech_coverage=round(coverage, 2), words_per_s=round(wps, 2), scene_cuts=cuts,
                           original_music=orig_music, content_kind=str(inp.visual.get("kind", "")), notes=notes)


def scaled_policy(policy: PlannerPolicy, style: str) -> PlannerPolicy:
    m = BUDGET.get(style, 1.0)
    upd = {"max_effects_per_min": policy.max_effects_per_min * m, "sfx_per_min": policy.sfx_per_min * m,
           "emphasis_per_min": policy.emphasis_per_min * (1.0 if style != "minimal" else 0.7),
           "max_time_effects": 0 if style == "minimal" else policy.max_time_effects,
           "max_callouts": 0 if style == "minimal" else policy.max_callouts}
    return policy.model_copy(update=upd)


# ------------------------------------------------------------------ accents per moment type
def effect_for_moment(c: Candidate, policy: PlannerPolicy, allowed: set[str], style: str) -> str | None:
    """Preferred accent for the candidate's moment type, None = let the preset's kind mapping decide."""
    m = getattr(c, "moment", "")
    ev = " ".join(c.evidence)
    energetic = style == "energetic"
    prefs: list[str]
    if m == "action_only":
        return "none"
    if m == "funny":
        prefs = (["glitch"] if energetic and c.category in ("fail", "unexpected") and c.strength >= 0.8 else []) + \
            (["punch_zoom"] if energetic else ["subtle_zoom", "punch_zoom"])
    elif m == "spectacular":
        prefs = (["flash"] if "lampo" in ev and "picco audio" in ev and c.strength >= 0.85 else []) + \
            (["punch_zoom", "progressive_zoom"] if energetic else ["progressive_zoom", "subtle_zoom"])
    elif m == "competitive":
        prefs = (["shake"] if energetic and c.kind == "reaction" and c.strength >= 0.9 else []) + \
            (["punch_zoom"] if energetic else ["progressive_zoom", "subtle_zoom"])
    elif m == "tension":
        prefs = ["progressive_zoom", "subtle_zoom"]
    elif m == "emotional":
        prefs = {"cinematic": ["progressive_zoom", "subtle_zoom"], "energetic": ["punch_zoom", "subtle_zoom"]}.get(
            style, ["subtle_zoom", "punch_zoom"])
    elif m == "narrative":
        prefs = ["subtle_zoom", "caption_emphasis"]
    elif m == "informative":
        prefs = ["caption_emphasis", "subtle_zoom"]
    else:
        return None
    for p in prefs:
        if p in allowed:
            return p
    return None


def sfx_for_moment(effect: str, c: Candidate) -> str | None:
    m = getattr(c, "moment", "")
    ev = " ".join(c.evidence)
    if m in ("narrative", "informative", "emotional") and effect not in ("punch_zoom", "shake"):
        return None
    if m == "funny":
        return "pop" if effect != "glitch" else "gaming"
    if m == "spectacular" and "lampo" in ev and "picco audio" in ev:
        return "explosion"
    if m == "competitive":
        return "hit"
    if m == "tension":
        return "riser"
    return {"punch_zoom": "impact", "shake": "impact", "flash": "impact", "progressive_zoom": "riser",
            "subtle_zoom": "whoosh", "glitch": "gaming"}.get(effect)


# ------------------------------------------------------------------ beyond accents
def _cut_pauses(pauses) -> list[tuple[float, float]]:
    return [(p.start, p.end) for p in pauses if p.action == "cut"]


def plan_time_effects(inp: PlannerInput, cands: list[Candidate], policy: PlannerPolicy, cfg: EditConfig,
                      pauses, hints: dict[int, str] | None = None) -> tuple[list[TimeEffect], list[str]]:
    notes: list[str] = []
    allowed = list(policy.allowed_time_effects)
    if not cfg.time_effects or not allowed or policy.max_time_effects <= 0:
        return [], notes
    d = inp.duration
    cut = _cut_pauses(pauses)
    out: list[TimeEffect] = []
    for c in sorted(cands, key=lambda c: -c.strength):
        if len(out) >= policy.max_time_effects:
            break
        if c.strength < policy.time_min_strength:
            break
        m = getattr(c, "moment", "")
        if hints is not None:
            kind = hints.get(c.id)
            if not kind or kind not in allowed:
                continue
        elif m in ("spectacular", "competitive") or (m == "tension" and policy.style == "cinematic"):
            kind = next((k for k in allowed if k in ("slow_motion", "speed_ramp")), None)
        elif m == "funny" or (m == "narrative" and c.strength >= 0.85 and policy.style != "energetic"):
            # narrative freeze = the storytelling beat; in gaming presets only gags get frozen
            kind = "freeze_frame" if "freeze_frame" in allowed else None
        else:
            kind = None
        if kind is None:
            continue
        t = c.t
        if kind == "freeze_frame":
            # never freeze in the middle of a word: move to the end of the word being spoken (if close)
            spoken = [w for w in inp.words if w["start"] < t < w["end"]]
            if spoken:
                if spoken[0]["end"] - t > 0.4:
                    notes.append(f"Fermo immagine a {t:.1f}s evitato: cadrebbe a metà di una parola")
                    continue
                t = spoken[0]["end"] + 0.02
            if not (0.5 <= t <= d - 0.5) or any(pa <= t <= pb for pa, pb in cut):
                continue
            hold = 0.7 if policy.style == "energetic" else 0.9
            out.append(TimeEffect(kind="freeze_frame", start=round(t, 3), hold=hold, intensity=c.strength,
                                  priority=2, candidate=c.id,
                                  reason=f"{_label(m)}: fermo immagine sul momento esatto ({c.evidence[0]})"))
            continue
        a, b = (t - 0.35, t + 1.1) if kind == "slow_motion" else (t - 0.9, t + 1.1)
        if policy.style == "cinematic" and kind == "slow_motion":
            a, b = t - 0.5, t + 1.4
        a, b = max(0.05, a), min(d - 0.1, b)
        if b - a < 0.6:
            continue
        cov = speech_coverage(inp.words, a, b)
        if cov > 0.3:
            notes.append(f"{_kind_it(kind)} a {t:.1f}s evitato: qualcuno sta parlando (rallenterebbe la voce)")
            continue
        if any(min(b, pb) - max(a, pa) > 0 for pa, pb in cut):
            continue
        speed = policy.slowmo_speed if kind == "slow_motion" else max(0.35, policy.slowmo_speed - 0.05)
        out.append(TimeEffect(kind=kind, start=round(a, 3), end=round(b, 3), speed=speed, intensity=c.strength,
                              priority=1 if c.strength >= 0.85 else 2, candidate=c.id,
                              reason=f"{_label(m)} senza parlato: {_kind_it(kind).lower()} per far vedere il momento "
                                     f"({c.evidence[0]})"))
    return out, notes


def plan_transitions(inp: PlannerInput, cands: list[Candidate], policy: PlannerPolicy, cfg: EditConfig, pauses,
                     style: str, sfx_on: bool) -> list[Transition]:
    if not cfg.transitions:
        return []
    kinds = list(policy.transition_kinds) or ["crossfade"]
    out: list[Transition] = []
    last_t, last_sfx = -99.0, -99.0
    for i, (a, b) in enumerate(_cut_pauses(pauses)):
        if a - last_t < 2.0:
            continue
        nxt = [c for c in cands if b - 0.1 <= c.t <= b + 1.5 and c.strength >= 0.6]
        if style == "minimal":
            kind, dur, why = "crossfade", 0.12, "taglio morbido (stile minimale)"
        elif style == "cinematic":
            kind, dur, why = ("dip", 0.3, "pausa lunga: passaggio al nero") if b - a > 1.5 else \
                ("crossfade", 0.25, "dissolvenza morbida (stile cinematografico)")
        elif style == "energetic":
            if nxt:
                kind, dur, why = "zoom_blur", 0.2, "il momento forte arriva subito dopo il taglio: transizione dinamica"
            elif "glitch" in kinds and (seed_for(inp.clip_id, i) % 3 == 0):
                kind, dur, why = "glitch", 0.16, "taglio di ritmo (gaming)"
            else:
                kind, dur, why = "crossfade", 0.12, "taglio pulito"
        else:
            kind, dur, why = "crossfade", 0.18, "dissolvenza breve sul taglio"
        if kind not in kinds:
            kind = "crossfade" if "crossfade" in kinds else kinds[0]
        sfx = None
        if sfx_on and policy.transition_sfx and kind in ("zoom_blur", "glitch") and a - last_sfx >= 6:
            sfx = SfxCue(category="whoosh" if kind == "zoom_blur" else "transition",
                         volume=round(cfg.sfx_volume * 0.7, 2), at=a)
            last_sfx = a
        out.append(Transition(kind=kind, at=round(a, 3), duration=dur, sfx=sfx, priority=3,
                              reason=f"Pausa {a:.1f}–{b:.1f}s tagliata: {why}"))
        last_t = a
    return out


def _clean_title(title: str, n: int = 46) -> str:
    from backend.subtitles.ass import strip_emoji

    t = strip_emoji(re.sub(r"[“”\"«»]", "", title or "")).strip(" .…-|")
    t = re.sub(r"\s*\|\s*.*$", "", t)  # "Title | Game" → "Title"
    if len(t) <= n:
        return t
    cut = t[:n].rsplit(" ", 1)[0]
    return cut.rstrip(",;:") + "…"


def _callout_text(c: Candidate, inp: PlannerInput) -> tuple[str, str] | None:
    """Verbatim text for a callout (never invented): on-screen text, the reaction keyword, or a spoken word."""
    ost = str(inp.visual.get("on_screen_text", "") or "").strip()
    if getattr(c, "moment", "") in ("competitive", "spectacular") and 2 <= len(ost) <= 14 and \
            re.fullmatch(r"[\w\s!?'’\-:]+", ost):
        return ost.upper(), "testo leggibile a schermo"
    for e in c.evidence:
        m = re.search(r"parola chiave “(.+?)”", e)
        if m:
            return m.group(1).upper()[:18], "parola detta nella clip"
    # no fallback to "the longest word nearby": on real clips it picked weak words (TROPPO, SAPESSE) —
    # a callout only appears when the evidence itself names the word
    return None


def plan_overlays(inp: PlannerInput, cands: list[Candidate], policy: PlannerPolicy, cfg: EditConfig,
                  summary: DirectorSummary, hold_times: list[float]) -> list[TextOverlay]:
    if not cfg.motion_graphics:
        return []
    out: list[TextOverlay] = []
    d = inp.duration
    style = summary.style
    if "hook_title" in policy.overlays and not cfg.intro and inp.title and \
            (summary.comprehensibility < 0.65 or style in ("energetic", "cinematic")):
        text = _clean_title(inp.title)
        if len(text) >= 3:
            anim = {"energetic": "pop", "cinematic": "fade"}.get(style, "slide")
            why = "la clip ha bisogno di contesto" if summary.comprehensibility < 0.65 else "aggancio nei primi secondi"
            out.append(TextOverlay(kind="hook_title", start=0.15, end=round(min(2.6, max(1.2, d * 0.3)), 2), text=text,
                                   animation=anim, position="top", evidence="titolo della clip", priority=2,
                                   reason=f"Titolo iniziale: {why}"))
    if "callout" in policy.overlays and policy.max_callouts > 0:
        n = 0
        for c in sorted(cands, key=lambda c: -c.strength):
            if n >= policy.max_callouts or c.strength < 0.7:
                break
            if getattr(c, "moment", "") not in ("funny", "competitive", "spectacular"):
                continue
            got = _callout_text(c, inp)
            if not got:
                continue
            text, ev = got
            start = c.t + (0.05 if not any(abs(c.t - h) < 0.2 for h in hold_times) else 0.0)
            out.append(TextOverlay(kind="callout", start=round(max(0.0, start), 3), end=round(min(d, start + 1.2), 3),
                                   text=text, animation="pop", position="upper", evidence=ev, priority=3,
                                   reason=f"{_label(c.moment)}: scritta sul momento ({ev})"))
            n += 1
    return out


def plan_look(cfg: EditConfig, policy: PlannerPolicy, summary: DirectorSummary) -> Look:
    if cfg.look == "none":
        return Look()
    vig = policy.vignette if cfg.vignette else 0.0
    if cfg.look != "auto":
        return Look(grade=cfg.look, intensity=max(0.4, policy.look_intensity), vignette=vig,
                    reason="Look scelto dall'utente")
    grade, why = policy.look, "look del preset"
    kind = summary.content_kind.lower()
    if summary.style == "cinematic" and summary.dominant in ("tension", "emotional", "spectacular"):
        grade, why = "cinematic", f"momento {_label(summary.dominant).lower()}: look cinematografico"
    elif "sport" in kind:
        grade, why = "punchy", "sport: colori decisi"
    elif "podcast" in kind or "parla" in kind:
        grade, why = "warm", "persone che parlano: pelle naturale, tono caldo leggero"
    if summary.style == "minimal":
        return Look(grade=grade, intensity=round(policy.look_intensity * 0.6, 2), vignette=round(vig * 0.5, 2),
                    reason=f"{why} (leggero, stile minimale)")
    return Look(grade=grade, intensity=policy.look_intensity, vignette=vig, reason=why)


def choose_track(catalog: list[dict], mood: str, energy: float, duration: float, seed: int,
                 forced: str | None = None) -> dict | None:
    usable = [t for t in catalog if t.get("enabled", True) and t.get("license")]
    if forced:
        hit = next((t for t in usable if t["id"] == forced), None)
        if hit:
            return hit
    pool = [t for t in usable if t.get("category") == mood]
    if not pool:
        return None
    target_bpm = 80 + 70 * energy

    def score(t: dict) -> float:
        s = 1.0 if t.get("origin") == "user" else 0.0       # your licensed tracks first
        if t.get("bpm"):
            s -= abs(float(t["bpm"]) - target_bpm) / 60
        if (t.get("duration") or 0) < duration * 0.6 and t.get("origin") == "user":
            s -= 0.3                                          # will loop a lot
        return s

    ranked = sorted(pool, key=lambda t: (-score(t), t["id"]))
    top = [t for t in ranked[:3] if score(t) >= score(ranked[0]) - 0.35]
    return top[seed % len(top)]


def plan_music(inp: PlannerInput, cands: list[Candidate], policy: PlannerPolicy, cfg: EditConfig,
               summary: DirectorSummary, catalog: list[dict] | None, time_effects: list[TimeEffect],
               mood_hint: str | None = None) -> tuple[MusicCue | None, list[str]]:
    notes: list[str] = []
    if cfg.music == "off":
        return None, notes
    if cfg.music_volume < 0.02:
        return None, ["Volume musica a zero: solo audio originale"]
    if not catalog:
        return None, ["Nessuna traccia musicale disponibile nella libreria audio"]
    if cfg.music_mood != "auto":
        mood = cfg.music_mood
        why = "mood scelto dall'utente"
    else:
        prefs = MOOD_FOR_TYPE.get(summary.dominant or "", [])
        allowed = list(policy.music_moods) or list(MUSIC_MOODS)
        if mood_hint in allowed:
            mood, why = mood_hint, "mood scelto dall'AI locale"
        else:
            mood = next((m for m in allowed if m in prefs), allowed[0])
            why = f"momenti {_label(summary.dominant).lower()}" if summary.dominant else "stile del preset"
    track = choose_track(catalog, mood, summary.energy, inp.duration, seed_for(inp.clip_id, mood), cfg.music_track)
    if track is None:
        other = next((m for m in (policy.music_moods or MUSIC_MOODS) if
                      choose_track(catalog, m, summary.energy, inp.duration, 0)), None)
        if other is None:
            return None, [f"Nessuna traccia con licenza per il mood {mood}"]
        notes.append(f"Nessuna traccia {mood}: uso {other}")
        mood = other
        track = choose_track(catalog, mood, summary.energy, inp.duration, seed_for(inp.clip_id, mood))
    level = policy.music_level_db + 20 * math.log10(max(0.02, cfg.music_volume) / 0.5)
    if summary.original_music:
        level -= 6
    if summary.speech_coverage > 0.85 and summary.style == "minimal":
        level -= 3
    duck = policy.duck_db * (cfg.music_ducking / 0.6)
    climax = None
    slow = [e for e in time_effects if e.kind in ("slow_motion", "speed_ramp")]
    strong = [c for c in cands if c.strength >= 0.6 and getattr(c, "moment", "") != "action_only"]
    if slow:
        climax = slow[0].start
    elif strong:
        climax = max(strong, key=lambda c: c.strength).t
    cue = MusicCue(asset_id=track["id"], title=track.get("title", ""), mood=mood, path=track.get("path", ""),
                   bpm=track.get("bpm"), beat_offset=float(track.get("beat_offset") or 0.0),
                   drop_time=track.get("drop_time"), license=track.get("license", ""),
                   attribution=track.get("attribution", ""), level_db=round(min(-6, max(-40, level)), 1),
                   duck_db=round(min(0, max(-30, duck)), 1),
                   fade_in=1.5 if summary.style == "cinematic" else 0.6, fade_out=1.2, sync_at=climax,
                   reason=f"{why}; {'battere allineato al culmine' if climax is not None else 'nessun culmine netto'}")
    return cue, notes


def plan_sounds(cands: list[Candidate], policy: PlannerPolicy, cfg: EditConfig, summary: DirectorSummary,
                time_effects: list[TimeEffect], music: MusicCue | None, used_at: list[float]) -> list[SoundCue]:
    if not cfg.sfx or policy.sfx_per_min <= 0:
        return []
    out: list[SoundCue] = []
    vol = cfg.sfx_volume
    for e in time_effects:
        if e.kind in ("slow_motion", "speed_ramp") and e.start >= 1.0 and summary.style != "minimal":
            at = max(0.0, e.start - 1.0)
            if all(abs(at - u) > 1.2 for u in used_at):
                out.append(SoundCue(category="riser", at=round(at, 3), volume=round(vol * 0.6, 2), priority=3,
                                    reason=f"Costruisce l'attesa prima del {_kind_it(e.kind).lower()}"))
        if e.kind == "freeze_frame" and all(abs(e.start - u) > 0.3 for u in used_at):
            out.append(SoundCue(category="hit", at=e.start, volume=round(vol * 0.8, 2), priority=2,
                                reason="Accento sonoro sul fermo immagine"))
    if music is not None and music.sync_at is not None and summary.style in ("energetic", "cinematic"):
        top = max((c.strength for c in cands), default=0)
        if top >= 0.8 and all(abs(music.sync_at - u) > 0.3 for u in used_at + [s.at for s in out]):
            out.append(SoundCue(category="bass_drop", at=music.sync_at, volume=round(vol * 0.7, 2), priority=3,
                                reason="Bass drop sul culmine, a tempo con la musica"))
    return out[:3]


def _label(m: str | None) -> str:
    return {"funny": "Momento divertente", "spectacular": "Momento spettacolare", "competitive": "Momento competitivo",
            "narrative": "Momento narrativo", "emotional": "Momento emozionante", "informative": "Momento informativo",
            "tension": "Momento di tensione", "action_only": "Solo movimento"}.get(m or "", "Momento")


def _kind_it(k: str) -> str:
    return {"slow_motion": "Slow motion", "speed_ramp": "Speed ramp", "freeze_frame": "Fermo immagine"}.get(k, k)


__all__ = ["analyse", "scaled_policy", "effect_for_moment", "sfx_for_moment", "plan_time_effects",
           "plan_transitions", "plan_overlays", "plan_look", "plan_music", "plan_sounds", "choose_track",
           "item_id", "BUDGET"]
