"""HTTP errors matching GUI / Rust runtime_api shapes."""

from __future__ import annotations

from fastapi import HTTPException


def api_error(status_code: int, message: str, *, error: str | None = None) -> HTTPException:
    body: dict[str, str] = {"message": message}
    if error:
        body["error"] = error
    return HTTPException(status_code=status_code, detail=body)
