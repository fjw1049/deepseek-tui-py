"""Auth-specific error hierarchy.

Every auth operation raises one of these rather than generic exceptions.
Callers catch ``AuthError`` (leaf) or the top-level ``AuthError`` (base)
depending on how granular they need to be.
"""

from __future__ import annotations


class AuthError(Exception):
    """Base for all authentication errors."""


class CredentialNotFoundError(AuthError):
    """No stored credential exists for the requested identity or provider."""


class CredentialExpiredError(AuthError):
    """The stored credential has passed its expiry."""


class CredentialInvalidError(AuthError):
    """The stored credential is malformed or rejected by the provider."""


class ProviderAuthError(AuthError):
    """The provider rejected the attempted authentication."""


class SessionLockedError(AuthError):
    """The session is in a locked state and cannot be mutated."""


class SessionNotFoundError(AuthError):
    """No session exists for the given identity."""


class SessionExpiredError(AuthError):
    """The session has timed out and must be re-established."""


class AuthConfigError(AuthError):
    """An authentication option or configuration is inconsistent."""
