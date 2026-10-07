"""ServiceError -> HTTP error, for routes that call docbox.service."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from fastapi import HTTPException

from docbox.service.errors import ServiceError


@contextmanager
def http_errors() -> Iterator[None]:
    try:
        yield
    except ServiceError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.detail) from None
