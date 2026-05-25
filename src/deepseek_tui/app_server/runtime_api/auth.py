"""Optional bearer-token guard for /v1/* routes."""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse, Response


@dataclass(frozen=True, slots=True)
class ResolvedRuntimeAuth:
    token: str | None
    generated: bool


def resolve_runtime_auth(
    cli_token: str | None,
    env_token: str | None = None,
    *,
    insecure_no_auth: bool = False,
) -> ResolvedRuntimeAuth:
    """Mirror Rust ``resolve_runtime_auth`` (runtime_api.rs)."""
    token = _first_nonblank(cli_token) or _first_nonblank(env_token)
    if token:
        return ResolvedRuntimeAuth(token=token, generated=False)
    if insecure_no_auth:
        return ResolvedRuntimeAuth(token=None, generated=False)
    return ResolvedRuntimeAuth(token=_generate_runtime_token(), generated=True)


def _first_nonblank(value: str | None) -> str | None:
    if value is None:
        return None
    trimmed = value.strip()
    return trimmed or None


def _generate_runtime_token() -> str:
    return f"dst_{uuid.uuid4().hex}{uuid.uuid4().hex}"


def env_runtime_token() -> str | None:
    return _first_nonblank(os.environ.get("DEEPSEEK_RUNTIME_TOKEN"))


class RuntimeAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: object, *, auth_token: str | None) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self._token = (auth_token or "").strip()

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        if not self._token:
            return await call_next(request)
        path = request.url.path
        if path == "/health" or path == "/healthz":
            return await call_next(request)
        if not path.startswith("/v1/"):
            return await call_next(request)
        token = self._extract_token(request)
        if token != self._token:
            return JSONResponse(
                status_code=401,
                content={
                    "error": "runtime_auth_required",
                    "message": "Bearer token required for /v1/* routes.",
                },
            )
        return await call_next(request)

    @staticmethod
    def _extract_token(request: Request) -> str | None:
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            return auth[7:].strip()
        header = request.headers.get("x-deepseek-runtime-token", "").strip()
        if header:
            return header
        query = request.query_params.get("token", "").strip()
        return query or None
