"""Authentication service — login, token issue/verify, credential management.

Provides :class:`AuthService` as the single entry point for all authentication
operations used by the FastAPI dependencies and CLI commands. Handles:

- API key validation against the configured key list
- JWT access token creation and verification
- Session lifecycle (create, validate, refresh, revoke)
- Credential storage via the secrets module
- Password hashing for user-based auth
"""

from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from pydantic import BaseModel, Field

from deepseek_tui.auth.errors import (
    AuthConfigError,
    AuthError,
    CredentialExpiredError,
    CredentialInvalidError,
    CredentialNotFoundError,
    SessionExpiredError,
    SessionLockedError,
)
from deepseek_tui.auth.models import (
    AuthConfig,
    AuthResult,
    AuthScheme,
    AuthSession,
    CredentialOrigin,
    CredentialRecord,
    SessionState,
    TokenStatus,
    UserIdentity,
)
from deepseek_tui.auth.session import SessionStore

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Token payload model
# ---------------------------------------------------------------------------


class AuthTokenPayload(BaseModel):
    """Decoded JWT payload for an access token.

    Fields follow the JWT registered claims convention where applicable.
    """

    sub: str
    """Subject — the user_id."""

    provider: str
    """Provider this token was issued for."""

    session_id: str
    """Link back to the parent AuthSession."""

    exp: int
    """Expiration time (Unix timestamp)."""

    iat: int
    """Issued at (Unix timestamp)."""

    token_type: str = "access"
    """Token type discriminator (reserved for future refresh tokens)."""


# ---------------------------------------------------------------------------
# AuthService
# ---------------------------------------------------------------------------


class AuthService:
    """Central authentication service.

    Wires together credential checking, JWT creation, and session management.
    Created once per app-server startup and attached to ``app.state``.

    Parameters
    ----------
    config : AuthConfig
        The ``[auth]`` section from the project config.
    session_store : SessionStore
        Shared session store instance.
    """

    def __init__(self, config: AuthConfig, session_store: SessionStore) -> None:
        self._config = config
        self._store = session_store
        self._jwt_secret = self._resolve_jwt_secret()
        self._algorithm = config.jwt_algorithm or "HS256"

    # ------------------------------------------------------------------
    # API key authentication
    # ------------------------------------------------------------------

    async def authenticate_api_key(self, token: str) -> AuthResult:
        """Validate an API key from the ``Authorization: Bearer`` header.

        Returns an ``AuthResult`` with ``ok=True`` and a minimal session if
        the key matches any configured API key.
        """
        if not self._config.enabled:
            return AuthResult(ok=True, provider="api_key", message="auth disabled")

        for key in self._config.api_keys:
            if _constant_time_compare(token, key):
                session = AuthSession(
                    provider="api_key",
                    user_id="api_user",
                    credential_ref="api_key",
                    scheme=AuthScheme.API_KEY,
                    state=SessionState.ACTIVE,
                    token_status=TokenStatus.VALID,
                )
                await self._store.add(session)
                return AuthResult(
                    ok=True,
                    provider="api_key",
                    account="api_user",
                    session=session,
                    message="API key authenticated",
                )

        return AuthResult(
            ok=False,
            provider="api_key",
            error="invalid_api_key",
            message="API key does not match any configured key",
        )

    # ------------------------------------------------------------------
    # JWT token management
    # ------------------------------------------------------------------

    async def create_access_token(
        self,
        user_id: str,
        provider: str = "jwt",
        ttl_minutes: int | None = None,
    ) -> tuple[str, AuthSession]:
        """Issue a new JWT access token and create a backing session.

        Returns ``(token_string, session)``.
        """
        ttl = ttl_minutes or self._config.token_expire_minutes
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(minutes=ttl)

        session = AuthSession(
            provider=provider,
            user_id=user_id,
            credential_ref=user_id,
            scheme=AuthScheme.TOKEN,
            state=SessionState.ACTIVE,
            token_status=TokenStatus.VALID,
            created_at=now,
            expires_at=expires_at,
        )
        await self._store.add(session)

        payload = AuthTokenPayload(
            sub=user_id,
            provider=provider,
            session_id=_derive_session_id(session),
            exp=int(expires_at.timestamp()),
            iat=int(now.timestamp()),
        )
        token = self._encode_jwt(payload.model_dump())
        return token, session

    async def verify_access_token(self, token: str) -> AuthTokenPayload:
        """Decode and verify a JWT access token.

        Raises
        ------
        CredentialInvalidError
            If the token is malformed, expired, or signature is wrong.
        SessionExpiredError
            If the backing session has expired or been closed.
        SessionLockedError
            If the backing session is locked.
        """
        try:
            payload_dict = self._decode_jwt(token)
        except AuthError:
            raise
        except Exception as exc:
            raise CredentialInvalidError(f"JWT decode failed: {exc}") from exc

        payload = AuthTokenPayload(**payload_dict)

        # Verify backing session is still valid.
        try:
            session = await self._store.validate(payload.session_id)
        except SessionExpiredError:
            raise
        except SessionLockedError:
            raise
        except Exception as exc:
            raise CredentialInvalidError(
                f"session check failed: {exc}"
            ) from exc

        # Bump last-validated timestamp.
        await self._store.touch(payload.session_id)
        return payload

    async def refresh_access_token(self, token: str) -> tuple[str, AuthSession] | None:
        """Refresh an expiring token if its session is still active.

        Returns ``(new_token, session)`` or ``None`` if the session cannot
        be extended (closed/locked/not found).
        """
        try:
            payload = await self.verify_access_token(token)
        except (AuthError, SessionExpiredError, SessionLockedError):
            return None

        session = await self._store.get(payload.session_id)
        # Only refresh sessions that are still ACTIVE.
        if session.state != SessionState.ACTIVE:
            return None

        return await self.create_access_token(
            user_id=payload.sub,
            provider=payload.provider,
        )

    async def revoke_access_token(self, token: str) -> bool:
        """Revoke (close) the backing session for a token."""
        try:
            payload = self._decode_jwt(token)
        except Exception:
            return False
        session_payload = AuthTokenPayload(**payload)
        try:
            await self._store.close(session_payload.session_id)
            logger.info("token_revoked session_id=%s", session_payload.session_id)
            return True
        except SessionNotFoundError:
            return False

    # ------------------------------------------------------------------
    # Credential management
    # ------------------------------------------------------------------

    async def store_credential(
        self,
        provider: str,
        credential: str,
        scheme: AuthScheme = AuthScheme.API_KEY,
        origin: CredentialOrigin = CredentialOrigin.USER_INPUT,
        expires_at: datetime | None = None,
    ) -> CredentialRecord:
        """Store a credential record (in-memory; optionally persisted)."""
        record = CredentialRecord(
            provider=provider,
            credential=credential,
            scheme=scheme,
            origin=origin,
            expires_at=expires_at,
        )
        # In a production build this would delegate to the secrets module's
        # keyring-backed store. For now, credentials live in the session.
        return record

    # ------------------------------------------------------------------
    # Config helpers
    # ------------------------------------------------------------------

    @property
    def enabled(self) -> bool:
        return self._config.enabled

    @property
    def exempt_paths(self) -> list[str]:
        return self._config.exempt_paths or ["/healthz", "/v1/healthz"]

    # ------------------------------------------------------------------
    # JWT internals
    # ------------------------------------------------------------------

    def _resolve_jwt_secret(self) -> str:
        if self._config.jwt_secret:
            return self._config.jwt_secret
        # Auto-generate a secret if none configured.
        generated = secrets.token_hex(32)
        logger.warning(
            "no jwt_secret configured; generated ephemeral secret "
            "(sessions will be invalidated on restart)"
        )
        return generated

    def _encode_jwt(self, payload: dict[str, Any]) -> str:
        from jose import jwt

        return jwt.encode(payload, self._jwt_secret, algorithm=self._algorithm)

    def _decode_jwt(self, token: str) -> dict[str, Any]:
        from jose import JWTError, jwt

        try:
            payload = jwt.decode(
                token,
                self._jwt_secret,
                algorithms=[self._algorithm],
            )
        except JWTError as exc:
            raise CredentialInvalidError(f"JWT verification failed: {exc}") from exc
        return payload


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def _constant_time_compare(a: str, b: str) -> bool:
    """Comparisons should be constant-time to avoid timing attacks."""
    if len(a) != len(b):
        return False
    result = 0
    for ca, cb in zip(a.encode(), b.encode()):
        result |= ca ^ cb
    return result == 0


def _derive_session_id(session: AuthSession) -> str:
    raw = f"{session.provider}:{session.user_id}:{session.created_at.timestamp()}"
    import hashlib

    return hashlib.sha256(raw.encode()).hexdigest()[:32]
