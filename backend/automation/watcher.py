"""Polling watcher for watch folders.

Polling instead of inotify: inotify does not see changes made by Windows on /mnt/c.

File lifecycle (WatchedFile.status):
  waiting   → size/mtime still changing, or not yet a finalised video (e.g. OBS still recording)
  ready     → imported as a Video, waiting for the automatic pipeline
  deferred  → pipeline postponed (paused / outside time window / PC busy)
  processing→ auto.pipeline job running
  done      → clips rendered and waiting in the Approval Center
  skipped | duplicate | error → with a human-readable reason
"""

from __future__ import annotations

import logging
import os
import threading
from datetime import timedelta
from pathlib import Path

from sqlalchemy import or_, select

from backend.automation.common import automation_settings, can_run_heavy, notify, quick_signature
from backend.core.config import SUPPORTED_VIDEO_EXTENSIONS, get_settings
from backend.core.exceptions import MediaError
from backend.core.timeutil import utcnow
from backend.database.session import session_scope
from backend.models.automation_entities import CreatorPermission, WatchedFile, WatchFolder
from backend.models.entities import Job, JobStatus, StorageMode, Video, VideoStatus
from backend.models.schemas import RightsIn
from backend.services import ffmpeg
from backend.services import video_service as vs

log = logging.getLogger(__name__)

TEMP_SUFFIXES = (".part", ".tmp", ".crdownload", ".partial", ".download", ".!ut", ".temp")
IMPORTED = ("ready", "deferred", "processing", "done")
MAX_PIPELINE_ATTEMPTS = 2


def is_temp_name(name: str) -> bool:
    low = name.lower()
    return low.startswith((".", "~$", "~")) or low.endswith(TEMP_SUFFIXES) or ".part." in low


def list_candidates(folder: WatchFolder) -> list[Path]:
    root = Path(folder.path)
    exts = {e.lower() if e.startswith(".") else f".{e.lower()}" for e in (folder.extensions or [])} \
        or SUPPORTED_VIDEO_EXTENSIONS
    out: list[Path] = []
    if not root.is_dir():
        raise FileNotFoundError(f"Cartella non trovata: {root}")
    walker = os.walk(root) if folder.recursive else [(str(root), [], [e.name for e in os.scandir(root) if e.is_file()])]
    for dirpath, _dirs, files in walker:
        for name in files:
            if is_temp_name(name) or Path(name).suffix.lower() not in exts:
                continue
            out.append(Path(dirpath) / name)
    return sorted(out)


def rights_for(db, folder: WatchFolder) -> tuple[RightsIn, str]:
    """Rights of a new file: from the creator's recorded consent if linked, else the folder profile."""
    if folder.creator is not None:
        today = utcnow().date()
        perms = [p for p in folder.creator.permissions if not p.revoked and (p.expires_at is None or p.expires_at >= today)]
        if perms:
            p: CreatorPermission = perms[0]
            channel = (folder.creator.channels or [{}])[0].get("url", "")
            return RightsIn(owner=folder.creator.name, source_url=channel, license_type="creator_permission",
                            authorization_status="authorized", commercial_use_allowed=p.commercial_use,
                            attribution_required=True, attribution_text=p.attribution_text, expires_at=p.expires_at,
                            restrictions=p.restrictions,
                            evidence=f"Permesso registrato il {p.granted_at.isoformat()} (id {p.id[:8]}): {p.scope}"), ""
        return RightsIn(owner=folder.creator.name, license_type="creator_permission",
                        authorization_status="pending"), "Nessun permesso valido del creator: export bloccato"
    try:
        return RightsIn.model_validate(folder.rights or {}), ""
    except ValueError:
        return RightsIn(), "Profilo diritti della cartella non valido"


class Watcher:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.last_tick_at = None
        self.last_tick_stats: dict = {}
        self._last_expiry_check = None

    # ------------------------------------------------------------- lifecycle
    def start(self) -> None:
        if self._thread is not None or not get_settings().automation_enabled:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="clipnova-watcher", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=10)
        self._thread = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _loop(self) -> None:
        while not self._stop.wait(max(3, get_settings().automation_poll_s)):
            try:
                self.tick()
            except Exception as e:  # noqa: BLE001 - keep watching
                log.error("Watcher tick failed: %s", e, exc_info=True)

    # ------------------------------------------------------------- one pass
    def tick(self, now=None) -> dict:
        with self._lock:
            now = now or utcnow()
            stats = {"seen": 0, "imported": 0, "skipped": 0, "submitted": 0, "deferred": 0}
            with session_scope() as db:
                if automation_settings(db).get("paused"):
                    stats["paused"] = True
                    self.last_tick_at, self.last_tick_stats = now, stats
                    return stats
                folders = db.scalars(select(WatchFolder).where(WatchFolder.enabled.is_(True))).all()
                folder_ids = [f.id for f in folders]
            for fid in folder_ids:
                self._scan_folder(fid, now, stats)
            self._dispatch(now, stats)
            self._check_permissions(now)
            self.last_tick_at, self.last_tick_stats = now, stats
            return stats

    def _scan_folder(self, folder_id: str, now, stats: dict) -> None:
        s = get_settings()
        with session_scope() as db:
            folder = db.get(WatchFolder, folder_id)
            try:
                paths = list_candidates(folder)
                folder.last_error = None
            except OSError as e:
                folder.last_error = str(e)
                return
            folder.last_scan_at = now
            known = {wf.path: wf for wf in db.scalars(select(WatchedFile).where(WatchedFile.folder_id == folder_id))}
            present = {str(p) for p in paths}
            for path, wf in known.items():  # files removed while still waiting
                if path not in present and wf.status == "waiting":
                    wf.status, wf.reason = "skipped", "File rimosso prima della fine della scrittura"
            for p in paths:
                stats["seen"] += 1
                wf = known.get(str(p))
                try:
                    st = p.stat()
                except OSError:
                    continue
                if wf is None:
                    db.add(WatchedFile(folder_id=folder_id, path=str(p), size=st.st_size, mtime=st.st_mtime,
                                       status="waiting", first_seen_at=now, last_change_at=now))
                    continue
                if wf.status != "waiting":
                    continue
                if st.st_size != wf.size or st.st_mtime != wf.mtime:
                    wf.size, wf.mtime, wf.last_change_at = st.st_size, st.st_mtime, now
                    wf.reason = "In scrittura"
                    continue
                stable_for = (now - wf.last_change_at).total_seconds()
                if stable_for < s.automation_stable_s:
                    continue
                self._consider(db, folder, wf, p, stable_for, stats, now)

    def _consider(self, db, folder: WatchFolder, wf: WatchedFile, p: Path, stable_for: float, stats: dict, now) -> None:
        s = get_settings()
        ext = p.suffix.lower()
        twin_mp4 = p.with_suffix(".mp4")
        # OBS remux handling: prefer the .mp4, never import both
        if ext == ".mkv" and twin_mp4.exists():
            wf.status, wf.reason = "skipped", "Remuxato da OBS in .mp4: importo solo l'mp4"
            stats["skipped"] += 1
            return
        if ext == ".mp4":
            mkv = db.scalar(select(WatchedFile).where(WatchedFile.folder_id == folder.id,
                                                      WatchedFile.path == str(p.with_suffix(".mkv"))))
            if mkv is not None and mkv.status in IMPORTED:
                wf.status, wf.reason = "skipped", "Remux di un .mkv già importato"
                stats["skipped"] += 1
                return
        if ext == ".mkv" and stable_for < s.automation_stable_s + s.automation_remux_grace_s:
            wf.reason = "In attesa di un eventuale remux .mp4 di OBS"
            return
        # Finalised container? (an MP4 still being recorded has no moov atom → ffprobe fails)
        try:
            info = ffmpeg.probe(p)
        except MediaError as e:
            if stable_for > s.automation_unreadable_timeout_s:
                wf.status, wf.reason = "error", f"Non leggibile come video: {e.message[:200]}"
            else:
                wf.reason = "File non ancora finalizzato"
            return
        try:
            sig = quick_signature(p)
        except OSError as e:
            wf.reason = f"Lettura non possibile: {e}"
            return
        wf.signature = sig
        dup_video = db.scalar(select(Video).where(Video.signature == sig))
        dup_file = db.scalar(select(WatchedFile).where(WatchedFile.signature == sig, WatchedFile.id != wf.id,
                                                       WatchedFile.status.in_(IMPORTED)))
        if dup_video is not None or dup_file is not None:
            what = f"«{dup_video.title}»" if dup_video else Path(dup_file.path).name
            wf.status, wf.reason = "duplicate", f"Già importato: {what}"
            stats["skipped"] += 1
            return

        rights, note = rights_for(db, folder)
        video = vs.create_video(
            db, file_path=p, original_filename=p.name, storage_mode=StorageMode.REFERENCED, file_size=p.stat().st_size,
            title=None, game=folder.game, creator=folder.creator_name or (folder.creator.name if folder.creator else ""),
            source=folder.source or f"Cartella monitorata: {folder.name or folder.path}",
            notes=f"Importato automaticamente da {folder.path}", rights=rights, status=VideoStatus.PENDING)
        video.signature = sig
        video.origin = "watch_folder"
        video.duration, video.width, video.height = info.duration, info.width, info.height
        wf.video_id, wf.status, wf.stage = video.id, "ready", "imported"
        wf.reason = note or "Importato, in attesa della pipeline"
        stats["imported"] += 1
        notify(db, f"Nuovo video importato: {p.name}", note, "/auto-import", kind="import")

    def _dispatch(self, now, stats: dict) -> None:
        from backend.workers.queue import job_manager

        with session_scope() as db:
            cfg = automation_settings(db)
            ok, reason = can_run_heavy(cfg)
            # retry pipelines interrupted by a restart
            for wf in db.scalars(select(WatchedFile).where(WatchedFile.status == "processing")).all():
                job = db.get(Job, wf.job_id) if wf.job_id else None
                if job is None or job.status in (JobStatus.FAILED.value, JobStatus.CANCELLED.value):
                    interrupted = job is not None and (job.error or "").startswith("Interrupted")
                    if interrupted and wf.attempts < MAX_PIPELINE_ATTEMPTS:
                        wf.status, wf.reason = "ready", "Ripresa dopo il riavvio"
                    elif job is not None and job.status == JobStatus.CANCELLED.value:
                        wf.status, wf.reason = "error", "Pipeline annullata"
                    else:
                        wf.status, wf.reason = "error", f"Pipeline fallita: {(job.error if job else 'job mancante')}"[:500]
            db.flush()  # sessions don't autoflush: make the files reset above visible to the query below
            pending = db.scalars(select(WatchedFile).where(or_(WatchedFile.status == "ready",
                                                               WatchedFile.status == "deferred"))
                                 .order_by(WatchedFile.first_seen_at)).all()
            to_submit = []
            for wf in pending:
                if not ok:
                    wf.status, wf.reason = "deferred", reason
                    stats["deferred"] += 1
                    continue
                wf.status, wf.stage, wf.attempts = "processing", "queued", wf.attempts + 1
                wf.reason = "In coda per la pipeline"
                to_submit.append((wf.id, wf.video_id))
        for wf_id, video_id in to_submit:
            job_id = job_manager.submit("auto.pipeline", {"watched_file_id": wf_id}, video_id=video_id)
            with session_scope() as db:
                wf = db.get(WatchedFile, wf_id)
                wf.job_id = job_id
            stats["submitted"] += 1

    def _check_permissions(self, now) -> None:
        """Hourly: warn before consents expire, mark creators whose consent expired."""
        if self._last_expiry_check and now - self._last_expiry_check < timedelta(hours=1):
            return
        self._last_expiry_check = now
        from backend.automation.creators import check_permission_expiry

        with session_scope() as db:
            check_permission_expiry(db, now.date())


watcher = Watcher()
