"""Assisted manual export: a ready-to-upload package per clip.

data/exports/<export_id>/
  <slug>.mp4            the approved render (hard link when possible, else copy)
  thumbnail.jpg         cover frame
  subtitles.srt         sidecar subtitles (YouTube accepts them)
  tiktok.txt / instagram.txt / youtube.txt   platform copy within length limits
  CHECKLIST.txt         what to do, in order, for each platform
  metadata.json         clip, rights snapshot, content, render stats
  package.zip           everything above (for one-click download)

Commercial/non-commercial exports are blocked when the rights policy says so.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import zipfile
from pathlib import Path

from backend.content_generation.templates import for_platform
from backend.core.config import get_settings
from backend.core.exceptions import RightsViolation, ValidationFailed
from backend.models.entities import Clip, ClipStatus, Export, new_id
from backend.rights_management.policy import Purpose, evaluate
from backend.services.approval import APPROVED_STATES, attribution_text, ensure_content, latest_render

log = logging.getLogger(__name__)
PLATFORMS = ("tiktok", "instagram", "youtube")

CHECKLIST = {
    "it": {
        "head": "CLIPNOVA – checklist di pubblicazione manuale",
        "common": ["Verifica che i diritti e le restrizioni riportati sotto siano rispettati.",
                   "Guarda il video fino alla fine prima di pubblicarlo."],
        "tiktok": ["Apri TikTok (app o tiktok.com/upload) e carica {video}.",
                   "Incolla il testo di tiktok.txt nella descrizione.",
                   "Se la clip contiene materiale di terzi, mantieni il credito nella descrizione."],
        "instagram": ["Apri Instagram → Nuovo Reel e carica {video}.",
                      "Incolla il testo di instagram.txt come didascalia.",
                      "Scegli la copertina (puoi usare thumbnail.jpg)."],
        "youtube": ["Apri studio.youtube.com → Carica video → {video}.",
                    "Copia titolo e descrizione da youtube.txt (contiene #Shorts).",
                    "Facoltativo: carica subtitles.srt in Sottotitoli.",
                    "Imposta 'Non è destinato ai bambini' e la visibilità desiderata."],
    },
    "en": {
        "head": "CLIPNOVA – manual publishing checklist",
        "common": ["Check that the rights and restrictions listed below are respected.",
                   "Watch the video to the end before publishing."],
        "tiktok": ["Open TikTok (app or tiktok.com/upload) and upload {video}.",
                   "Paste tiktok.txt into the description.",
                   "If the clip contains third-party material, keep the credit in the description."],
        "instagram": ["Open Instagram → New Reel and upload {video}.", "Paste instagram.txt as the caption.",
                      "Pick the cover (thumbnail.jpg can be used)."],
        "youtube": ["Open studio.youtube.com → Upload → {video}.",
                    "Copy title and description from youtube.txt (includes #Shorts).",
                    "Optional: upload subtitles.srt under Subtitles.",
                    "Set 'Not made for kids' and the desired visibility."],
    },
}


def slugify(text: str, max_len: int = 50) -> str:
    s = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE).strip().lower()
    s = re.sub(r"[\s_-]+", "-", s)
    return (s[:max_len].strip("-") or "clip")


def _link_or_copy(src: Path, dst: Path) -> None:
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def check_exportable(clip: Clip, purpose: Purpose) -> dict:
    if clip.status not in APPROVED_STATES:
        raise ValidationFailed("Only approved clips can be exported: approve it in the Approval Center first",
                               code="not_approved")
    decision = evaluate(clip.video.rights, purpose)
    if not decision.allowed:
        raise RightsViolation("Export blocked by the rights policy", details=decision.as_dict())
    return decision.as_dict()


def create_export(clip: Clip, platforms: list[str], purpose: Purpose) -> Export:
    platforms = [p for p in dict.fromkeys(platforms) if p in PLATFORMS]
    if not platforms:
        raise ValidationFailed(f"Choose at least one platform: {', '.join(PLATFORMS)}")
    decision = check_exportable(clip, purpose)
    render = latest_render(clip)
    if render is None or not Path(render.path or "").exists():
        raise ValidationFailed("No completed render available for this clip")

    s = get_settings()
    content = ensure_content(clip)
    attribution = attribution_text(clip)
    lang = content.get("language", "it") if content.get("language") in ("it", "en") else "it"
    exp = Export(id=new_id(), clip_id=clip.id, render_id=render.id, platforms=platforms, purpose=purpose.value)
    folder = s.exports_dir / exp.id
    folder.mkdir(parents=True, exist_ok=False)

    video_name = f"{slugify(content.get('title') or clip.suggested_title)}.mp4"
    _link_or_copy(Path(render.path), folder / video_name)
    for src, name in ((render.thumbnail_path, "thumbnail.jpg"), (render.srt_path, "subtitles.srt")):
        if src and Path(src).exists():
            shutil.copy2(src, folder / name)

    texts = {}
    for p in platforms:
        t = for_platform(content, p, attribution)
        texts[p] = t
        body = f"{t['title']}\n\n{t['description']}" if p == "youtube" else t["caption"]
        (folder / f"{p}.txt").write_text(body.strip() + "\n", encoding="utf-8")

    rights = clip.video.rights
    ck = CHECKLIST[lang]
    lines = [ck["head"], "=" * len(ck["head"]), ""] + [f"- {x}" for x in ck["common"]] + [""]
    for p in platforms:
        lines += [p.upper()] + [f"  {i}. {step.format(video=video_name)}" for i, step in enumerate(ck[p], 1)] + [""]
    lines += ["DIRITTI / RIGHTS", f"  Uso: {purpose.value}", f"  Proprietario: {rights.owner if rights else '-'}",
              f"  Licenza: {rights.license_type if rights else '-'}"]
    if attribution:
        lines.append(f"  Attribuzione obbligatoria: {attribution}")
    if rights and rights.restrictions.strip():
        lines.append(f"  RESTRIZIONI: {rights.restrictions.strip()}")
    for w in decision["warnings"]:
        lines.append(f"  ⚠ {w}")
    (folder / "CHECKLIST.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

    meta = {
        "export_id": exp.id, "clip_id": clip.id, "video": clip.video.title, "game": clip.video.game,
        "clip": {"start": clip.start, "end": clip.end, "category": clip.category, "score": clip.score},
        "render": {"id": render.id, "encoder": render.encoder, "duration": render.duration,
                   "width": render.width, "height": render.height},
        "content": content, "platform_texts": texts, "purpose": purpose.value, "rights_check": decision,
        "approved_at": clip.approved_at.isoformat() if clip.approved_at else None,
    }
    (folder / "metadata.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    with zipfile.ZipFile(folder / "package.zip", "w") as z:
        for f in sorted(folder.iterdir()):
            if f.name != "package.zip":
                z.write(f, f.name, compress_type=zipfile.ZIP_STORED if f.suffix == ".mp4" else zipfile.ZIP_DEFLATED)

    exp.path = str(folder)
    exp.rights_snapshot = decision
    exp.content_snapshot = {"content": content, "platform_texts": texts}
    if s.export_copy_dir:
        exp.copied_to = _copy_out(folder, s.export_copy_dir, video_name)
    clip.status = ClipStatus.EXPORTED.value
    return exp


def _copy_out(folder: Path, target_root: Path, video_name: str) -> str | None:
    """Optional mirror of the package (e.g. into a Windows folder under /mnt/c)."""
    try:
        target_root.mkdir(parents=True, exist_ok=True)
        dest = target_root / f"{Path(video_name).stem}_{folder.name[:6]}"
        shutil.copytree(folder, dest, ignore=shutil.ignore_patterns("package.zip"))
        return str(dest)
    except OSError as e:
        log.warning("Could not copy export to %s: %s", target_root, e)
        return None
