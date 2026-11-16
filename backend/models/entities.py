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
    # Webcam overlay region in the source frame, normalised 0..1: {x, y, w, h, source, confidence}
    webcam_region: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    status: Mapped[str] = mapped_column(String(20), default=VideoStatus.PENDING.value, index=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Quick content signature (size + sampled blocks): prevents importing the same file twice
    signature: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    origin: Mapped[str] = mapped_column(String(20), default="manual")  # manual | watch_folder

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
    edit_config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    # Subtitle cues in clip-relative seconds (None = generate from transcript)
    subtitles: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    # Last AI Editing Planner result (EditPlan JSON, see backend/editing/planner.py); reused while its key matches
    edit_plan: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    # Social copy: {language, title, hook, caption, description, hashtags, cta, generated_by}
    content: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    review_note: Mapped[str] = mapped_column(Text, default="")
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    video: Mapped[Video] = relationship(back_populates="clips")
    renders: Mapped[list[Render]] = relationship(back_populates="clip", cascade="all, delete-orphan",
                                                 order_by="Render.created_at.desc()")

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


class ExportPurpose(str, Enum):
    NON_COMMERCIAL = "non_commercial"
    COMMERCIAL = "commercial"


class Export(Base):
    """A manual-upload package for one or more platforms (data/exports/<id>)."""

    __tablename__ = "exports"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    clip_id: Mapped[str] = mapped_column(ForeignKey("clips.id", ondelete="CASCADE"), index=True)
    render_id: Mapped[str | None] = mapped_column(ForeignKey("renders.id", ondelete="SET NULL"), nullable=True)
    platforms: Mapped[list[str]] = mapped_column(JSON, default=list)
    purpose: Mapped[str] = mapped_column(String(20), default=ExportPurpose.COMMERCIAL.value)
    path: Mapped[str] = mapped_column(Text, default="")
    copied_to: Mapped[str | None] = mapped_column(Text, nullable=True)
    rights_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    content_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    clip: Mapped[Clip] = relationship()


class SocialAccount(Base):
    """A connected platform account. Tokens are encrypted at rest (Fernet)."""

    __tablename__ = "social_accounts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    platform: Mapped[str] = mapped_column(String(20), index=True)
    display_name: Mapped[str] = mapped_column(String(200), default="")
    credentials_encrypted: Mapped[str] = mapped_column(Text, default="")
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="connected")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class PublicationStatus(str, Enum):
    SCHEDULED = "scheduled"
    PUBLISHING = "publishing"
    PUBLISHED = "published"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Publication(Base):
    __tablename__ = "publications"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    clip_id: Mapped[str] = mapped_column(ForeignKey("clips.id", ondelete="CASCADE"), index=True)
    export_id: Mapped[str] = mapped_column(ForeignKey("exports.id", ondelete="CASCADE"))
    account_id: Mapped[str] = mapped_column(ForeignKey("social_accounts.id", ondelete="CASCADE"))
    platform: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default=PublicationStatus.SCHEDULED.value, index=True)
    privacy: Mapped[str] = mapped_column(String(20), default="private")
    scheduled_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    remote_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    remote_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    log: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    approved_confirmation: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    clip: Mapped[Clip] = relationship()
    export: Mapped[Export] = relationship()
    account: Mapped[SocialAccount] = relationship()


class RenderStatus(str, Enum):
    RENDERING = "rendering"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Render(Base):
    """A rendered vertical video for a clip (data/renders)."""

    __tablename__ = "renders"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    clip_id: Mapped[str] = mapped_column(ForeignKey("clips.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default=RenderStatus.RENDERING.value)
    path: Mapped[str | None] = mapped_column(Text, nullable=True)
    srt_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    ass_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    thumbnail_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration: Mapped[float | None] = mapped_column(Float, nullable=True)
    file_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    width: Mapped[int] = mapped_column(Integer, default=1080)
    height: Mapped[int] = mapped_column(Integer, default=1920)
    encoder: Mapped[str] = mapped_column(String(30), default="")
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    stats: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    clip: Mapped[Clip] = relationship(back_populates="renders")


class BrandAsset(Base):
    """A Brand Kit file (logo). Stored re-encoded under data/brand, never served by path."""

    __tablename__ = "brand_assets"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    owner: Mapped[str] = mapped_column(String(64), default="local", index=True)  # single local profile today
    kind: Mapped[str] = mapped_column(String(20), default="logo")
    original_name: Mapped[str] = mapped_column(String(255), default="")
    stored_name: Mapped[str] = mapped_column(String(80))
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    file_size: Mapped[int] = mapped_column(Integer)
    has_alpha: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


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
