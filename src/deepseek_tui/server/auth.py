"""Optional bearer-token guard for /v1/* routes."""

from __future__ import annotations



import os
import uuid
from dataclasses import dataclass
from pathlib import Path

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
    """Resolve the bearer token used for /v1/* routes.

    Priority (mirrors Rust ``resolve_runtime_auth`` plus a Python-side file
    fallback so CLI/Electron callers share the same secret without explicit
    plumbing):

    1. ``cli_token``                  — explicit ``--auth-token``
    2. ``env_token``                  — ``DEEPSEEK_RUNTIME_TOKEN``
    3. ``~/.deepseek/runtime.token``  — auto-managed file (Electron writes here)
    4. generate fresh + flag          — fall through to write_runtime_token_file

    ``--insecure`` skips steps 3–4 (no auth middleware) unless step 1–2
    already supplied an explicit token.
    """
    token = _first_nonblank(cli_token) or _first_nonblank(env_token)
    if token:
        return ResolvedRuntimeAuth(token=token, generated=False)
    if insecure_no_auth:
        return ResolvedRuntimeAuth(token=None, generated=False)
    cached = _read_runtime_token_file()
    if cached:
        return ResolvedRuntimeAuth(token=cached, generated=False)
    return ResolvedRuntimeAuth(token=_generate_runtime_token(), generated=True)


def _read_runtime_token_file() -> str | None:
    try:
        path = runtime_token_file()
    except Exception:  # noqa: BLE001
        return None
    if not path.exists():
        return None
    try:
        return _first_nonblank(path.read_text(encoding="utf-8"))
    except OSError:
        return None


def _first_nonblank(value: str | None) -> str | None:
    if value is None:
        return None
    trimmed = value.strip()
    return trimmed or None


def _generate_runtime_token() -> str:
    return f"dst_{uuid.uuid4().hex}{uuid.uuid4().hex}"


def env_runtime_token() -> str | None:
    return _first_nonblank(os.environ.get("DEEPSEEK_RUNTIME_TOKEN"))


def runtime_token_file() -> Path:
    """``~/.deepseek/runtime.token`` — auto-generated bearer cache.

    Persisting the generated token to a 0600 file lets the Electron app
    read it back without parsing stdout, and avoids leaking the token to
    process supervisors or log aggregators.
    """
    from deepseek_tui.config.paths import user_deepseek_dir

    return user_deepseek_dir() / "runtime.token"


def write_runtime_token_file(token: str) -> Path:
    path = runtime_token_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(str(path) + ".tmp")
    tmp.write_text(token, encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass  # best-effort on platforms without POSIX perms
    tmp.replace(path)
    return path


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
        # Default-deny: every other route (including /legacy/*) requires the
        # bearer token. A /v1-only allowlist previously left the legacy
        # prompt/tool routes callable by any local process.
        token = self._extract_token(request)
        if token != self._token:
            return JSONResponse(
                status_code=401,
                content={
                    "error": "runtime_auth_required",
                    "message": "Bearer token required for runtime API routes.",
                },
            )
        return await call_next(request)

    @staticmethod
    def _extract_token(request: Request) -> str | None:
        # Header-only: query/URL tokens leak into proxy logs and process lists.
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            return auth[7:].strip() or None
        header = request.headers.get("x-deepseek-runtime-token", "").strip()
        return header or None
