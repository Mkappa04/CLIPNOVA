from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.core.exceptions import ConflictError, NotFoundError
from backend.database.session import get_db
from backend.models.entities import Job
from backend.models.schemas import JobOut
from backend.workers.queue import job_manager

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get("", response_model=list[JobOut])
def list_jobs(
    status: str | None = None, video_id: str | None = None, type: str | None = None,
    limit: int = Query(100, ge=1, le=500), db: Session = Depends(get_db),
):
    stmt = select(Job).order_by(Job.created_at.desc()).limit(limit)
    if status:
        stmt = stmt.where(Job.status.in_(status.split(",")))
    if video_id:
        stmt = stmt.where(Job.video_id == video_id)
    if type:
        stmt = stmt.where(Job.type == type)
    return db.scalars(stmt).all()


@router.get("/{job_id}", response_model=JobOut)
def get_job(job_id: str, db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if job is None:
        raise NotFoundError(f"Job {job_id} not found")
    return job


@router.post("/{job_id}/cancel", response_model=JobOut)
def cancel_job(job_id: str, db: Session = Depends(get_db)):
    if db.get(Job, job_id) is None:
        raise NotFoundError(f"Job {job_id} not found")
    if not job_manager.cancel(job_id):
        raise ConflictError("Job is not active")
    db.expire_all()
    return db.get(Job, job_id)
