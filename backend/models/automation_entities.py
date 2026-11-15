"""Milestone 4B entities: watch folders, discovery (API keys, quota, cache), creators CRM, notifications."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.core.timeutil import utcnow
from backend.database.session import Base
from backend.models.entities import new_id


class AppSetting(Base):
    """Runtime-editable settings (automation pause, time window…)."""

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[Any] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class Creator(Base):
    __tablename__ = "creators"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(200))
    language: Mapped[str] = mapped_column(String(8), default="")
    channels: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)   # [{platform, channel_id, url, handle}]
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    score: Mapped[float] = mapped_column(default=0.0)
    notes: Mapped[str] = mapped_column(Text, default="")
    contact: Mapped[str] = mapped_column(String(300), default="")
    status: Mapped[str] = mapped_column(String(20), default="to_contact", index=True)
    status_history: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    source: Mapped[str] = mapped_column(String(20), default="manual")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    permissions: Mapped[list[CreatorPermission]] = relationship(
        back_populates="creator", cascade="all, delete-orphan", order_by="CreatorPermission.created_at.desc()")


class CreatorPermission(Base):
    """Recorded consent (proof) from a creator."""

    __tablename__ = "creator_permissions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    creator_id: Mapped[str] = mapped_column(ForeignKey("creators.id", ondelete="CASCADE"), index=True)
    granted_at: Mapped[date] = mapped_column(Date)
    expires_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    scope: Mapped[str] = mapped_column(Text, default="")
    commercial_use: Mapped[bool] = mapped_column(Boolean, default=False)
    attribution_text: Mapped[str] = mapped_column(Text, default="")
    restrictions: Mapped[str] = mapped_column(Text, default="")
    evidence_text: Mapped[str] = mapped_column(Text, default="")
    evidence_file: Mapped[str | None] = mapped_column(Text, nullable=True)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    expiry_notified: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    creator: Mapped[Creator] = relationship(back_populates="permissions")


class WatchFolder(Base):
    __tablename__ = "watch_folders"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(200), default="")
    path: Mapped[str] = mapped_column(Text)                       # Linux path (Windows paths translated)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    recursive: Mapped[bool] = mapped_column(Boolean, default=False)
    extensions: Mapped[list[str]] = mapped_column(JSON, default=list)
    mode: Mapped[str] = mapped_column(String(10), default="reference")
    game: Mapped[str] = mapped_column(String(120), default="GTA 6")
    creator_name: Mapped[str] = mapped_column(String(200), default="")
    source: Mapped[str] = mapped_column(String(300), default="")
    rights: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    pipeline: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    creator_id: Mapped[str | None] = mapped_column(ForeignKey("creators.id", ondelete="SET NULL"), nullable=True)
    last_scan_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    creator: Mapped[Creator | None] = relationship()


class WatchedFile(Base):
    __tablename__ = "watched_files"
    __table_args__ = (UniqueConstraint("folder_id", "path"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    folder_id: Mapped[str] = mapped_column(ForeignKey("watch_folders.id", ondelete="CASCADE"), index=True)
    path: Mapped[str] = mapped_column(Text)
    size: Mapped[int] = mapped_column(Integer, default=0)
    mtime: Mapped[float] = mapped_column(default=0.0)
    signature: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    # waiting → (stable) → importing → processing → done | skipped | duplicate | error | deferred
    status: Mapped[str] = mapped_column(String(20), default="waiting", index=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    stage: Mapped[str] = mapped_column(String(40), default="")
    video_id: Mapped[str | None] = mapped_column(ForeignKey("videos.id", ondelete="SET NULL"), nullable=True)
    job_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_change_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    folder: Mapped[WatchFolder] = relationship()


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    kind: Mapped[str] = mapped_column(String(30), default="info")
    title: Mapped[str] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(Text, default="")
    link: Mapped[str] = mapped_column(String(300), default="")
    read: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ApiKey(Base):
    """Encrypted credentials for discovery APIs (youtube_data, twitch)."""

    __tablename__ = "api_keys"

    provider: Mapped[str] = mapped_column(String(30), primary_key=True)
    credentials_encrypted: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class ApiQuota(Base):
    __tablename__ = "api_quota"
    __table_args__ = (UniqueConstraint("provider", "day"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String(30))
    day: Mapped[date] = mapped_column(Date)
    units: Mapped[int] = mapped_column(Integer, default=0)
    calls: Mapped[int] = mapped_column(Integer, default=0)


class SearchCache(Base):
    __tablename__ = "search_cache"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    provider: Mapped[str] = mapped_column(String(30))
    params: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    results: Mapped[Any] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
