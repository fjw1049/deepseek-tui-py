"""Data models for user identity, credentials, and auth sessions.

All models are Pydantic so they serialise cleanly to JSON for the app-server
API and the runtime-thread event log.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "AuthConfig",
    "AuthProviderConfig",
    "AuthResult",
    "AuthScheme",
    "AuthSession",
    "AuthTokenPayload",
    "CredentialOrigin",
    "CredentialRecord",
    "SessionState",
    "TokenStatus",
    "UserIdentity",
]

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class AuthScheme(str, Enum):
    """Authentication method for a provider."""

    API_KEY = "api_key"
    """Bearer token sent in the ``Authorization`` header."""

    OAUTH2 = "oauth2"
    """OAuth 2.0 client-credentials or authorization-code flow."""

    TOKEN = "token"
    """Short-lived JWT or opaque token obtained from a previous exchange."""

    NONE = "none"
    """No authentication required (local-only providers)."""


class CredentialOrigin(str, Enum):
    """Where a credential was resolved from."""

    KEYRING = "keyring"
    ENV = "env"
    CONFIG_FILE = "config_file"
    USER_INPUT = "user_input"
    REFRESHED = "refreshed"


class TokenStatus(str, Enum):
    """Liveness of a previously-issued token."""

    VALID = "valid"
    EXPIRED = "expired"
    REVOKED = "revoked"
    UNKNOWN = "unknown"


class SessionState(str, Enum):
    """Lifecycle state of an auth session."""

    ACTIVE = "active"
    STALE = "stale"
    LOCKED = "locked"
    CLOSED = "closed"


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------


class UserIdentity(BaseModel):
    """A local user identity that can be authenticated against providers.

    ``user_id`` is a stable local identifier (email, username, or UUID).
    ``display_name`` is what the UI shows. ``provider_accounts`` maps
    provider names (e.g. ``"deepseek"``) to the account name that was
    authenticated for that provider.
    """

    model_config = ConfigDict(extra="ignore")

    user_id: str
    display_name: str
    provider_accounts: dict[str, str] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def provider_account(self, provider: str) -> str | None:
        return self.provider_accounts.get(provider)


# ---------------------------------------------------------------------------
# Credentials
# ---------------------------------------------------------------------------


class CredentialRecord(BaseModel):
    """A stored credential for a specific provider.

    ``credential`` holds the actual secret value (API key, token, etc).
    The optional ``expires_at`` supports token-based auth with refresh;
    API keys are typically long-lived and may omit it.
    """

    model_config = ConfigDict(extra="ignore")

    provider: str
    credential: str
    scheme: AuthScheme = AuthScheme.API_KEY
    origin: CredentialOrigin = CredentialOrigin.KEYRING
    expires_at: datetime | None = None
    issued_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return datetime.now(timezone.utc) >= self.expires_at

    @property
    def masked_value(self) -> str:
        """Return a masked version of the credential for display."""
        raw = self.credential
        if len(raw) <= 8:
            return "****"
        return raw[:4] + "****" + raw[-4:]


# ---------------------------------------------------------------------------
# Auth sessions
# ---------------------------------------------------------------------------


class AuthSession(BaseModel):
    """An authenticated session for one provider.

    Created when a user authenticates and kept alive with periodic
    validation. When ``token_status`` moves past ``VALID`` the session
    must be re-established.
    """

    model_config = ConfigDict(extra="ignore")

    provider: str
    user_id: str
    credential_ref: str
    """Key into the credential store (e.g. the provider name)."""

    scheme: AuthScheme = AuthScheme.API_KEY
    state: SessionState = SessionState.ACTIVE
    token_status: TokenStatus = TokenStatus.UNKNOWN

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_validated_at: datetime | None = None
    expires_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def is_valid(self) -> bool:
        if self.state != SessionState.ACTIVE:
            return False
        if self.expires_at is not None and datetime.now(timezone.utc) >= self.expires_at:
            return False
        return self.token_status in (TokenStatus.VALID, TokenStatus.UNKNOWN)

    @property
    def age_seconds(self) -> float:
        return (datetime.now(timezone.utc) - self.created_at).total_seconds()


# ---------------------------------------------------------------------------
# AuthTokenPayload — JWT / verified-token payload
# ---------------------------------------------------------------------------


class AuthTokenPayload(BaseModel):
    """Payload extracted from a verified auth token (JWT or API key).

    ``sub`` is the subject identifier. ``role`` controls authorization level.
    ``scopes`` is an optional list of granted permission scopes.
    """

    model_config = ConfigDict(extra="ignore")

    sub: str = "anonymous"
    role: str = "anonymous"
    scopes: list[str] | None = None
    metadata: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Auth configuration
# ---------------------------------------------------------------------------


class AuthProviderConfig(BaseModel):
    """Per-provider authentication settings.

    Stored alongside ``ProviderConfig`` in the TOML config file under a
    new ``[auth.providers.X]`` key.
    """

    model_config = ConfigDict(extra="ignore")

    scheme: AuthScheme = AuthScheme.API_KEY
    """The authentication method this provider requires."""

    auth_url: str | None = None
    """OAuth / token endpoint for obtaining or refreshing credentials."""

    scopes: list[str] = Field(default_factory=list)
    """OAuth scopes to request during authentication."""

    token_ttl_seconds: int | None = None
    """Lifetime for short-lived tokens; ``None`` means no expiry."""

    validate_on_startup: bool = True
    """Whether to test the credential when the session is created."""


class AuthConfig(BaseModel):
    """Top-level auth configuration, mirroring a ``[auth]`` TOML section."""

    model_config = ConfigDict(extra="ignore")

    enabled: bool = True
    """Master switch — disable to skip all auth checks."""

    default_scheme: AuthScheme = AuthScheme.API_KEY
    """Fallback scheme when a provider has no explicit auth config."""

    session_ttl_seconds: int = 86_400
    """Default session lifetime (24 h)."""

    max_failures_before_lock: int = 5
    """Consecutive failed auth attempts before the session is locked."""

    providers: dict[str, AuthProviderConfig] = Field(default_factory=dict)
    """Per-provider overrides."""


# ---------------------------------------------------------------------------
# JWT / token payload
# ---------------------------------------------------------------------------


class AuthTokenPayload(BaseModel):
    """Decoded JWT payload carried in ``Authorization: Bearer <token>``.

    ``sub`` is the stable local user identifier (email / username / UUID).
    ``exp`` and ``iat`` are UNIX epoch seconds. ``provider`` is optional
    and scopes the token to a single LLM provider.
    """

    model_config = ConfigDict(extra="ignore")

    sub: str
    """Subject — stable local user identifier."""

    exp: int
    """Expiration (UNIX epoch seconds)."""

    iat: int = Field(default_factory=lambda: int(datetime.now(timezone.utc).timestamp()))
    """Issued-at (UNIX epoch seconds)."""

    provider: str | None = None
    """Optional provider scope — empty means all providers."""

    session_id: str | None = None
    """Optional session identifier for server-side revocation."""

    @property
    def is_expired(self) -> bool:
        from datetime import datetime, timezone

        return datetime.now(timezone.utc).timestamp() >= self.exp

    @property
    def identity(self) -> str:
        return self.sub


# ---------------------------------------------------------------------------
# Auth result returned by provider flows
# ---------------------------------------------------------------------------


class AuthResult(BaseModel):
    """Outcome of an authentication attempt."""

    model_config = ConfigDict(extra="ignore")

    ok: bool
    provider: str
    account: str | None = None
    """The authenticated account name, if known."""

    session: AuthSession | None = None
    credential: CredentialRecord | None = None
    error: str | None = None
    message: str | None = None
