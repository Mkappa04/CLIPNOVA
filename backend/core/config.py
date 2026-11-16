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
    version: str = "2.0.0"

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

    # --- Transcription (faster-whisper). GPU model is used when enough VRAM is free.
    whisper_model: str = "large-v3-turbo"
    whisper_cpu_model: str = "small"
    whisper_compute_type_gpu: str = "int8_float16"
    whisper_compute_type_cpu: str = "int8"
    whisper_min_free_vram_mb: int = 2000
    whisper_keep_loaded: bool = False   # False = free VRAM after each job
    whisper_beam_size: int = 5

    # --- Analysis proxy (low-res copy used for scene/motion analysis)
    analysis_proxy_width: int = 320
    analysis_proxy_fps: int = 10
    analysis_window_s: float = 0.5
    # Decoder for the analysis pass. On i5-11400H + RTX 3060 Laptop, CPU decoding of 1080p60 H.264
    # benchmarked faster (30 s vs 51 s per 10 min) than NVDEC + download; the other is the fallback.
    analysis_decoder: str = "cpu"  # cpu | nvdec
    models_path: Path | None = None   # override model cache location (default: <data_dir>/models)
    publishing_enabled: bool = False
    publish_scheduler_interval_s: int = 30

    # --- Automation (watch folders)
    automation_enabled: bool = True          # background watcher thread
    automation_poll_s: int = 15              # polling interval (inotify is unreliable on /mnt/c)
    automation_stable_s: int = 10            # file size/mtime unchanged for this long = finished writing
    automation_remux_grace_s: int = 60       # wait for an OBS .mkv → .mp4 remux before importing a .mkv
    automation_unreadable_timeout_s: int = 900

    # --- Discovery (official APIs, search only)
    discovery_cache_ttl_h: float = 6.0
    youtube_daily_quota: int = 10000
    youtube_quota_reserve: int = 1000        # keep this many units unused
    twitch_game_name: str = "Grand Theft Auto VI"

    # Content generation: "none" = template mode (default, no LLM); "ollama" = optional local LLM
    llm_provider: str = "none"
    llm_model: str = "qwen3.5:4b"
    llm_url: str = "http://127.0.0.1:11434"
    llm_timeout_s: float = 120.0
    # Semantic clip detection with the local LLM: "auto" = use Ollama when the model is available, "off" = heuristics only
    semantic_scoring: str = "auto"
    # Model for semantic clip judgement (bigger = better story understanding); falls back to llm_model
    semantic_model: str = "qwen3:8b"
    # Vision model (Ollama) that describes the clip frames for the social copy generator ("" = off)
    vision_model: str = "qwen3.5:4b"
    # Social copy generator: "auto" = local LLM when available, "off" = deterministic texts only
    metadata_ai: str = "auto"
    # Hashtags per platform: [min, max]
    hashtags_instagram: tuple[int, int] = (3, 5)
    hashtags_tiktok: tuple[int, int] = (3, 5)
    hashtags_youtube: tuple[int, int] = (2, 4)
    # Embedding model used to learn your taste from approved/rejected clips (multilingual, small)
    preference_embed_model: str = "embeddinggemma"

    # Brand Kit: max logo upload size (MB) and max logo dimensions (px)
    brand_logo_max_mb: float = 5.0
    audio_import_max_mb: float = 60.0      # audio library: max size of an imported music/SFX file
    audio_import_max_s: float = 900.0      # max duration (15 min)
    brand_logo_max_px: int = 4096

    # Optional extra copy of every export package, e.g. a Windows folder:
    # /mnt/c/Users/<you>/Videos/CLIPNOVA  (so you can upload from the Windows browser)
    export_copy_dir: Path | None = None

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
    def models_dir(self) -> Path:
        return self.models_path or self.data_dir / "models"

    @property
    def previews_dir(self) -> Path:
        return self.data_dir / "previews"

    @property
    def exports_dir(self) -> Path:
        return self.data_dir / "exports"

    @property
    def secret_key_path(self) -> Path:
        return self.data_dir / "secret.key"

    @property
    def brand_dir(self) -> Path:
        return self.data_dir / "brand"

    @property
    def renders_dir(self) -> Path:
        return self.data_dir / "renders"

    @property
    def db_url(self) -> str:
        return self.database_url or f"sqlite:///{self.data_dir / 'clipnova.db'}"

    def ensure_dirs(self) -> None:
        for d in (self.data_dir, self.videos_dir, self.thumbnails_dir, self.logs_dir,
                  self.cache_dir, self.renders_dir, self.models_dir, self.previews_dir, self.exports_dir):
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
