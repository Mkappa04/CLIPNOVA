"""Logging setup: console + rotating file in data/logs."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from backend.core.config import Settings

_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
_configured = False


def setup_logging(settings: Settings) -> None:
    global _configured
    if _configured:
        return
    settings.logs_dir.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(settings.log_level.upper())

    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter(_FORMAT))
    root.addHandler(console)

    file_handler = RotatingFileHandler(
        settings.logs_dir / "clipnova.log", maxBytes=5 * 1024 * 1024, backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(logging.Formatter(_FORMAT))
    root.addHandler(file_handler)

    logging.getLogger("multipart").setLevel(logging.WARNING)
    _configured = True
