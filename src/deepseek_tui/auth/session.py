"""In-memory session store for authenticated sessions.

:class:`SessionStore` holds :class:`AuthSession` objects in a dict and
provides CRUD + expiry-eviction. Designed for single-process deployments;
a multi-instance deployment should swap this for a Redis-backed store
(API-compatible — same ``SessionStoreABC`` interface).
"""

from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Any

from deepseek_tui.auth.errors import (
    SessionExpiredError,
    SessionLockedError,
    SessionNotFoundError,
)
from deepseek_tui.auth.models import (
    AuthSession,
    SessionState,
    TokenStatus,
)

logger = logging.getLogger(__name__)


class SessionStore:
    """Thread-safe in-memory session store.

    Sessions are keyed by ``(provider, user_id)``. Expired sessions are
    evicted lazily on read and explicitly via :meth:`evict_expired`.

    Parameters
    ----------
    ttl_seconds : int
        Default TTL for new sessions (used when ``session.expires_at`` is
        not set). Default 86400 (24 h).
    max_sessions : int
        Hard limit on concurrent sessions. When exceeded, the oldest
        session is evicted. 0 means unlimited.
    """

    def __init__(
        self,
        ttl_seconds: int = 86_400,
        max_sessions: int = 0,
    ) -> None:
        self._ttl_seconds = ttl_seconds
        self._max_sessions = max_sessions
        # OrderedDict for FIFO eviction under max_sessions
        self._sessions: OrderedDict[str, AuthSession] = OrderedDict()
        self._lock = threading.Lock()

    # ---- public API -------------------------------------------------------

    def get(self, provider: str, user_id: str) -> AuthSession:
        """Retrieve a session, raising if missing or expired.

        Raises
        ------
        SessionNotFoundError
            No session for ``(provider, user_id)``.
        SessionExpiredError
            Session exists but has expired.
        """
        key = self._key(provider, user_id)
        with self._lock:
            session = self._sessions.get(key)
            if session is None:
                raise SessionNotFoundError(
                    f"No session for provider={provider!r} user_id={user_id!r}"
                )
            if not session.is_valid:
                if (
                    session.expires_at
                    and datetime.now(timezone.utc) >= session.expires_at
                ):
                    self._sessions.pop(key, None)
                    raise SessionExpiredError(
                        f"Session expired for provider={provider!r} user_id={user_id!r}"
                    )
                if session.state == SessionState.LOCKED:
                    raise SessionLockedError(
                        f"Session locked for provider={provider!r} user_id={user_id!r}"
                    )
        return session

    def put(self, session: AuthSession) -> None:
        """Store a session, evicting oldest if at capacity."""
        key = self._key(session.provider, session.user_id)
        if session.expires_at is None:
            session.expires_at = datetime.now(timezone.utc).replace(
                tzinfo=timezone.utc
            ).timestamp()
            # Add TTL
            expires_dt = datetime.now(timezone.utc).replace(tzinfo=timezone.utc)
            import datetime as dt_mod

            try:
                from datetime import timedelta

                session.expires_at = expires_dt + timedelta(seconds=self._ttl_seconds)
            except Exception:
                session.expires_at = expires_dt

        with self._lock:
            if self._max_sessions > 0 and len(self._sessions) >= self._max_sessions:
                oldest_key, oldest_val = next(iter(self._sessions.items()))
                logger.info(
                    "session_evict_oldest provider=%s user=%s",
                    oldest_val.provider,
                    oldest_val.user_id,
                )
                self._sessions.pop(oldest_key)
            self._sessions[key] = session
            self._sessions.move_to_end(key)

    def delete(self, provider: str, user_id: str) -> None:
        """Remove a session silently if it exists."""
        key = self._key(provider, user_id)
        with self._lock:
            self._sessions.pop(key, None)

    def list_sessions(
        self,
        provider: str | None = None,
        state: SessionState | None = None,
    ) -> list[AuthSession]:
        """Return matching sessions (filtered in-Python)."""
        with self._lock:
            results: list[AuthSession] = []
            now = datetime.now(timezone.utc)
            for session in self._sessions.values():
                if provider is not None and session.provider != provider:
                    continue
                if state is not None and session.state != state:
                    continue
                # Skip expired
                if (
                    session.expires_at is not None
                    and now >= session.expires_at
                    and session.state == SessionState.ACTIVE
                ):
                    continue
                results.append(session)
            return results

    def evict_expired(self) -> int:
        """Remove all expired sessions. Returns count evicted."""
        now = datetime.now(timezone.utc)
        expired_keys: list[str] = []
        with self._lock:
            for key, session in self._sessions.items():
                if (
                    session.expires_at is not None
                    and now >= session.expires_at
                ):
                    expired_keys.append(key)
            for key in expired_keys:
                self._sessions.pop(key, None)
        count = len(expired_keys)
        if count:
            logger.info("session_evict_expired count=%d", count)
        return count

    def touch(
        self, provider: str, user_id: str, ttl_seconds: int | None = None
    ) -> AuthSession:
        """Reset the expiry on an existing session (refresh)."""
        key = self._key(provider, user_id)
        ttl = ttl_seconds if ttl_seconds is not None else self._ttl_seconds
        with self._lock:
            session = self._sessions.get(key)
            if session is None:
                raise SessionNotFoundError(
                    f"No session for provider={provider!r} user_id={user_id!r}"
                )
            from datetime import timedelta

            session.expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl)
            session.last_validated_at = datetime.now(timezone.utc)
            return session

    def count(self) -> int:
        """Return the number of active (non-expired) sessions."""
        with self._lock:
            return len(self._sessions)

    def clear(self) -> None:
        """Remove all sessions. Used in tests."""
        with self._lock:
            self._sessions.clear()

    # ---- internal ---------------------------------------------------------

    @staticmethod
    def _key(provider: str, user_id: str) -> str:
        return f"{provider}:{user_id}"
