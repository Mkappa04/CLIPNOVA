"""Storage maintenance: find and (on confirmation) remove regenerable or orphaned files inside data/.

Never touches: original videos referenced in place, managed videos still in the library, renders and
exports that exist in the database, the database itself (only VACUUM), credentials, evidence files.
"""

from __future__ import annotations


import shutil
import sqlite3
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.core.config import get_settings
from backend.models.entities import ACTIVE_JOB_STATUSES, Clip, Export, Job, Render, Video
from backend.services.system import dir_size

CATEGORIES = {
    "orphan_videos": "File in data/videos non più collegati a nessun video (es. upload interrotti)",
    "orphan_cache": "Cache di analisi di video eliminati",
    "analysis_audio": "Audio estratto per l'analisi (si rigenera se rianalizzi il video)",
    "previews": "Anteprime delle clip (si rigenerano quando le apri)",
    "orphan_renders": "Cartelle di render senza record o con render falliti/annullati",
    "orphan_exports": "Cartelle di export senza record",
    "database": "Compattazione del database (VACUUM)",
}


def _size(p: Path) -> int:
    return dir_size(p) if p.is_dir() else (p.stat().st_size if p.exists() else 0)


def scan(db: Session) -> dict[str, dict]:
    s = get_settings()
    out: dict[str, dict] = {k: {"label": v, "bytes": 0, "items": []} for k, v in CATEGORIES.items()}

    referenced = {str(Path(p).resolve()) for (p,) in db.execute(select(Video.file_path))}
    if s.videos_dir.is_dir():
        for f in s.videos_dir.iterdir():
            if f.is_file() and str(f.resolve()) not in referenced:
                out["orphan_videos"]["items"].append(str(f))

    video_ids = {v for (v,) in db.execute(select(Video.id))}
    if s.cache_dir.is_dir():
        for d in s.cache_dir.iterdir():
            if not d.is_dir():
                continue
            if d.name not in video_ids:
                out["orphan_cache"]["items"].append(str(d))
            elif (d / "audio.wav").exists():
                out["analysis_audio"]["items"].append(str(d / "audio.wav"))

    if s.previews_dir.is_dir():
        out["previews"]["items"] = [str(f) for f in s.previews_dir.iterdir() if f.is_file()]

    good_renders = {r for (r,) in db.execute(select(Render.id).where(Render.status.in_(["completed", "rendering"])))}
    if s.renders_dir.is_dir():
        out["orphan_renders"]["items"] = [str(d) for d in s.renders_dir.iterdir() if d.is_dir() and d.name not in good_renders]

    exports = {e for (e,) in db.execute(select(Export.id))}
    if s.exports_dir.is_dir():
        out["orphan_exports"]["items"] = [str(d) for d in s.exports_dir.iterdir() if d.is_dir() and d.name not in exports]

    for v in out.values():
        v["bytes"] = sum(_size(Path(p)) for p in v["items"])
        v["count"] = len(v["items"])
    dbf = s.data_dir / "clipnova.db"
    if dbf.exists():
        con = sqlite3.connect(dbf)
        try:
            page, free = con.execute("PRAGMA page_size").fetchone()[0], con.execute("PRAGMA freelist_count").fetchone()[0]
        finally:
            con.close()
        out["database"].update({"bytes": page * free, "count": 1 if free else 0})
    return out


def cleanup(db: Session, categories: list[str]) -> dict:
    s = get_settings()
    active = db.scalar(select(func.count(Job.id)).where(Job.status.in_(ACTIVE_JOB_STATUSES))) or 0
    found = scan(db)
    data_root = s.data_dir.resolve()
    freed, removed, skipped = 0, 0, []
    for cat in categories:
        if cat not in CATEGORIES:
            continue
        if cat == "database":
            if active:
                skipped.append("database: job attivi, VACUUM rimandato")
                continue
            before = (s.data_dir / "clipnova.db").stat().st_size
            con = sqlite3.connect(s.data_dir / "clipnova.db")
            try:
                con.execute("VACUUM")
            finally:
                con.close()
            freed += max(0, before - (s.data_dir / "clipnova.db").stat().st_size)
            continue
        if cat in ("analysis_audio", "previews") and active:
            skipped.append(f"{cat}: job attivi, rimandato")
            continue
        for p in found[cat]["items"]:
            path = Path(p).resolve()
            if data_root not in path.parents:  # hard safety net: only inside data/
                skipped.append(str(path))
                continue
            size = _size(path)
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
            else:
                path.unlink(missing_ok=True)
            freed += size
            removed += 1
        if cat == "previews":
            db.query(Clip).filter(Clip.preview_path.is_not(None)).update({"preview_path": None})
    from backend.services import system

    system._size_cache.clear()
    return {"freed_bytes": freed, "removed": removed, "skipped": skipped}


