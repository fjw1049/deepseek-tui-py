"""Auth middleware for the FastAPI app-server.

Provides:

- :class:`RateLimitMiddleware` — per-IP rate limiting with a sliding
  window counter.
- :func:`setup_auth_middleware` — one-shot wiring that attaches the
  auth registry and rate limiter to the FastAPI app.

Both honour ``AuthConfig.enabled`` — when auth is disabled they pass
all requests through without inspection.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from deepseek_tui.auth.dependencies import AuthRegistry
from deepseek_tui.auth.models import AuthConfig
from deepseek_tui.auth.session import SessionStore

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_X_RATELIMIT_REMAINING = "X-RateLimit-Remaining"
_X_RATELIMIT_RESET = "X-RateLimit-Reset"

# ---------------------------------------------------------------------------
# Rate-limit middleware
# ---------------------------------------------------------------------------


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Per-IP rate limiting using a sliding-window counter.

    Tracks request counts by client IP within a fixed 60-second window.
    When the limit is exceeded, returns ``429 Too Many Requests`` with
    standard rate-limit headers.

    Parameters
    ----------
    app:
        The ASGI app to wrap.
    max_requests:
        Maximum requests per minute per IP.
    exempt_paths:
        URL paths that bypass rate limiting (e.g. health checks).
    """

    def __init__(
        self,
        app: Any,
        max_requests: int = 60,
        exempt_paths: list[str] | None = None,
    ) -> None:
        super().__init__(app)
        self._max_requests = max_requests
        self._exempt_paths = set(exempt_paths or ["/healthz", "/v1/healthz"])
        self._windows: dict[str, _SlidingWindow] = {}
        self._cleanup_at: float = time.monotonic()

    async def dispatch(
        self, request: Request, call_next: Any
    ) -> Response:
        # Exempt paths always pass.
        if request.url.path in self._exempt_paths:
            return await call_next(request)

        client_ip = self._client_ip(request)
        now = time.monotonic()

        window = self._windows.get(client_ip)
        if window is None:
            window = _SlidingWindow(limit=self._max_requests)
            self._windows[client_ip] = window

        remaining = window.record_request(now)
        self._maybe_cleanup(now)

        if remaining < 0:
            reset_after = int(window.reset_at - now) if window.reset_at > now else 1
            response = JSONResponse(
                status_code=429,
                content={
                    "error": "rate_limit_exceeded",
                    "message": "Too many requests. Try again shortly.",
                    "retry_after_seconds": reset_after,
                },
                headers={
                    _X_RATELIMIT_REMAINING: "0",
                    _X_RATELIMIT_RESET: str(reset_after),
                    "Retry-After": str(reset_after),
                },
            )
            return response

        response = await call_next(request)
        reset_after = int(window.reset_at - now) if window.reset_at > now else 1
        response.headers[_X_RATELIMIT_REMAINING] = str(max(0, remaining))
        response.headers[_X_RATELIMIT_RESET] = str(reset_after)
        return response

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _client_ip(request: Request) -> str:
        """Extract the client IP from headers or the request's remote addr."""
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip.strip()
        client = request.client
        if client is not None:
            return client.host
        return "unknown"

    def _maybe_cleanup(self, now: float) -> None:
        """Evict stale windows every 60 seconds."""
        if now - self._cleanup_at < 60.0:
            return
        self._cleanup_at = now
        stale: list[str] = []
        for ip, window in self._windows.items():
            if now >= window.reset_at:
                stale.append(ip)
        for ip in stale:
            del self._windows[ip]


# ---------------------------------------------------------------------------
# Setup helper
# ---------------------------------------------------------------------------


def setup_auth_middleware(
    app: FastAPI,
    config: AuthConfig,
    store: SessionStore | None = None,
) -> AuthRegistry:
    """Wire auth components into a FastAPI app.

    Attaches the following to ``app.state``:

    - ``auth_registry`` — an :class:`AuthRegistry` instance
    - ``session_store`` — the :class:`SessionStore` instance

    Also adds :class:`RateLimitMiddleware` when ``rate_limit_per_minute``
    is positive.

    Parameters
    ----------
    app:
        The FastAPI application.
    config:
        Auth configuration from the user's TOML file.
    store:
        Optional pre-configured session store. If omitted, a default
        in-memory store is created (no file persistence).

    Returns
    -------
    AuthRegistry
        The registry attached to ``app.state.auth_registry``.
    """
    if store is None:
        store = SessionStore()

    registry = AuthRegistry(store=store, config=config)
    app.state.auth_registry = registry
    app.state.session_store = store

    # Add rate-limiting middleware if configured.
    if config.rate_limit_per_minute > 0:
        exempt = list(config.exempt_paths)
        middleware = RateLimitMiddleware(
            app,
            max_requests=config.rate_limit_per_minute,
            exempt_paths=exempt,
        )
        app.add_middleware(
            type(middleware),  # type: ignore[arg-type]
            max_requests=config.rate_limit_per_minute,
            exempt_paths=exempt,
        )

    logger.info(
        "Auth middleware configured: enabled=%s rate_limit=%d/min",
        config.enabled,
        config.rate_limit_per_minute,
    )
    return registry


# ---------------------------------------------------------------------------
# Internal data types
# ---------------------------------------------------------------------------


class _SlidingWindow:
    """Per-IP sliding window counter.

    Tracks request timestamps in a deque. On each request, it drops
    timestamps older than 60 seconds, then counts the remaining entries.
    If the count exceeds the limit, the request is rejected.
    """

    __slots__ = ("_timestamps", "_limit", "_window_seconds", "reset_at")

    def __init__(self, limit: int, window_seconds: int = 60) -> None:
        self._timestamps: list[float] = []
        self._limit = limit
        self._window_seconds = window_seconds
        self.reset_at: float = 0.0

    def record_request(self, now: float) -> int:
        """Record a request and return remaining capacity.

        Returns the number of requests still allowed before hitting the
        limit. Returns -1 when the limit is exceeded.
        """
        cutoff = now - self._window_seconds
        # Prune old entries.
        self._timestamps = [t for t in self._timestamps if t > cutoff]
        self._timestamps.append(now)
        # Update reset_at to the end of the current window.
        self.reset_at = now + self._window_seconds
        remaining = self._limit - len(self._timestamps)
        return remaining if remaining >= 0 else -1
