"""The editing plan (v2): a validated, declarative description of every editing decision for one clip.

The AI (rules or local LLM) only fills this structure; the renderer interprets it through predefined,
safe operations (OpenCV/numpy frame functions, FFmpeg filters built by code). Nothing in here is ever
executed as a command.

Tracks (all times are clip-relative *source* seconds, before pause removal / time remapping):

- ``segments``     visual accents (zoom, shake, flash, glitch, caption emphasis) + explicit "none" gaps
- ``time_effects`` slow motion, speed ramp, freeze frame
- ``transitions``  what happens on each jump cut (crossfade, zoom blur, flash, glitch, dip)
- ``overlays``     motion graphics (hook title, callouts)
- ``sounds``       standalone sound effects (+ the ones attached to segments)
- ``music``        background track with level, ducking, fades and the beat-sync point
- ``look``         colour grade + vignette
- ``director``     the analysis that motivated the plan (moment types, style, energy, comprehensibility)

Every item has a stable ``id`` (kind@time) so the user can switch single items off
(``EditConfig.disabled_items``), a ``priority`` (1 = essential … 3 = nice to have) and a ``reason``.
``EditPlan`` repairs what it can (clamps, overlaps, incompatible pairs, budgets) and records each
correction in ``issues``.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

PLAN_VERSION = 2

Effect = Literal["none", "subtle_zoom", "progressive_zoom", "punch_zoom", "caption_emphasis", "flash", "shake",
                 "glitch"]
VISUAL_ZOOMS = ("subtle_zoom", "progressive_zoom", "punch_zoom")
SfxCategory = Literal["whoosh", "impact", "bass_drop", "riser", "explosion", "hit", "transition", "ui", "cinematic",
                      "gaming", "pop", "ding"]
SFX_CATEGORIES: tuple[str, ...] = SfxCategory.__args__  # type: ignore[attr-defined]
TimeKind = Literal["slow_motion", "speed_ramp", "freeze_frame"]
TransitionKind = Literal["crossfade", "zoom_blur", "flash", "glitch", "dip"]
OverlayKind = Literal["hook_title", "callout"]
LookName = Literal["none", "teal_orange", "warm", "cool", "punchy", "bw", "cinematic", "vivid"]
MusicMood = Literal["cinematic", "dynamic", "electronic", "chill", "dramatic", "gaming"]
MUSIC_MOODS: tuple[str, ...] = MusicMood.__args__  # type: ignore[attr-defined]
MomentType = Literal["funny", "spectacular", "competitive", "narrative", "emotional", "informative", "tension",
                     "action_only"]
Style = Literal["minimal", "balanced", "energetic", "cinematic"]

MAX_STRETCH = 0.30        # time effects may lengthen the clip by at most 30 %
MAX_OUTPUT_S = 180.0      # platform limit (Shorts 3 min, Reels 3 min, TikTok more)
INCOMPATIBLE_WITH_FREEZE = {"punch_zoom", "progressive_zoom", "subtle_zoom", "shake", "flash", "glitch"}


def _clamp01(v) -> float:
    try:
        return float(min(1.0, max(0.0, float(v))))
    except (TypeError, ValueError):
        return 0.0


def _short(v, n: int = 200) -> str:
    return " ".join(str(v or "").split())[:n]


def item_id(kind: str, t: float) -> str:
    return f"{kind}@{t:.1f}"


# ------------------------------------------------------------------ items
class SfxCue(BaseModel):
    category: SfxCategory
    volume: float = Field(0.5, ge=0, le=1)
    at: float = Field(0.0, ge=0, description="Clip-relative time of the sound")


class PlanSegment(BaseModel):
    id: str = ""
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    effect: Effect = "none"
    intensity: float = 0.0
    reason: str = ""
    sfx: SfxCue | None = None
    candidate: int | None = None
    priority: int = Field(2, ge=1, le=3)

    v_intensity = field_validator("intensity", mode="before")(classmethod(lambda cls, v: _clamp01(v)))
    v_reason = field_validator("reason")(classmethod(lambda cls, v: _short(v)))

    @model_validator(mode="after")
    def _order(self) -> PlanSegment:
        if self.end <= self.start:
            raise ValueError(f"segment end {self.end} <= start {self.start}")
        if self.effect == "none":
            self.intensity = 0.0
            self.sfx = None
        return self


class TimeEffect(BaseModel):
    id: str = ""
    kind: TimeKind
    start: float = Field(ge=0)
    end: float = Field(0.0, ge=0)
    speed: float = Field(0.5, ge=0.2, le=1.0, description="Playback speed (slow motion / bottom of the ramp)")
    hold: float = Field(0.0, ge=0, le=2.0, description="Freeze duration (freeze_frame only)")
    intensity: float = 0.6
    priority: int = Field(2, ge=1, le=3)
    reason: str = ""
    candidate: int | None = None

    v_intensity = field_validator("intensity", mode="before")(classmethod(lambda cls, v: _clamp01(v)))
    v_reason = field_validator("reason")(classmethod(lambda cls, v: _short(v)))

    @model_validator(mode="after")
    def _shape(self) -> TimeEffect:
        if self.kind == "freeze_frame":
            self.end = self.start
            self.hold = min(max(self.hold, 0.3), 1.5)
            self.speed = 1.0
        else:
            self.hold = 0.0
            if self.end - self.start < 0.3:
                raise ValueError("time effect shorter than 0.3 s")
        return self

    @property
    def added(self) -> float:
        """Seconds this effect adds to the output."""
        if self.kind == "freeze_frame":
            return self.hold
        span = self.end - self.start
        if self.kind == "slow_motion":
            return span * (1 / self.speed - 1)
        return span * 0.5 * (1 / self.speed - 1)   # ramp: ~half of the span at the bottom speed


class Transition(BaseModel):
    id: str = ""
    kind: TransitionKind
    at: float = Field(ge=0, description="Source time of the cut (start of the removed pause)")
    duration: float = Field(0.2, ge=0.06, le=0.6)
    sfx: SfxCue | None = None
    priority: int = Field(3, ge=1, le=3)
    reason: str = ""

    v_reason = field_validator("reason")(classmethod(lambda cls, v: _short(v)))


class TextOverlay(BaseModel):
    id: str = ""
    kind: OverlayKind
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    text: str = Field(min_length=1, max_length=60)
    animation: Literal["pop", "slide", "fade", "typewriter"] = "pop"
    position: Literal["top", "upper", "center"] = "upper"
    evidence: str = ""
    priority: int = Field(2, ge=1, le=3)
    reason: str = ""

    v_reason = field_validator("reason")(classmethod(lambda cls, v: _short(v)))

    @field_validator("text", mode="before")
    @classmethod
    def _text(cls, v) -> str:
        t = re.sub(r"\{[^}]*\}", "", " ".join(str(v or "").split()))   # no ASS override blocks
        t = re.sub(r"[{}\\]", "", t)
        return t[:60]


class SoundCue(BaseModel):
    id: str = ""
    category: SfxCategory
    at: float = Field(ge=0)
    volume: float = Field(0.5, ge=0, le=1)
    priority: int = Field(2, ge=1, le=3)
    reason: str = ""

    v_reason = field_validator("reason")(classmethod(lambda cls, v: _short(v)))


class Look(BaseModel):
    grade: LookName = "none"
    intensity: float = Field(0.6, ge=0, le=1)
    vignette: float = Field(0.0, ge=0, le=1)
    reason: str = ""


class MusicCue(BaseModel):
    id: str = "music"
    asset_id: str
    title: str = ""
    mood: MusicMood
    path: str = ""
    bpm: float | None = None
    beat_offset: float = 0.0
    drop_time: float | None = None
    license: str = ""
    attribution: str = ""
    level_db: float = Field(-20.0, ge=-40, le=-6, description="Target music level (RMS dBFS) without speech")
    duck_db: float = Field(-10.0, ge=-30, le=0, description="Extra attenuation while someone speaks")
    fade_in: float = Field(0.8, ge=0, le=5)
    fade_out: float = Field(1.2, ge=0, le=5)
    sync_at: float | None = Field(None, description="Clip-relative source time to land on a downbeat / the drop")
    reason: str = ""


class Moment(BaseModel):
    candidate: int
    t: float
    type: MomentType
    strength: float
    evidence: str = ""


class DirectorSummary(BaseModel):
    style: Style = "balanced"
    energy: float = 0.0
    comprehensibility: float = 0.6
    dominant: MomentType | None = None
    moments: list[Moment] = []
    speech_coverage: float = 0.0
    words_per_s: float = 0.0
    scene_cuts: int = 0
    original_music: bool = False
    content_kind: str = ""
    notes: list[str] = []


# ------------------------------------------------------------------ plan
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
    time_effects: list[TimeEffect] = []
    transitions: list[Transition] = []
    overlays: list[TextOverlay] = []
    sounds: list[SoundCue] = []
    music: MusicCue | None = None
    look: Look = Field(default_factory=Look)
    director: DirectorSummary | None = None
    candidates: list[dict] = []
    notes: list[str] = []
    issues: list[str] = []
    key: str = ""

    @model_validator(mode="after")
    def _normalise(self) -> EditPlan:
        d = self.duration
        issues = list(self.issues)
        cut_pauses = [(p.start, p.end) for p in self.pauses if p.action == "cut"]

        # --- time effects: inside the clip, outside removed pauses, no overlaps, bounded stretch
        tfx: list[TimeEffect] = []
        for e in sorted(self.time_effects, key=lambda e: (e.priority, e.start)):
            a, b = max(0.0, min(e.start, d - 0.1)), max(0.0, min(e.end, d - 0.05))
            if e.kind != "freeze_frame" and b - a < 0.3:
                issues.append(f"{e.kind} a {e.start:.1f}s fuori dalla clip: scartato")
                continue
            if any(min(b, pb) - max(a, pa) > 0 or (e.kind == "freeze_frame" and pa <= a <= pb)
                   for pa, pb in cut_pauses):
                issues.append(f"{e.kind} a {a:.1f}s cade in una pausa tagliata: scartato")
                continue
            if any(a <= x.end + 0.2 and (b if e.kind != "freeze_frame" else a) >= x.start - 0.2 for x in tfx):
                issues.append(f"{e.kind} a {a:.1f}s si sovrappone a un altro effetto di tempo: scartato")
                continue
            e = e.model_copy(update={"start": round(a, 3), "end": round(b if e.kind != "freeze_frame" else a, 3)})
            stretch = sum(x.added for x in tfx) + e.added
            if stretch > MAX_STRETCH * d or d + stretch > MAX_OUTPUT_S:
                issues.append(f"{e.kind} a {a:.1f}s allungherebbe troppo la clip: scartato")
                continue
            tfx.append(e)
        self.time_effects = sorted(tfx, key=lambda e: e.start)
        freezes = [e.start for e in self.time_effects if e.kind == "freeze_frame"]
        slowmo = [(e.start, e.end) for e in self.time_effects if e.kind == "slow_motion"]

        # --- visual accents: clamp, drop overlaps and pairs that don't go together
        effects: list[PlanSegment] = []
        for s in sorted((s for s in self.segments if s.effect != "none"), key=lambda s: s.start):
            a, b = max(0.0, min(s.start, d)), max(0.0, min(s.end, d))
            if b - a < 0.15:
                continue
            if effects and a < effects[-1].end:  # overlap: keep the earlier one
                issues.append(f"{s.effect} a {a:.1f}s sovrapposto a {effects[-1].effect}: scartato")
                continue
            if s.effect in INCOMPATIBLE_WITH_FREEZE and any(a - 0.1 <= f <= b + 0.1 for f in freezes):
                issues.append(f"{s.effect} a {a:.1f}s incompatibile con il fermo immagine: scartato")
                continue
            if s.effect == "glitch" and any(min(b, sb) - max(a, sa) > 0 for sa, sb in slowmo):
                issues.append(f"glitch a {a:.1f}s durante uno slow motion: scartato")
                continue
            seg = s.model_copy(update={"start": round(a, 3), "end": round(b, 3), "id": s.id or item_id(s.effect, a)})
            if seg.sfx is not None:
                seg.sfx = seg.sfx.model_copy(update={"at": round(min(max(seg.sfx.at, 0.0), d - 0.05), 3)})
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

        # --- transitions: only on removed pauses, never two within 0.8 s
        trs: list[Transition] = []
        for tr in sorted(self.transitions, key=lambda x: x.at):
            if not any(pa - 0.35 <= tr.at <= pb + 0.05 for pa, pb in cut_pauses):
                issues.append(f"transizione {tr.kind} a {tr.at:.1f}s non è su un taglio: scartata")
                continue
            if trs and tr.at - trs[-1].at < 0.8:
                issues.append(f"transizione a {tr.at:.1f}s troppo vicina alla precedente: scartata")
                continue
            trs.append(tr.model_copy(update={"id": tr.id or item_id(tr.kind, tr.at)}))
        self.transitions = trs

        # --- overlays: inside the clip, no two on screen together
        ovs: list[TextOverlay] = []
        for o in sorted(self.overlays, key=lambda o: o.start):
            a, b = max(0.0, min(o.start, d - 0.3)), min(o.end, d)
            if b - a < 0.4:
                issues.append(f"testo “{o.text}” troppo breve o fuori dalla clip: scartato")
                continue
            if ovs and a < ovs[-1].end:
                issues.append(f"testo “{o.text}” sovrapposto a un altro testo: scartato")
                continue
            ovs.append(o.model_copy(update={"start": round(a, 3), "end": round(b, 3),
                                            "id": o.id or item_id(o.kind, a)}))
        self.overlays = ovs

        # --- standalone sounds: inside the clip, not on top of each other
        snd: list[SoundCue] = []
        taken = [s.sfx.at for s in self.segments if s.sfx is not None]
        for c in sorted(self.sounds, key=lambda c: (c.priority, c.at)):
            at = round(min(max(c.at, 0.0), d - 0.05), 3)
            if any(abs(at - t) < 0.25 for t in taken):
                issues.append(f"suono {c.category} a {at:.1f}s sovrapposto a un altro suono: scartato")
                continue
            taken.append(at)
            snd.append(c.model_copy(update={"at": at, "id": c.id or item_id(c.category, at)}))
        self.sounds = sorted(snd, key=lambda c: c.at)
        if self.music is not None and self.music.sync_at is not None:
            self.music.sync_at = round(min(max(self.music.sync_at, 0.0), d), 3)
        for e in self.time_effects:
            e.id = e.id or item_id(e.kind, e.start)
        self.issues = list(dict.fromkeys(issues))[:30]
        return self

    # ---------------------------------------------------------- views
    def effect_segments(self, *kinds: str) -> list[PlanSegment]:
        return [s for s in self.segments if s.effect in kinds]

    def sfx_cues(self) -> list[SfxCue]:
        """Every sound of the plan (segment-attached, transitions, standalone), sorted by time."""
        cues = [s.sfx for s in self.segments if s.sfx is not None]
        cues += [t.sfx.model_copy(update={"at": t.at}) for t in self.transitions if t.sfx is not None]
        cues += [SfxCue(category=c.category, volume=c.volume, at=c.at) for c in self.sounds]
        return sorted(cues, key=lambda c: c.at)

    def kept_pauses(self) -> list[tuple[float, float]]:
        return [(p.start, p.end) for p in self.pauses if p.action == "keep"]

    def item_ids(self) -> list[str]:
        ids = [s.id for s in self.segments if s.effect != "none"]
        ids += [e.id for e in self.time_effects] + [t.id for t in self.transitions]
        ids += [o.id for o in self.overlays] + [c.id for c in self.sounds]
        if self.music is not None:
            ids.append(self.music.id)
        if self.look.grade != "none" or self.look.vignette > 0:
            ids.append("look")
        return ids

    def without(self, disabled: list[str] | set[str]) -> EditPlan:
        """Copy with the items the user switched off removed (unknown ids are ignored)."""
        off = set(disabled or [])
        if not off:
            return self
        data = self.model_dump()
        data["segments"] = [s for s in data["segments"] if s["effect"] == "none" or s["id"] not in off]
        for k in ("time_effects", "transitions", "overlays", "sounds"):
            data[k] = [x for x in data[k] if x["id"] not in off]
        if data["music"] and data["music"]["id"] in off:
            data["music"] = None
        if "look" in off:
            data["look"] = Look().model_dump()
        data["notes"] = data["notes"] + [f"{len(off & set(self.item_ids()))} elementi disattivati dall'utente"]
        return EditPlan.model_validate(data)

    def summary(self) -> dict:
        c = Counter(s.effect for s in self.segments)
        return {"source": self.source, "preset": self.preset, "effects": {k: v for k, v in c.items() if k != "none"},
                "none_segments": c.get("none", 0), "emphasis": len(self.emphasis),
                "sfx": len(self.sfx_cues()), "kept_pauses": len(self.kept_pauses()),
                "time_effects": [e.kind for e in self.time_effects],
                "transitions": [t.kind for t in self.transitions],
                "overlays": [o.kind for o in self.overlays],
                "music": ({"title": self.music.title, "mood": self.music.mood} if self.music else None),
                "look": self.look.grade, "style": self.director.style if self.director else None}
