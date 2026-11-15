"""Encryption at rest for platform credentials (Fernet: AES-128-CBC + HMAC-SHA256).

Key source, in order: CLIPNOVA_SECRET_KEY env var, else data/secret.key (created
on first use with 0600 permissions). Losing the key means re-entering credentials.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from backend.core.config import get_settings


@lru_cache
def _fernet() -> Fernet:
    env = os.environ.get("CLIPNOVA_SECRET_KEY")
    if env:
        return Fernet(env.encode())
    path = get_settings().secret_key_path
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as fh:
            fh.write(Fernet.generate_key())
    return Fernet(path.read_bytes().strip())


def encrypt_json(data: dict) -> str:
    return _fernet().encrypt(json.dumps(data).encode()).decode()


def decrypt_json(token: str) -> dict:
    if not token:
        return {}
    try:
        return json.loads(_fernet().decrypt(token.encode()))
    except InvalidToken as e:
        raise ValueError("Cannot decrypt credentials (secret key changed?)") from e


def mask(creds: dict) -> dict:
    """Safe view for the API: never return secrets, only which fields are set."""
    return {k: ("••••" + str(v)[-4:] if v and len(str(v)) > 8 else "••••") if v else "" for k, v in creds.items()}
