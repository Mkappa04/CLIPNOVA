"""Publisher interface. Only official, authorised platform APIs are used.

Nothing here runs unless CLIPNOVA_PUBLISHING_ENABLED=true AND the user has
explicitly scheduled an approved clip with confirmation (see publishing/service.py).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import httpx


class PublisherError(Exception):
    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


@dataclass
class PublishRequest:
    video: Path
    title: str
    description: str
    caption: str
    hashtags: list[str]
    privacy: str = "private"           # private | unlisted | public (mapped per platform)


@dataclass
class PublishResult:
    remote_id: str
    url: str | None = None
    status: str = "published"          # published | processing
    refreshed_credentials: dict | None = None
    details: dict = field(default_factory=dict)


Log = Callable[[str], None]


class Publisher(ABC):
    platform: str = ""
    name: str = ""
    docs_url: str = ""
    credential_fields: list[str] = []
    notes: str = ""

    def missing_credentials(self, creds: dict) -> list[str]:
        return [f for f in self.credential_fields if not creds.get(f)]

    @abstractmethod
    def publish(self, req: PublishRequest, creds: dict, client: httpx.Client, log: Log) -> PublishResult:
        ...

    @staticmethod
    def raise_for(resp: httpx.Response, what: str) -> None:
        if resp.status_code < 400:
            return
        retryable = resp.status_code in (408, 429) or resp.status_code >= 500
        try:
            detail = resp.json()
        except ValueError:
            detail = resp.text[:300]
        raise PublisherError(f"{what}: HTTP {resp.status_code} {detail}", retryable=retryable)
