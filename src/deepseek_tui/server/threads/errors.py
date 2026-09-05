"""Typed thread/turn errors carrying their HTTP error codes.

``routes.classify_turn_value_error`` dispatches on ``error_code`` instead of
matching message substrings, so rewording a raise site can no longer silently
flip a 409 into a 400. The substring checks in the classifier remain only as
a fallback for plain ``ValueError``s raised elsewhere.
"""

from __future__ import annotations


class CodedTurnError(ValueError):
    """``ValueError`` whose HTTP error code is part of its type."""

    error_code: str = "invalid_request"


class TurnConflictError(CodedTurnError):
    """A turn is already running on the thread (HTTP 409)."""

    error_code = "turn_conflict"


class TurnNotActiveError(CodedTurnError):
    """Thread not loaded, or the referenced turn is not the active one (409)."""

    error_code = "turn_not_active"
