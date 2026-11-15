"""Publication scheduling, dispatch and retry.

Guarantees (checked again at dispatch time, not only when scheduling):
- CLIPNOVA_PUBLISHING_ENABLED must be true (default false);
- the clip is approved/exported and the publication was created with explicit confirmation;
- the export's rights decision is re-evaluated (an authorization may have expired).
Retry: exponential backoff (2, 4, 8… minutes) up to max_attempts for transient errors.
"""

from __future__ import annotations

import logging
import threading
from datetime import timedelta
from pathlib import Path

import httpx
from sqlalchemy import or_, select

from backend.content_generation.templates import for_platform
from backend.core.config import get_settings
from backend.core.timeutil import utcnow
from backend.database.session import session_scope
from backend.models.entities import Publication, PublicationStatus
from backend.publishing.base import PublisherError, PublishRequest
from backend.publishing.crypto import decrypt_json, encrypt_json
from backend.publishing.registry import get_publisher
from backend.rights_management.policy import Purpose, evaluate
from backend.services.approval import APPROVED_STATES, attribution_text

log = logging.getLogger(__name__)
_client_factory = lambda: httpx.Client(timeout=httpx.Timeout(60.0, write=600.0))  # noqa: E731 (tests override)


def _append(pub: Publication, msg: str) -> None:
    pub.log = [*(pub.log or []), {"at": utcnow().isoformat() + "Z", "msg": msg}][-50:]


def preflight(pub: Publication) -> str | None:
    """Return a blocking reason, or None if the publication may proceed."""
    if not get_settings().publishing_enabled:
        return "Publishing is disabled (CLIPNOVA_PUBLISHING_ENABLED=false)"
    if not pub.approved_confirmation:
        return "Missing explicit confirmation"
    if pub.clip.status not in APPROVED_STATES:
        return f"Clip is no longer approved (status: {pub.clip.status})"
    decision = evaluate(pub.clip.video.rights, Purpose(pub.export.purpose))
    if not decision.allowed:
        return "Rights check failed: " + "; ".join(decision.blockers)
    video = _export_video(pub)
    if video is None:
        return "Export package video is missing"
    return None


def _export_video(pub: Publication) -> Path | None:
    folder = Path(pub.export.path or "")
    vids = sorted(folder.glob("*.mp4")) if folder.is_dir() else []
    return vids[0] if vids else None


def publish_now(pub_id: str, log_fn=None) -> str:
    """Run one publication attempt. Returns the resulting status."""
    with session_scope() as db:
        pub = db.get(Publication, pub_id)
        if pub is None or pub.status not in (PublicationStatus.SCHEDULED.value, PublicationStatus.PUBLISHING.value):
            return pub.status if pub else "missing"
        reason = preflight(pub)
        if reason:
            pub.status = PublicationStatus.FAILED.value
            pub.last_error = reason
            _append(pub, f"Blocked: {reason}")
            return pub.status
        pub.status = PublicationStatus.PUBLISHING.value
        pub.attempts += 1
        _append(pub, f"Attempt {pub.attempts}/{pub.max_attempts}")
        publisher = get_publisher(pub.platform)
        creds = decrypt_json(pub.account.credentials_encrypted)
        content = (pub.export.content_snapshot or {}).get("content", {})
        texts = for_platform(content, pub.platform, attribution_text(pub.clip))
        req = PublishRequest(video=_export_video(pub), title=texts.get("title", content.get("title", "")),
                             description=texts.get("description", ""), caption=texts.get("caption", ""),
                             hashtags=texts.get("hashtags", []), privacy=pub.privacy)
        account_id = pub.account_id

    messages: list[str] = []

    def plog(m: str) -> None:
        messages.append(m)
        if log_fn:
            log_fn(m)

    error: PublisherError | None = None
    result = None
    try:
        with _client_factory() as client:
            result = publisher.publish(req, creds, client, plog)
    except PublisherError as e:
        error = e
    except httpx.HTTPError as e:
        error = PublisherError(f"Network error: {e}", retryable=True)

    with session_scope() as db:
        pub = db.get(Publication, pub_id)
        for m in messages:
            _append(pub, m)
        if result is not None:
            pub.status = PublicationStatus.PUBLISHED.value
            pub.remote_id, pub.remote_url, pub.last_error = result.remote_id, result.url, None
            _append(pub, f"Done: {result.status} {result.url or result.remote_id}")
            if result.refreshed_credentials:
                acc = pub.account
                acc.credentials_encrypted = encrypt_json({**creds, **result.refreshed_credentials})
        else:
            assert error is not None
            pub.last_error = str(error)
            if error.retryable and pub.attempts < pub.max_attempts:
                delay = timedelta(minutes=2 ** pub.attempts)
                pub.status = PublicationStatus.SCHEDULED.value
                pub.next_attempt_at = utcnow() + delay
                _append(pub, f"Retryable error, next attempt in {int(delay.total_seconds() // 60)} min: {error}")
            else:
                pub.status = PublicationStatus.FAILED.value
                _append(pub, f"Failed: {error}")
                if "reconnect" in str(error).lower():
                    acc = db.get(type(pub.account), account_id)
                    if acc is not None:
                        acc.status = "needs_reconnect"
        return pub.status


def due_publications() -> list[str]:
    now = utcnow()
    with session_scope() as db:
        rows = db.scalars(select(Publication.id).where(
            Publication.status == PublicationStatus.SCHEDULED.value, Publication.scheduled_at <= now,
            or_(Publication.next_attempt_at.is_(None), Publication.next_attempt_at <= now))).all()
        return list(rows)


class Scheduler:
    """Background loop that hands due publications to the job queue."""

    def __init__(self) -> None:
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="clipnova-scheduler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
        self._thread = None

    def tick(self) -> int:
        from backend.workers.queue import job_manager

        if not get_settings().publishing_enabled:
            return 0
        ids = due_publications()
        for pid in ids:
            with session_scope() as db:
                pub = db.get(Publication, pid)
                if pub is None or pub.status != PublicationStatus.SCHEDULED.value:
                    continue
                pub.status = PublicationStatus.PUBLISHING.value  # claim it
            job_manager.submit("publish.post", {"publication_id": pid})
        return len(ids)

    def _loop(self) -> None:
        interval = max(5, get_settings().publish_scheduler_interval_s)
        while not self._stop.wait(interval):
            try:
                self.tick()
            except Exception as e:  # noqa: BLE001 - keep the loop alive
                log.error("Scheduler tick failed: %s", e)


scheduler = Scheduler()
