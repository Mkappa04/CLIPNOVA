"""Video library operations: import (upload / local path), update, delete."""

from __future__ import annotations

import logging
import re
import shutil
from pathlib import Path
from typing import BinaryIO

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.core.config import SUPPORTED_VIDEO_EXTENSIONS, get_settings
from backend.core.exceptions import ConflictError, NotFoundError, ValidationFailed
from backend.models.entities import (
    ACTIVE_JOB_STATUSES,
    Clip,
    Job,
    RightsRecord,
    StorageMode,
    Video,
    VideoStatus,
    new_id,
)
from backend.models.schemas import RightsIn, VideoOut

log = logging.getLogger(__name__)

_CHUNK = 4 * 1024 * 1024
_SAFE_RE = re.compile(r"[^A-Za-z0-9._-]+")


def safe_filename(name: str) -> str:
    stem = _SAFE_RE.sub("_", Path(name).stem).strip("._") or "video"
    return f"{stem[:80]}{Path(name).suffix.lower()}"


def check_extension(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    if ext not in SUPPORTED_VIDEO_EXTENSIONS:
        raise ValidationFailed(
            f"Unsupported file type '{ext or '(none)'}'. Supported: {', '.join(sorted(SUPPORTED_VIDEO_EXTENSIONS))}"
        )
    return ext


def default_title(filename: str) -> str:
    return Path(filename).stem.replace("_", " ").replace("-", " ").strip()[:300] or "Untitled"


def apply_rights(video: Video, rights_in: RightsIn) -> RightsRecord:
    data = rights_in.model_dump()
    data["license_type"] = rights_in.license_type.value
    data["authorization_status"] = rights_in.authorization_status.value
    if video.rights is None:
        video.rights = RightsRecord(**data)
    else:
        for k, v in data.items():
            setattr(video.rights, k, v)
    return video.rights


def save_upload_stream(stream: BinaryIO, original_name: str) -> tuple[Path, int]:
    """Stream an uploaded file into data/videos enforcing the size limit."""
    s = get_settings()
    check_extension(original_name)
    dest = s.videos_dir / f"{new_id()[:12]}_{safe_filename(original_name)}"
    limit = s.max_upload_mb * 1024 * 1024
    written = 0
    try:
        with dest.open("wb") as out:
            while chunk := stream.read(_CHUNK):
                written += len(chunk)
                if written > limit:
                    raise ValidationFailed(f"File exceeds the {s.max_upload_mb} MB upload limit")
                out.write(chunk)
    except BaseException:
        dest.unlink(missing_ok=True)
        raise
    if written == 0:
        dest.unlink(missing_ok=True)
        raise ValidationFailed(f"'{original_name}' is empty")
    return dest, written


def create_video(
    db: Session, *, file_path: Path, original_filename: str, storage_mode: StorageMode,
    file_size: int, title: str | None, game: str, creator: str, source: str, notes: str,
    rights: RightsIn, status: VideoStatus = VideoStatus.PENDING,
) -> Video:
    video = Video(
        title=(title or "").strip() or default_title(original_filename),
        original_filename=original_filename,
        file_path=str(file_path),
        storage_mode=storage_mode.value,
        file_size=file_size,
        game=game.strip() or "Unknown",
        creator=creator.strip(),
        source=source.strip(),
        notes=notes,
        status=status.value,
    )
    apply_rights(video, rights)
    db.add(video)
    db.flush()
    return video


def resolve_import_path(raw: str) -> tuple[Path, list[str]]:
    warnings: list[str] = []
    path = Path(raw.strip().strip('"').strip("'")).expanduser()
    if re.match(r"^[A-Za-z]:\\", raw.strip()):
        drive = raw.strip()[0].lower()
        path = Path(f"/mnt/{drive}/" + raw.strip()[3:].replace("\\", "/"))
        warnings.append(f"Windows path translated to {path}")
    if not path.is_absolute():
        raise ValidationFailed("Path must be absolute")
    path = path.resolve()
    if not path.exists():
        raise ValidationFailed(f"File not found: {path}")
    if not path.is_file():
        raise ValidationFailed(f"Not a file: {path}")
    check_extension(path.name)
    if str(path).startswith("/mnt/"):
        warnings.append("File is on the Windows filesystem (/mnt): access is slower. "
                        "Consider 'copy' mode to bring it into the Linux filesystem.")
    return path, warnings


def get_video(db: Session, video_id: str) -> Video:
    video = db.get(Video, video_id)
    if video is None:
        raise NotFoundError(f"Video {video_id} not found")
    return video


def to_out(db: Session, video: Video) -> VideoOut:
    out = VideoOut.model_validate(video)
    out.has_thumbnail = bool(video.thumbnail_path and Path(video.thumbnail_path).exists())
    out.clip_count = db.scalar(select(func.count(Clip.id)).where(Clip.video_id == video.id)) or 0
    return out


def delete_video(db: Session, video: Video, delete_file: bool) -> dict:
    active = db.scalar(select(func.count(Job.id)).where(
        Job.video_id == video.id, Job.status.in_(ACTIVE_JOB_STATUSES)))
    if active:
        raise ConflictError("Video has active jobs; cancel them first")

    removed: list[str] = []
    kept: list[str] = []
    s = get_settings()
    if video.thumbnail_path:
        Path(video.thumbnail_path).unlink(missing_ok=True)
    fp = Path(video.file_path)
    if delete_file and video.is_managed_file:
        try:
            fp.resolve().relative_to(s.videos_dir.resolve())
        except ValueError:
            kept.append(str(fp))  # safety: never delete outside our managed folder
        else:
            fp.unlink(missing_ok=True)
            removed.append(str(fp))
    else:
        kept.append(str(fp))
    db.delete(video)
    log.info("Deleted video %s (removed=%s kept=%s)", video.id, removed, kept)
    return {"removed_files": removed, "kept_files": kept}


def copy_with_progress(src: Path, dest: Path, on_progress, should_cancel) -> None:
    total = src.stat().st_size or 1
    done = 0
    try:
        with src.open("rb") as fi, dest.open("wb") as fo:
            while chunk := fi.read(_CHUNK):
                if should_cancel():
                    raise InterruptedError
                fo.write(chunk)
                done += len(chunk)
                on_progress(done / total)
        shutil.copystat(src, dest)
    except BaseException:
        dest.unlink(missing_ok=True)
        raise
