from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.core.config import SUPPORTED_VIDEO_EXTENSIONS, get_settings
from backend.database.session import get_db
from backend.models.entities import (
    ACTIVE_JOB_STATUSES,
    Clip,
    ClipStatus,
    Job,
    JobStatus,
    Video,
    VideoStatus,
)
from backend.models.schemas import JobOut
from backend.services import system, video_service

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/health")
def health() -> dict:
    s = get_settings()
    return {"status": "ok", "app": s.app_name, "version": s.version}


@router.get("/system")
def system_info() -> dict:
    return system.system_info()


@router.get("/settings")
def settings() -> dict:
    s = get_settings()
    return {
        "app_name": s.app_name, "version": s.version, "host": s.host, "port": s.port,
        "data_dir": str(s.data_dir), "log_level": s.log_level, "max_upload_mb": s.max_upload_mb,
        "worker_concurrency": s.worker_concurrency, "use_gpu": s.use_gpu, "max_vram_mb": s.max_vram_mb,
        "default_language": s.default_language, "publishing_enabled": s.publishing_enabled,
        "supported_extensions": sorted(SUPPORTED_VIDEO_EXTENSIONS),
    }


@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db)) -> dict:
    s = get_settings()

    def count(model, *where) -> int:
        return db.scalar(select(func.count()).select_from(model).where(*where)) or 0

    clips_by_status = dict(db.execute(select(Clip.status, func.count()).group_by(Clip.status)).all())
    videos_by_game = dict(db.execute(select(Video.game, func.count()).group_by(Video.game)).all())
    total_duration = db.scalar(select(func.coalesce(func.sum(Video.duration), 0.0))) or 0.0
    recent_videos = db.scalars(select(Video).order_by(Video.created_at.desc()).limit(6)).unique().all()
    recent_jobs = db.scalars(select(Job).order_by(Job.created_at.desc()).limit(8)).all()
    disk = system.shutil.disk_usage(s.data_dir)

    return {
        "videos": {
            "total": count(Video),
            "ready": count(Video, Video.status.in_([VideoStatus.READY.value, VideoStatus.ANALYZED.value])),
            "errors": count(Video, Video.status == VideoStatus.ERROR.value),
            "total_duration": total_duration,
            "by_game": videos_by_game,
        },
        "clips": {
            "total": sum(clips_by_status.values()),
            "in_review": clips_by_status.get(ClipStatus.REVIEW.value, 0),
            "approved": clips_by_status.get(ClipStatus.APPROVED.value, 0),
            "by_status": clips_by_status,
        },
        "jobs": {
            "active": count(Job, Job.status.in_(ACTIVE_JOB_STATUSES)),
            "failed": count(Job, Job.status == JobStatus.FAILED.value),
            "renders_completed": count(Job, Job.type.like("render.%"), Job.status == JobStatus.COMPLETED.value),
        },
        "storage": {"data_bytes": system.dir_size(s.data_dir), "disk_free": disk.free, "disk_total": disk.total},
        "recent_videos": [video_service.to_out(db, v).model_dump(mode="json") for v in recent_videos],
        "recent_jobs": [JobOut.model_validate(j).model_dump(mode="json") for j in recent_jobs],
    }
