"""Pydantic API schemas."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer

from backend.models.entities import AuthorizationStatus, LicenseType


def _iso_utc(d: datetime) -> str:
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.isoformat()


UTCDateTime = Annotated[datetime, PlainSerializer(_iso_utc, return_type=str)]


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------- rights
class RightsIn(BaseModel):
    owner: str = ""
    source_url: str = ""
    license_type: LicenseType = LicenseType.UNKNOWN
    authorization_status: AuthorizationStatus = AuthorizationStatus.UNKNOWN
    commercial_use_allowed: bool = False
    attribution_required: bool = True
    attribution_text: str = ""
    expires_at: date | None = None
    restrictions: str = ""
    evidence: str = ""


class RightsOut(ORMModel):
    owner: str
    source_url: str
    license_type: str
    authorization_status: str
    commercial_use_allowed: bool
    attribution_required: bool
    attribution_text: str
    expires_at: date | None
    restrictions: str
    evidence: str
    updated_at: UTCDateTime


class RightsDecisionOut(BaseModel):
    purpose: str
    allowed: bool
    blockers: list[str]
    warnings: list[str]


# ---------------------------------------------------------------- videos
class VideoOut(ORMModel):
    id: str
    title: str
    original_filename: str
    file_path: str
    storage_mode: str
    game: str
    creator: str
    source: str
    notes: str
    file_size: int
    duration: float | None
    width: int | None
    height: int | None
    fps: float | None
    video_codec: str | None
    audio_codec: str | None
    has_audio: bool
    bitrate: int | None
    status: str
    error: str | None
    has_thumbnail: bool = False
    clip_count: int = 0
    rights: RightsOut | None = None
    created_at: UTCDateTime
    updated_at: UTCDateTime


class VideoUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=300)
    game: str | None = Field(default=None, max_length=120)
    creator: str | None = Field(default=None, max_length=200)
    source: str | None = Field(default=None, max_length=300)
    notes: str | None = None


class ImportPathRequest(BaseModel):
    path: str
    mode: Literal["reference", "copy"] = "reference"
    title: str | None = None
    game: str = "GTA 6"
    creator: str = ""
    source: str = ""
    notes: str = ""
    rights: RightsIn = Field(default_factory=RightsIn)


class ImportResult(BaseModel):
    videos: list[VideoOut]
    job_ids: list[str]
    warnings: list[str] = []


# ---------------------------------------------------------------- jobs
class JobOut(ORMModel):
    id: str
    type: str
    status: str
    progress: float
    message: str
    payload: dict[str, Any]
    result: dict[str, Any] | None
    error: str | None
    cancel_requested: bool
    video_id: str | None
    created_at: UTCDateTime
    started_at: UTCDateTime | None
    finished_at: UTCDateTime | None
