"""Authentication module for the app-server HTTP API.

Supports two authentication modes (configurable via ``config.auth``):

1. **Static API keys** — pre-shared keys checked against
   ``Authorization: Bearer <key>`` headers.
2. **JWT sessions** — ephemeral tokens issued via ``POST /auth/login``
   using a valid API key as credential, then used for subsequent requests.

Both modes can be combined. The module provides FastAPI dependency
injection (:func:`verify_request`) and a rate-limiting middleware
(:class:`RateLimitMiddleware`).

Exempt paths (``config.auth.exempt_paths``) skip auth checks entirely.
"""

from __future__ import annotations

from deepseek_tui.auth.dependencies import AuthRegistry, optional_auth, verify_request
from deepseek_tui.auth.middleware import RateLimitMiddleware, setup_auth_middleware
from deepseek_tui.auth.models import AuthSession, AuthTokenPayload
from deepseek_tui.auth.session import SessionStore

__all__ = [
    "AuthRegistry",
    "AuthSession",
    "AuthTokenPayload",
    "RateLimitMiddleware",
    "SessionStore",
    "optional_auth",
    "setup_auth_middleware",
    "verify_request",
]
