"""What can go wrong in a service call, independent of how it was asked for. The HTTP
routes turn `status` into a response code, the CLI turns `code` into an exit code and a
JSON error, the MCP server into a tool error."""

from __future__ import annotations


class ServiceError(Exception):
    code = "error"
    status = 500

    def __init__(self, detail: str, *, status: int | None = None) -> None:
        super().__init__(detail)
        self.detail = detail
        if status is not None:
            self.status = status


class NotFound(ServiceError):
    code = "not_found"
    status = 404


class Invalid(ServiceError):
    code = "invalid"
    status = 400


class Conflict(ServiceError):
    """The request can't happen in the current state (busy, not installed yet, ...)."""

    code = "conflict"
    status = 409


class NeedsPrerequisite(Conflict):
    """An external program (Tesseract, Ollama) has to be installed or started first."""

    code = "needs_prerequisite"


class Blocked(Conflict):
    """Refused by a setting or the hardware: the cloud switch is off, it doesn't fit."""

    code = "blocked"


class Unavailable(ServiceError):
    code = "unavailable"
    status = 503


class Failed(ServiceError):
    code = "failed"
    status = 500
