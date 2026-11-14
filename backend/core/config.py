"""Centralised configuration. Values come from environment variables prefixed
with ``CLIPNOVA_`` or from the project ``.env`` file."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]

SUPPORTED_VIDEO_EXTENSIONS = frozenset(
    {".mp4", ".mkv", ".mov", ".avi", ".webm", ".flv", ".m4v", ".ts", ".mts", ".wmv"}
)

LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_prefix="CLIPNOVA_",
        extra="ignore",
    )

    app_name: str = "CLIPNOVA"
    version: str = "0.1.0"

    host: str = "127.0.0.1"
    port: int = 8000
    allow_public_bind: bool = False

    data_dir: Path = PROJECT_ROOT / "data"
    database_url: str | None = None
    log_level: str = "INFO"

    max_upload_mb: int = 20480
    worker_concurrency: int = 1

    ffmpeg_bin: str = "ffmpeg"
    ffprobe_bin: str = "ffprobe"

    use_gpu: bool = True
    max_vram_mb: int = 4500

    default_language: str = "it"
    publishing_enabled: bool = False

    cors_origins: list[str] = ["http://127.0.0.1:5173", "http://localhost:5173"]

    @field_validator("worker_concurrency")
    @classmethod
    def _min_one(cls, v: int) -> int:
        return max(1, v)

    @field_validator("data_dir")
    @classmethod
    def _absolute(cls, v: Path) -> Path:
        return v if v.is_absolute() else (PROJECT_ROOT / v).resolve()

    @property
    def videos_dir(self) -> Path:
        return self.data_dir / "videos"

    @property
    def thumbnails_dir(self) -> Path:
        return self.data_dir / "thumbnails"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache"

    @property
    def renders_dir(self) -> Path:
        return self.data_dir / "renders"

    @property
    def db_url(self) -> str:
        return self.database_url or f"sqlite:///{self.data_dir / 'clipnova.db'}"

    def ensure_dirs(self) -> None:
        for d in (self.data_dir, self.videos_dir, self.thumbnails_dir, self.logs_dir,
                  self.cache_dir, self.renders_dir):
            d.mkdir(parents=True, exist_ok=True)

    def validate_security(self) -> None:
        if self.host not in LOOPBACK_HOSTS and not self.allow_public_bind:
            raise RuntimeError(
                f"Refusing to bind to '{self.host}': CLIPNOVA only listens on localhost. "
                "Set CLIPNOVA_ALLOW_PUBLIC_BIND=true only if you understand the risk."
            )


@lru_cache
def get_settings() -> Settings:
    return Settings()
