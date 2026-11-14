from __future__ import annotations

from datetime import datetime, timezone


def utcnow() -> datetime:
    """Naive UTC timestamp (SQLite stores no timezone; API layer re-attaches UTC)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)
