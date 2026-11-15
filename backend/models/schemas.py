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
    analysis_status: str | None = None
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


# ---------------------------------------------------------------- analysis & clips (Milestone 2)
from backend.clip_detection.scoring import ScoringConfig  # noqa: E402
from backend.models.entities import ClipCategory  # noqa: E402


class AnalyzeRequest(BaseModel):
    language: Literal["auto", "it", "en"] = "auto"
    transcribe: bool = True
    force: bool = Field(False, description="Ignore cached proxy/audio/transcript")
    scoring: ScoringConfig | None = None


class AnalysisOut(ORMModel):
    status: str
    language: str
    transcription_device: str
    whisper_model: str
    scenes: list[float]
    stats: dict[str, Any]
    config: dict[str, Any]
    error: str | None
    updated_at: UTCDateTime


class ClipOut(ORMModel):
    id: str
    video_id: str
    start: float
    end: float
    duration: float
    category: str
    score: float
    confidence: float
    transcript: str
    reason: str
    suggested_title: str
    status: str
    origin: str
    peak_time: float | None
    language: str
    signals: dict[str, Any]
    category_scores: dict[str, Any]
    keywords: list[str]
    video_title: str = ""
    game: str = ""
    created_at: UTCDateTime
    updated_at: UTCDateTime


class ClipCreate(BaseModel):
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    category: ClipCategory = ClipCategory.GAMEPLAY_HIGHLIGHT
    suggested_title: str = Field("", max_length=300)


class ClipUpdate(BaseModel):
    start: float | None = Field(default=None, ge=0)
    end: float | None = Field(default=None, gt=0)
    category: ClipCategory | None = None
    suggested_title: str | None = Field(default=None, max_length=300)
    status: Literal["detected", "review", "rejected", "archived"] | None = None  # 'approved' arrives in M4


# ---------------------------------------------------------------- editing & renders (Milestone 3)
class RenderOut(ORMModel):
    id: str
    clip_id: str
    job_id: str | None
    status: str
    duration: float | None
    file_size: int | None
    width: int
    height: int
    encoder: str
    config: dict[str, Any]
    stats: dict[str, Any]
    error: str | None
    created_at: UTCDateTime
    finished_at: UTCDateTime | None
    clip_title: str = ""
    video_title: str = ""
    game: str = ""
    has_thumbnail: bool = False


class SubtitleWord(BaseModel):
    start: float
    end: float
    word: str


class SubtitleCue(BaseModel):
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    text: str = Field(max_length=300)
    words: list[SubtitleWord] = []


class SubtitlesIn(BaseModel):
    cues: list[SubtitleCue]
