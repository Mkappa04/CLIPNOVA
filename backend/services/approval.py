"""Review & approval workflow.

IMPORT → ANALYSIS → CLIP DETECTION → EDITING → RENDERING → REVIEW → APPROVED → EXPORT / PUBLISH

- A clip can be approved only from REVIEW and only with a completed render.
- Changing the copy (title/caption/hashtags) of an approved clip, or re-rendering it,
  sends it back to REVIEW: approval always refers to exactly what will be published.
"""

from __future__ import annotations

from backend.clip_detection.pipeline import load_transcript
from backend.content_generation import llm, templates
from backend.core.config import get_settings
from backend.core.exceptions import ValidationFailed
from backend.core.timeutil import utcnow
from backend.models.entities import Clip, ClipStatus, LicenseType, Render, RenderStatus
from backend.rights_management.policy import Purpose, evaluate
from backend.subtitles.cues import clip_words

CONTENT_FIELDS = ("language", "title", "hook", "caption", "description", "hashtags", "cta")
APPROVED_STATES = (ClipStatus.APPROVED.value, ClipStatus.EXPORTED.value)


def latest_render(clip: Clip) -> Render | None:
    done = [r for r in clip.renders if r.status == RenderStatus.COMPLETED.value and r.path]
    return max(done, key=lambda r: r.created_at) if done else None


def clip_language(clip: Clip) -> str:
    a = clip.video.analysis
    if a is not None and a.language in ("it", "en"):
        return a.language
    s = get_settings()
    return s.default_language if s.default_language in ("it", "en") else "it"


def attribution_text(clip: Clip) -> str:
    r = clip.video.rights
    if r is None:
        return ""
    needs = r.attribution_required or r.license_type in (LicenseType.CC_BY.value, LicenseType.CC_BY_SA.value,
                                                         LicenseType.CC_BY_NC.value)
    return r.attribution_text.strip() if needs else ""


def _facts(clip: Clip) -> dict:
    transcript = clip.transcript
    if not transcript:
        words = clip_words(load_transcript(clip.video_id), clip.start, clip.end)
        transcript = " ".join(w["word"] for w in words)
    return {"category": clip.category, "transcript": transcript, "keywords": list(clip.keywords or []),
            "game": clip.video.game, "creator": clip.video.creator}


def generate_content(clip: Clip, *, use_llm: bool = False, language: str | None = None) -> tuple[dict, list[str]]:
    facts = _facts(clip)
    lang = language or clip_language(clip)
    content = templates.generate(**facts, language=lang, attribution=attribution_text(clip))
    warnings: list[str] = []
    if not facts["transcript"]:
        warnings.append("Nessun parlato nella clip: testo generico basato su gioco e categoria")
    if use_llm:
        try:
            content, w = llm.rewrite(content, language=lang, **facts)
            warnings += w
        except llm.LLMUnavailable as e:
            warnings.append(f"LLM locale non disponibile, uso i template: {e}")
    return content, warnings


def ensure_content(clip: Clip) -> dict:
    if not clip.content:
        clip.content, _ = generate_content(clip)
    return clip.content


def set_content(clip: Clip, content: dict) -> bool:
    """Save copy; returns True if an existing approval was revoked."""
    clean = {k: content.get(k) for k in CONTENT_FIELDS if k in content}
    tags = clean.get("hashtags") or []
    clean["hashtags"] = [str(t).lstrip("#").strip() for t in tags if str(t).strip("# ")][:30]
    previous = clip.content or {}
    changed = any(clean.get(k) != previous.get(k) for k in clean)
    source = previous.get("generated_by", "manual")
    if changed and "edited" not in source:
        source += "+edited"
    clip.content = {**previous, **clean, "generated_by": source}
    if changed and clip.status in APPROVED_STATES:
        clip.status = ClipStatus.REVIEW.value
        clip.approved_at = None
        return True
    return False


def rights_summary(clip: Clip) -> dict:
    return {p.value: evaluate(clip.video.rights, p).as_dict() for p in (Purpose.NON_COMMERCIAL, Purpose.COMMERCIAL)}


def approve(clip: Clip, note: str = "") -> None:
    if clip.status not in (ClipStatus.REVIEW.value,):
        raise ValidationFailed(f"Only clips in review can be approved (current: {clip.status})")
    if latest_render(clip) is None:
        raise ValidationFailed("Render the clip before approving it")
    ensure_content(clip)
    clip.status = ClipStatus.APPROVED.value
    clip.approved_at = utcnow()
    clip.review_note = note


def reject(clip: Clip, note: str = "") -> None:
    if clip.status == ClipStatus.RENDERING.value:
        raise ValidationFailed("Clip is rendering")
    clip.status = ClipStatus.REJECTED.value
    clip.approved_at = None
    clip.review_note = note


def archive(clip: Clip) -> None:
    if clip.status == ClipStatus.RENDERING.value:
        raise ValidationFailed("Clip is rendering")
    clip.status = ClipStatus.ARCHIVED.value
    clip.approved_at = None


def reopen(clip: Clip) -> None:
    if clip.status not in (ClipStatus.REJECTED.value, ClipStatus.ARCHIVED.value, *APPROVED_STATES):
        raise ValidationFailed(f"Nothing to reopen (current: {clip.status})")
    clip.status = ClipStatus.REVIEW.value if latest_render(clip) else ClipStatus.DETECTED.value
    clip.approved_at = None
