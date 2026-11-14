"""Domain exceptions mapped to consistent JSON error responses."""

from __future__ import annotations

from typing import Any


class ClipnovaError(Exception):
    status_code = 400
    code = "error"

    def __init__(self, message: str, *, code: str | None = None,
                 status_code: int | None = None, details: Any = None) -> None:
        super().__init__(message)
        self.message = message
        if code:
            self.code = code
        if status_code:
            self.status_code = status_code
        self.details = details

    def to_dict(self) -> dict[str, Any]:
        body: dict[str, Any] = {"error": self.code, "message": self.message}
        if self.details is not None:
            body["details"] = self.details
        return body


class NotFoundError(ClipnovaError):
    status_code = 404
    code = "not_found"


class ValidationFailed(ClipnovaError):
    status_code = 422
    code = "validation_failed"


class ConflictError(ClipnovaError):
    status_code = 409
    code = "conflict"


class MediaError(ClipnovaError):
    status_code = 422
    code = "media_error"


class RightsViolation(ClipnovaError):
    status_code = 403
    code = "rights_violation"
