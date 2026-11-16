"""Everything known about a clip, gathered for the social metadata generator.

The generator must understand the clip, not just read its transcript, so this collects every signal
the project already has — and labels how reliable each one is:

- speech inside the clip with timestamps (Whisper: may contain recognition errors);
- speech just before / after the clip (context, never quoted as if it were in the clip);
- the semantic judgement of the analysis (local LLM: payoff type, reason, key line — a hint, not a fact);
- the heuristic detection reason and signals (audio peaks, laughter, motion, scene changes);
- the editing plan's evidence (shouts, reaction keywords) and the preset;
- what is visible in the frames (vision model, see vision.py — may be wrong);
- user-declared facts: game/topic, creator, rights/attribution.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field

from backend.clip_detection.pipeline import cache_dir, load_transcript
from backend.clip_detection.semantic import SEMANTIC_FILE
from backend.models.entities import Clip
from backend.subtitles.cues import clip_words

log = logging.getLogger(__name__)

CONTEXT_S = 15.0


@dataclass
class ClipContext:
    clip_id: str
    language: str                       # language of the copy to write (it | en)
    speech_language: str                # language spoken in the clip
    game: str                           # user-declared game / topic
    creator: str                        # user-declared creator ("" = unknown)
    category: str
    preset: str
    duration: float
    transcript: str                     # clip speech, plain text
    timed_transcript: str               # "(3.2s) words…" lines
    before: str = ""
    after: str = ""
    semantic: dict = field(default_factory=dict)   # {payoff_type, strength, reason, hook, standalone}
    detection_reason: str = ""
    signals: list[str] = field(default_factory=list)
    visual: dict = field(default_factory=dict)     # VisualDescription as dict ({} = not available)
    attribution: str = ""
    word_count: int = 0

    def as_dict(self) -> dict:
        return asdict(self)

    def facts_text(self) -> str:
        """All grounded text: anything in the generated copy must be traceable to this."""
        parts = [self.game, self.creator, self.category, f"{self.duration:.0f} secondi", self.transcript, self.before, self.after,
                 json.dumps(self.visual, ensure_ascii=False), self.semantic.get("hook", "")]
        return " ".join(p for p in parts if p)

    @property
    def speech_poor(self) -> bool:
        return self.word_count < 8


def _timed(words: list[dict], per_line: int = 14) -> str:
    lines, cur, t0 = [], [], None
    for w in words:
        if t0 is None:
            t0 = w["start"]
        cur.append(w["word"])
        if len(cur) >= per_line or w["word"].rstrip().endswith((".", "?", "!")):
            lines.append(f"({t0:.1f}s) {' '.join(cur)}")
            cur, t0 = [], None
    if cur:
        lines.append(f"({t0:.1f}s) {' '.join(cur)}")
    return "\n".join(lines)


def _semantic_for(clip: Clip) -> dict:
    """The analysis judgement that overlaps the clip the most (if the semantic analysis ran)."""
    path = cache_dir(clip.video_id) / SEMANTIC_FILE
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    units = {u["id"]: u for u in data.get("units", [])}
    best, best_ov = None, 0.0
    for j in data.get("judgements", []):
        a, b = units.get(j.get("first")), units.get(j.get("last"))
        if not a or not b:
            continue
        ov = min(clip.end, b["end"]) - max(clip.start, a["start"])
        if ov > best_ov:
            best, best_ov = j, ov
    if best is None or best_ov < 0.3 * clip.duration:
        return {}
    raw = best.get("raw") or {}
    return {k: v for k, v in {
        "payoff_type": raw.get("tipo_culmine"), "strength": raw.get("forza_culmine"),
        "standalone": raw.get("autonomia"), "small_talk": raw.get("chiacchiera_generica"),
        "reason": best.get("reason", ""), "hook": best.get("hook", ""), "score": round(best.get("score", 0), 1),
    }.items() if v not in (None, "")}


def _signals(clip: Clip) -> list[str]:
    out: list[str] = []
    plan = clip.edit_plan or {}
    for c in plan.get("candidates", [])[:8]:
        if c.get("strength", 0) >= 0.5:
            out.append(f"{c.get('t', 0):.1f}s: {c.get('evidence', '')}")
    s = clip.signals or {}
    if s.get("laughter", 0) > 0.2:
        out.append("risate rilevate nell'audio")
    if s.get("scene_changes", 0) > 0.3:
        out.append("diversi cambi di scena")
    if s.get("visual_motion", 0) > 0.5:
        out.append("molto movimento sullo schermo")
    return out


def build_context(clip: Clip, *, language: str, attribution: str = "", visual: dict | None = None) -> ClipContext:
    transcript = load_transcript(clip.video_id)
    words = clip_words(transcript, clip.start, clip.end)
    text = " ".join(w["word"] for w in words) or (clip.transcript or "")
    before = " ".join(w["word"] for w in clip_words(transcript, max(0.0, clip.start - CONTEXT_S), clip.start))
    after = " ".join(w["word"] for w in clip_words(transcript, clip.end, clip.end + CONTEXT_S))
    reason = (clip.reason or "").split("\n")
    return ClipContext(
        clip_id=clip.id, language=language,
        speech_language=(transcript.language if transcript else "") or clip.language or "",
        game=(clip.video.game or "").strip(), creator=(clip.video.creator or "").strip(),
        category=clip.category, preset=(clip.edit_config or {}).get("preset", "custom"),
        duration=round(clip.duration, 1), transcript=text[:2500], timed_transcript=_timed(words)[:3000],
        before=before[-500:], after=after[:400], semantic=_semantic_for(clip),
        detection_reason=" ".join(r.strip("• ") for r in reason)[:400], signals=_signals(clip),
        visual=visual or {}, attribution=attribution, word_count=len(words),
    )
