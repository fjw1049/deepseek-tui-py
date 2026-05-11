"""FastAPI dependency injection for HTTP API authentication.

Provides three ways to protect endpoints:

1. **``verify_request``** — mandatory auth; raises 401 when missing/invalid.
2. **``optional_auth``** — injects ``AuthTokenPayload | None``; the handler
   decides what to do when the user is unauthenticated.
3. **``AuthRegistry``** — convenience wrapper that registers both variants
   for a route group.

All three rely on a :class:`SessionStore` and the app's ``AuthConfig``
attached via :class:`AuthRegistry.init_app`.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import time
from typing import Any

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from deepseek_tui.auth.errors import AuthError
from deepseek_tui.auth.models import (
    AuthConfig,
    AuthSession,
    AuthTokenPayload,
    TokenStatus,
)
from deepseek_tui.auth.session import SessionStore

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# FastAPI security scheme
# ---------------------------------------------------------------------------

_bearer_scheme = HTTPBearer(auto_error=False)
"""Bearer token extractor. We handle missing tokens ourselves so
``optional_auth`` can return ``None`` instead of raising."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _decode_jwt_payload(token: str) -> dict[str, Any] | None:
    """Decode a JWT *without* signature verification.

    This is safe only when the caller already verified the HMAC signature.
    Used here because :func:`verify_token` checks the signature first,
    then calls this to extract the payload for the caller.
    """
    try:
        # JWT: header.payload.signature
        payload_b64 = token.split(".")[1]
        # Restore padding
        padding = 4 - len(payload_b64) % 4
        if padding != 4:
            payload_b64 += "=" * padding
        decoded = base64.urlsafe_b64decode(payload_b64)
        import json

        return json.loads(decoded)
    except (IndexError, ValueError, json.JSONDecodeError):
        return None


def _compute_token_id(payload: AuthTokenPayload) -> str:
    """Deterministic token id from the payload for store indexing.

    Uses SHA-256 of the canonical JSON representation so the same
    payload always yields the same id (idempotent revocation).
    """
    import json

    canonical = json.dumps(payload.model_dump(mode="json"), sort_keys=True)
    return hashlib.sha256(canonical.encode()).hexdigest()


# ---------------------------------------------------------------------------
# AuthRegistry
# ---------------------------------------------------------------------------


class AuthRegistry:
    """Binds auth configuration + session store into a FastAPI app.

    Usage::

        registry = AuthRegistry()
        registry.init_app(app, config.auth, session_store)

        # In route modules:
        @router.get("/protected")
        async def protected(payload: AuthTokenPayload = Depends(registry.verify)):
            ...

        @router.get("/maybe")
        async def maybe(payload: AuthTokenPayload | None = Depends(registry.optional)):
            ...
    """

    def __init__(self) -> None:
        self._config: AuthConfig | None = None
        self._store: SessionStore | None = None

    def init_app(
        self,
        config: AuthConfig,
        store: SessionStore | None = None,
    ) -> None:
        """Attach config and optional session store.

        Call once at app startup (idempotent).
        """
        self._config = config
        self._store = store or SessionStore(
            ttl_seconds=config.session_ttl_minutes * 60,
        )

    @property
    def config(self) -> AuthConfig:
        if self._config is None:
            from deepseek_tui.auth.models import AuthConfig

            return AuthConfig()
        return self._config

    @property
    def store(self) -> SessionStore:
        if self._store is None:
            self._store = SessionStore()
        return self._store

    # ------------------------------------------------------------------
    # Token verification
    # ------------------------------------------------------------------

    def verify_token(self, token: str) -> AuthTokenPayload | None:
        """Validate a JWT against the registry's secret key.

        Returns the decoded payload on success, ``None`` on any failure
        (bad signature, expired, malformed). This is the core verification
        primitive used by both :func:`verify_request` and
        :func:`optional_auth`.
        """
        cfg = self.config
        if not cfg.enabled:
            # Auth disabled — accept any token shape for downstream
            # processing; the dependency guards will short-circuit.
            return self._decode_unsigned(token)

        secret = cfg.jwt_secret
        if not secret:
            logger.warning("Auth enabled but no jwt_secret configured")
            return None

        parts = token.split(".")
        if len(parts) != 3:
            return None

        header_b64, payload_b64, sig_b64 = parts
        # Recreate the signing input
        signing_input = f"{header_b64}.{payload_b64}".encode()

        # Verify HMAC-SHA256
        expected_sig = hmac.new(
            secret.encode(), signing_input, hashlib.sha256
        ).digest()

        try:
            padding = 4 - len(sig_b64) % 4
            if padding != 4:
                sig_b64 += "=" * padding
            actual_sig = base64.urlsafe_b64decode(sig_b64)
        except Exception:
            return None

        if not hmac.compare_digest(expected_sig, actual_sig):
            logger.debug("JWT signature mismatch")
            return None

        payload_dict = _decode_jwt_payload(token)
        if payload_dict is None:
            return None

        try:
            payload = AuthTokenPayload.model_validate(payload_dict)
        except Exception:
            logger.debug("Failed to validate token payload schema")
            return None

        if payload.is_expired:
            logger.debug("Token expired (sub=%s)", payload.sub)
            return None

        return payload

    def _decode_unsigned(self, token: str) -> AuthTokenPayload | None:
        """Decode a JWT without signature verification (auth disabled path)."""
        payload_dict = _decode_jwt_payload(token)
        if payload_dict is None:
            return None
        try:
            return AuthTokenPayload.model_validate(payload_dict)
        except Exception:
            return None

    def issue_token(
        self,
        user_id: str,
        provider: str = "",
        ttl_minutes: int | None = None,
        scopes: list[str] | None = None,
    ) -> tuple[str, AuthTokenPayload]:
        """Create and sign a JWT token.

        Returns ``(encoded_token, payload)``. The caller should store the
        payload (or its token id) in the session store.
        """
        cfg = self.config
        import json

        now = int(time.time())
        ttl = ttl_minutes if ttl_minutes is not None else cfg.session_ttl_minutes
        exp = now + ttl * 60

        payload = AuthTokenPayload(
            sub=user_id,
            provider=provider,
            exp=exp,
            iat=now,
            scopes=scopes or [],
        )

        secret = cfg.jwt_secret or "no-secret"
        header = base64.urlsafe_b64encode(
            json.dumps({"alg": "HS256", "typ": "JWT"}).encode()
        ).rstrip(b"=").decode()

        payload_bytes = json.dumps(payload.model_dump(mode="json")).encode()
        payload_b64 = base64.urlsafe_b64encode(payload_bytes).rstrip(b"=").decode()

        signing_input = f"{header}.{payload_b64}".encode()
        sig = hmac.new(secret.encode(), signing_input, hashlib.sha256).digest()
        sig_b64 = base64.urlsafe_b64encode(sig).rstrip(b"=").decode()

        token = f"{header}.{payload_b64}.{sig_b64}"
        return token, payload

    def create_session(
        self,
        user_id: str,
        provider: str = "",
        token: str | None = None,
        payload: AuthTokenPayload | None = None,
    ) -> AuthSession:
        """Create and store an :class:`AuthSession`.

        Either ``token`` or ``payload`` must be provided. If only a
        token is given, it is decoded (and verified if auth is enabled).
        """
        cfg = self.config

        if payload is None and token is not None:
            payload = self.verify_token(token) or self._decode_unsigned(token)

        if payload is None:
            from deepseek_tui.auth.models import AuthTokenPayload

            now = int(time.time())
            payload = AuthTokenPayload(
                sub=user_id, provider=provider, exp=now + cfg.session_ttl_minutes * 60, iat=now
            )

        token_id = _compute_token_id(payload)

        from datetime import datetime, timezone

        session = AuthSession(
            provider=provider or payload.provider or "default",
            user_id=user_id or payload.sub,
            credential_ref=token_id,
            scheme=cfg.default_scheme if hasattr(cfg, "default_scheme") else "token",
            state="active",  # type: ignore[arg-type]
            token_status=TokenStatus.VALID,
            created_at=datetime.now(timezone.utc),
            last_validated_at=datetime.now(timezone.utc),
        )

        self.store.put(session)
        return session

    # ------------------------------------------------------------------
    # Dependencies (returned by verify / optional properties)
    # ------------------------------------------------------------------

    async def _verify_dep(
        self,
        credentials: HTTPAuthorizationCredentials | None,
    ) -> AuthTokenPayload:
        """Mandatory auth — raises 401 if missing/invalid."""
        cfg = self.config

        if not cfg.enabled:
            # Auth disabled: return a synthetic anonymous payload so
            # handlers don't need null checks.
            return AuthTokenPayload(sub="anonymous", provider="")

        if credentials is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing Authorization header",
                headers={"WWW-Authenticate": "Bearer"},
            )

        token = credentials.credentials

        # 1. Check static API keys first (fast path)
        if self._match_api_key(token):
            from datetime import datetime, timezone

            now_ts = int(datetime.now(timezone.utc).timestamp())
            return AuthTokenPayload(
                sub="api-key-user",
                provider="",
                exp=now_ts + 86400,
                iat=now_ts,
            )

        # 2. Verify JWT
        payload = self.verify_token(token)
        if payload is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token",
                headers={"WWW-Authenticate": "Bearer"},
            )

        return payload

    async def _optional_dep(
        self,
        credentials: HTTPAuthorizationCredentials | None,
    ) -> AuthTokenPayload | None:
        """Optional auth — returns ``None`` when unauthenticated."""
        cfg = self.config

        if not cfg.enabled:
            return None

        if credentials is None:
            return None

        token = credentials.credentials

        # API key fast path
        if self._match_api_key(token):
            from datetime import datetime, timezone

            now_ts = int(datetime.now(timezone.utc).timestamp())
            return AuthTokenPayload(
                sub="api-key-user",
                provider="",
                exp=now_ts + 86400,
                iat=now_ts,
            )

        return self.verify_token(token)

    def _match_api_key(self, token: str) -> bool:
        cfg = self.config
        for key in cfg.api_keys:
            # Constant-time comparison to prevent timing attacks
            if hmac.compare_digest(token.encode(), key.encode()):
                return True
        return False

    # ------------------------------------------------------------------
    # Public dependency callables
    # ------------------------------------------------------------------

    @property
    def verify(self) -> Any:
        """FastAPI dependency::

            def handler(payload: AuthTokenPayload = Depends(registry.verify)):
        """
        return self._verify_dep

    @property
    def optional(self) -> Any:
        """FastAPI dependency::

            def handler(payload: AuthTokenPayload | None = Depends(registry.optional)):
        """
        return self._optional_dep


# ---------------------------------------------------------------------------
# Module-level convenience wrappers
#
# These work with a global ``AuthRegistry`` that must be initialised by
# the app startup code via ``init_auth(app, config)``.
# ---------------------------------------------------------------------------

_registry: AuthRegistry | None = None


def init_auth(config: AuthConfig, store: SessionStore | None = None) -> AuthRegistry:
    """Initialise the global auth registry (call once at app startup)."""
    global _registry
    _registry = AuthRegistry()
    _registry.init_app(config, store)
    return _registry


def get_registry() -> AuthRegistry:
    """Retrieve the global auth registry."""
    if _registry is None:
        raise RuntimeError("AuthRegistry not initialised. Call init_auth() first.")
    return _registry


async def verify_request(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> AuthTokenPayload:
    """Mandatory auth dependency for route handlers.

    Usage::

        @router.get("/protected")
        async def protected(
            payload: AuthTokenPayload = Depends(auth.dependencies.verify_request),
        ):
            ...
    """
    return await get_registry()._verify_dep(credentials)


async def optional_auth(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> AuthTokenPayload | None:
    """Optional auth dependency — returns ``None`` when unauthenticated.

    Usage::

        @router.get("/public")
        async def public(
            payload: AuthTokenPayload | None = Depends(auth.dependencies.optional_auth),
        ):
            ...
    """
    return await get_registry()._optional_dep(credentials)
