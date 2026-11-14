"""ORM entities. Enum-like fields are stored as strings for SQLite portability."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from enum import Enum
from typing import Any

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.core.timeutil import utcnow
from backend.database.session import Base


def new_id() -> str:
    return uuid.uuid4().hex


class VideoStatus(str, Enum):
    PENDING = "pending"
    COPYING = "copying"
    PROBING = "probing"
    READY = "ready"
    ANALYZING = "analyzing"
    ANALYZED = "analyzed"
    ERROR = "error"


class StorageMode(str, Enum):
    UPLOADED = "uploaded"      # file stored inside data/videos (managed by CLIPNOVA)
    COPIED = "copied"          # copied from a local path into data/videos (managed)
    REFERENCED = "referenced"  # original file left in place, never deleted by CLIPNOVA


class LicenseType(str, Enum):
    OWN_CONTENT = "own_content"
    CREATOR_PERMISSION = "creator_permission"
    LICENSED = "licensed"
    CC_BY = "cc_by"
    CC_BY_SA = "cc_by_sa"
    CC_BY_NC = "cc_by_nc"
    PUBLIC_DOMAIN = "public_domain"
    CREDIT_ONLY = "credit_only"  # "credit given" is NOT an authorization
    UNKNOWN = "unknown"


class AuthorizationStatus(str, Enum):
    AUTHORIZED = "authorized"
    PENDING = "pending"
    DENIED = "denied"
    UNKNOWN = "unknown"


class ClipStatus(str, Enum):
    DETECTED = "detected"
    EDITING = "editing"
    RENDERING = "rendering"
    REVIEW = "review"
    APPROVED = "approved"
    REJECTED = "rejected"
    ARCHIVED = "archived"
    EXPORTED = "exported"


class ClipCategory(str, Enum):
    FUNNY = "funny"
    RAGE = "rage"
    EPIC = "epic"
    FAIL = "fail"
    REACTION = "reaction"
    CLUTCH = "clutch"
    STORYTELLING = "storytelling"
    UNEXPECTED = "unexpected"
    GAMEPLAY_HIGHLIGHT = "gameplay_highlight"


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


ACTIVE_JOB_STATUSES = (JobStatus.QUEUED.value, JobStatus.RUNNING.value)


class Video(Base):
    __tablename__ = "videos"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    title: Mapped[str] = mapped_column(String(300))
    original_filename: Mapped[str] = mapped_column(String(500))
    file_path: Mapped[str] = mapped_column(Text)
    storage_mode: Mapped[str] = mapped_column(String(20), default=StorageMode.UPLOADED.value)

    game: Mapped[str] = mapped_column(String(120), default="GTA 6", index=True)
    creator: Mapped[str] = mapped_column(String(200), default="")
    source: Mapped[str] = mapped_column(String(300), default="")
    notes: Mapped[str] = mapped_column(Text, default="")

    file_size: Mapped[int] = mapped_column(Integer, default=0)
    duration: Mapped[float | None] = mapped_column(Float, nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fps: Mapped[float | None] = mapped_column(Float, nullable=True)
    video_codec: Mapped[str | None] = mapped_column(String(50), nullable=True)
    audio_codec: Mapped[str | None] = mapped_column(String(50), nullable=True)
    has_audio: Mapped[bool] = mapped_column(Boolean, default=False)
    bitrate: Mapped[int | None] = mapped_column(Integer, nullable=True)
    thumbnail_path: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[str] = mapped_column(String(20), default=VideoStatus.PENDING.value, index=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    rights: Mapped[RightsRecord | None] = relationship(
        back_populates="video", uselist=False, cascade="all, delete-orphan", lazy="joined"
    )
    clips: Mapped[list[Clip]] = relationship(back_populates="video", cascade="all, delete-orphan")
    analysis: Mapped[Analysis | None] = relationship(
        back_populates="video", uselist=False, cascade="all, delete-orphan"
    )

    @property
    def is_managed_file(self) -> bool:
        return self.storage_mode in (StorageMode.UPLOADED.value, StorageMode.COPIED.value)


class RightsRecord(Base):
    __tablename__ = "rights_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    video_id: Mapped[str] = mapped_column(ForeignKey("videos.id", ondelete="CASCADE"), unique=True)

    owner: Mapped[str] = mapped_column(String(200), default="")
    source_url: Mapped[str] = mapped_column(Text, default="")
    license_type: Mapped[str] = mapped_column(String(30), default=LicenseType.UNKNOWN.value)
    authorization_status: Mapped[str] = mapped_column(
        String(20), default=AuthorizationStatus.UNKNOWN.value
    )
    commercial_use_allowed: Mapped[bool] = mapped_column(Boolean, default=False)
    attribution_required: Mapped[bool] = mapped_column(Boolean, default=True)
    attribution_text: Mapped[str] = mapped_column(Text, default="")
    expires_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    restrictions: Mapped[str] = mapped_column(Text, default="")
    evidence: Mapped[str] = mapped_column(Text, default="")

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    video: Mapped[Video] = relationship(back_populates="rights")


class Clip(Base):
    __tablename__ = "clips"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    video_id: Mapped[str] = mapped_column(ForeignKey("videos.id", ondelete="CASCADE"), index=True)
    start: Mapped[float] = mapped_column(Float)
    end: Mapped[float] = mapped_column(Float)
    category: Mapped[str] = mapped_column(String(30), default=ClipCategory.GAMEPLAY_HIGHLIGHT.value)
    score: Mapped[float] = mapped_column(Float, default=0.0)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    transcript: Mapped[str] = mapped_column(Text, default="")
    reason: Mapped[str] = mapped_column(Text, default="")
    suggested_title: Mapped[str] = mapped_column(String(300), default="")
    status: Mapped[str] = mapped_column(String(20), default=ClipStatus.DETECTED.value, index=True)
    origin: Mapped[str] = mapped_column(String(10), default="auto")  # auto | manual
    peak_time: Mapped[float | None] = mapped_column(Float, nullable=True)
    language: Mapped[str] = mapped_column(String(8), default="")
    signals: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    category_scores: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    keywords: Mapped[list[str]] = mapped_column(JSON, default=list)
    preview_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    video: Mapped[Video] = relationship(back_populates="clips")

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


class AnalysisStatus(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class Analysis(Base):
    """Result of the analysis pipeline for one video (cached artefacts live in data/cache/<video_id>)."""

    __tablename__ = "analyses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    video_id: Mapped[str] = mapped_column(ForeignKey("videos.id", ondelete="CASCADE"), unique=True)
    status: Mapped[str] = mapped_column(String(20), default=AnalysisStatus.RUNNING.value)
    language: Mapped[str] = mapped_column(String(8), default="")
    transcription_device: Mapped[str] = mapped_column(String(10), default="")
    whisper_model: Mapped[str] = mapped_column(String(60), default="")
    transcript_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    timeline_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    scenes: Mapped[list[float]] = mapped_column(JSON, default=list)
    stats: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    video: Mapped[Video] = relationship(back_populates="analysis")


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    type: Mapped[str] = mapped_column(String(60), index=True)
    status: Mapped[str] = mapped_column(String(20), default=JobStatus.QUEUED.value, index=True)
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    message: Mapped[str] = mapped_column(Text, default="")
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    video_id: Mapped[str | None] = mapped_column(
        ForeignKey("videos.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
