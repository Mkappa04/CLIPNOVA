"""DB-backed job queue with progress tracking and cooperative cancellation.

Jobs are persisted in SQLite so the UI can follow them and so interrupted
jobs are visible after a restart. Execution uses a bounded thread pool;
heavy work (ffmpeg, AI models) runs in subprocesses or releases the GIL.
`worker_concurrency` defaults to 1 to protect the 6 GB of VRAM and the RAM.
"""

from __future__ import annotations

import logging
import threading
import time
import traceback
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from sqlalchemy import select

from backend.core.timeutil import utcnow
from backend.database.session import session_scope
from backend.models.entities import Job, JobStatus

log = logging.getLogger(__name__)


class JobCancelled(Exception):
    pass


class JobContext:
    """Handed to job handlers: report progress and check cancellation."""

    _MIN_WRITE_INTERVAL = 0.5

    def __init__(self, manager: JobManager, job_id: str, payload: dict[str, Any], video_id: str | None):
        self.manager = manager
        self.job_id = job_id
        self.payload = payload
        self.video_id = video_id
        self._last_write = 0.0

    @property
    def cancelled(self) -> bool:
        return self.manager.is_cancel_requested(self.job_id)

    def check_cancelled(self) -> None:
        if self.cancelled:
            raise JobCancelled()

    def progress(self, value: float, message: str | None = None, *, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._last_write < self._MIN_WRITE_INTERVAL:
            return
        self._last_write = now
        with session_scope() as db:
            job = db.get(Job, self.job_id)
            if job is not None:
                job.progress = max(0.0, min(1.0, float(value)))
                if message is not None:
                    job.message = message


Handler = Callable[[JobContext], dict[str, Any] | None]


class JobManager:
    def __init__(self) -> None:
        self._handlers: dict[str, Handler] = {}
        self._executor: ThreadPoolExecutor | None = None
        self._cancel_flags: dict[str, threading.Event] = {}
        self._lock = threading.Lock()

    # ---------------------------------------------------------- registry
    def register(self, job_type: str) -> Callable[[Handler], Handler]:
        def deco(fn: Handler) -> Handler:
            self._handlers[job_type] = fn
            return fn
        return deco

    @property
    def job_types(self) -> list[str]:
        return sorted(self._handlers)

    # ---------------------------------------------------------- lifecycle
    def start(self, concurrency: int = 1) -> None:
        if self._executor is not None:
            return
        self._executor = ThreadPoolExecutor(max_workers=concurrency, thread_name_prefix="clipnova-job")
        self._recover()
        log.info("Job manager started (concurrency=%d, types=%s)", concurrency, self.job_types)

    def shutdown(self) -> None:
        with self._lock:
            for ev in self._cancel_flags.values():
                ev.set()
        if self._executor is not None:
            self._executor.shutdown(wait=True, cancel_futures=True)
            self._executor = None
        # Jobs that never started stay 'queued' and are resumed on next start.

    def _recover(self) -> None:
        with session_scope() as db:
            running = db.scalars(select(Job).where(Job.status == JobStatus.RUNNING.value)).all()
            for job in running:
                job.status = JobStatus.FAILED.value
                job.error = "Interrupted by application restart"
                job.finished_at = utcnow()
            queued = db.scalars(
                select(Job).where(Job.status == JobStatus.QUEUED.value).order_by(Job.created_at)
            ).all()
            queued_ids = [j.id for j in queued]
        for jid in queued_ids:
            self._schedule(jid)

    # ---------------------------------------------------------- API
    def submit(self, job_type: str, payload: dict[str, Any] | None = None,
               video_id: str | None = None) -> str:
        if job_type not in self._handlers:
            raise ValueError(f"Unknown job type: {job_type}")
        with session_scope() as db:
            job = Job(type=job_type, payload=payload or {}, video_id=video_id,
                      status=JobStatus.QUEUED.value, message="Queued")
            db.add(job)
            db.flush()
            job_id = job.id
        self._schedule(job_id)
        return job_id

    def cancel(self, job_id: str) -> bool:
        with session_scope() as db:
            job = db.get(Job, job_id)
            if job is None or job.status not in (JobStatus.QUEUED.value, JobStatus.RUNNING.value):
                return False
            job.cancel_requested = True
            if job.status == JobStatus.QUEUED.value:
                job.status = JobStatus.CANCELLED.value
                job.finished_at = utcnow()
                job.message = "Cancelled before start"
        with self._lock:
            self._cancel_flags.setdefault(job_id, threading.Event()).set()
        return True

    def is_cancel_requested(self, job_id: str) -> bool:
        with self._lock:
            ev = self._cancel_flags.get(job_id)
        return bool(ev and ev.is_set())

    # ---------------------------------------------------------- internals
    def _schedule(self, job_id: str) -> None:
        if self._executor is None:
            log.debug("Job %s queued; executor not started yet", job_id)
            return
        with self._lock:
            self._cancel_flags.setdefault(job_id, threading.Event())
        self._executor.submit(self._run, job_id)

    def _run(self, job_id: str) -> None:
        with session_scope() as db:
            job = db.get(Job, job_id)
            if job is None or job.status != JobStatus.QUEUED.value:
                return
            if job.cancel_requested or self.is_cancel_requested(job_id):
                job.status = JobStatus.CANCELLED.value
                job.finished_at = utcnow()
                return
            job.status = JobStatus.RUNNING.value
            job.started_at = utcnow()
            job.message = "Running"
            handler = self._handlers[job.type]
            ctx = JobContext(self, job_id, dict(job.payload or {}), job.video_id)

        log.info("Job %s (%s) started", job_id, handler.__name__)
        status, result, error, message = JobStatus.COMPLETED, None, None, "Completed"
        try:
            result = handler(ctx)
        except JobCancelled:
            status, message = JobStatus.CANCELLED, "Cancelled"
        except Exception as exc:  # noqa: BLE001 - job boundary
            status, error, message = JobStatus.FAILED, f"{type(exc).__name__}: {exc}", "Failed"
            log.error("Job %s failed: %s\n%s", job_id, exc, traceback.format_exc())

        with session_scope() as db:
            job = db.get(Job, job_id)
            if job is not None:
                job.status = status.value
                job.result = result
                job.error = error
                job.message = message
                job.finished_at = utcnow()
                if status is JobStatus.COMPLETED:
                    job.progress = 1.0
        with self._lock:
            self._cancel_flags.pop(job_id, None)
        log.info("Job %s finished: %s", job_id, status.value)


job_manager = JobManager()
