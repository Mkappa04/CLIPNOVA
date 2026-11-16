"""Review & approval workflow.

IMPORT → ANALYSIS → CLIP DETECTION → EDITING → RENDERING → REVIEW → APPROVED → EXPORT / PUBLISH

- A clip can be approved only from REVIEW and only with a completed render.
- Changing the copy (title/caption/hashtags) of an approved clip, or re-rendering it,
  sends it back to REVIEW: approval always refers to exactly what will be published.
"""

from __future__ import annotations

from collections import Counter

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import object_session

from backend.content_generation import metadata, vision
from backend.content_generation.context import build_context
from backend.core.config import get_settings
from backend.core.exceptions import ValidationFailed
from backend.core.timeutil import utcnow
from backend.models.entities import Clip, ClipStatus, LicenseType, Render, RenderStatus
from backend.rights_management.policy import Purpose, evaluate

CONTENT_FIELDS = ("language", "title", "hook", "caption", "description", "hashtags", "cta", "metadata")
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


def _recent(clip: Clip, n: int = 30) -> tuple[list[str], Counter]:
    """Titles and hashtags of the most recent other clips: the generator avoids repeating them."""
    db = object_session(clip)
    if db is None:
        return [], Counter()
    rows = db.scalars(select(Clip.content).where(Clip.id != clip.id, Clip.content.is_not(None))
                      .order_by(Clip.updated_at.desc()).limit(n)).all()
    titles: list[str] = []
    tags: Counter = Counter()
    for c in rows:
        if not c:
            continue
        if c.get("title"):
            titles.append(c["title"])
        plat = ((c.get("metadata") or {}).get("platforms") or {})
        used = {t.lower() for p in plat.values() for t in (p.get("hashtags") or [])} or \
            {t.lower() for t in c.get("hashtags") or []}
        tags.update(used)
    return titles, tags


def generate_content(clip: Clip, *, use_llm: bool = True, language: str | None = None,
                     parts: list[str] | None = None, current: dict | None = None) -> tuple[dict, list[str]]:
    """Social copy: content analysis → 3 titles + per-platform captions + hashtags (see content_generation).

    `parts` (titles | captions | hashtags) regenerates only those, keeping the rest of `current`
    (the metadata dict being edited, else the stored one)."""
    lang = language or clip_language(clip)
    visual = vision.describe(clip) if use_llm and metadata.text_model() else {}
    ctx = build_context(clip, language=lang, attribution=attribution_text(clip), visual=visual)
    stored = (clip.content or {}).get("metadata") or {}
    titles, tags = _recent(clip)
    if visual:  # vision model done: free its VRAM before the text model loads
        import httpx

        from backend.clip_detection.semantic import wait_unloaded
        with httpx.Client() as c:
            wait_unloaded(c, visual.get("model", ""))
    meta, warnings = metadata.generate(ctx, parts=parts, current=current or stored, recent_titles=titles,
                                       recent_tags=tags, use_ai=use_llm)
    content = {**meta.legacy(), "metadata": meta.model_dump(), "generated_by": meta.generated_by}
    if not ctx.transcript:
        warnings.insert(0, "Nessun parlato nella clip: i testi si basano su ciò che si vede e sui dati del video")
    return content, warnings


def ensure_content(clip: Clip) -> dict:
    """Content for export/approval when none was generated: fast, without the AI (prudent texts)."""
    if not clip.content:
        clip.content, _ = generate_content(clip, use_llm=False)
    return clip.content


def set_content(clip: Clip, content: dict) -> bool:
    """Save copy; returns True if an existing approval was revoked."""
    clean = {k: content.get(k) for k in CONTENT_FIELDS if k in content}
    if clean.get("metadata"):
        try:
            meta = metadata.SocialMetadata.model_validate(clean["metadata"])
        except ValidationError as e:
            raise ValidationFailed(f"Metadati non validi: {e.errors()[0].get('msg', e)}") from e
        legacy = meta.legacy()
        prev = clip.content or {}
        # a client that edits only the classic fields (title/caption/hashtags) next to an unchanged
        # metadata block: the classic edit wins and is copied into the metadata
        def edited(k: str) -> bool:
            return k in clean and clean[k] != legacy[k] and clean[k] != prev.get(k)
        if edited("title"):
            t = str(clean["title"])[:100]
            meta.titles.options = [t] + [o for o in meta.titles.options if o != t][:2]
            meta.titles.selected = t
        if edited("caption"):
            meta.platforms.instagram.caption = str(clean["caption"])
        if edited("hashtags"):
            meta.platforms.instagram.hashtags = metadata.dedupe_tags([str(t) for t in clean["hashtags"]])
        meta = metadata.SocialMetadata.model_validate(meta.model_dump())
        clean["metadata"] = meta.model_dump()
        legacy = meta.legacy()
        clean.update({k: legacy[k] for k in ("title", "caption", "description", "hook")})
        if not edited("hashtags"):
            clean["hashtags"] = legacy["hashtags"]
    elif "metadata" in clean:
        clean.pop("metadata")
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
