"""Typed turn-error classification: error_code dispatch beats message text.

Regression guard: rewording a raise site in ``RuntimeThreadManager`` must not
silently flip the HTTP status/error code. Each typed exception maps to its
contractual (status, code) pair, and the substring fallback still classifies
plain ValueErrors that carry the historical wording.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from deepseek_tui.client.factory import MissingApiKeyError
from deepseek_tui.server.routes import classify_turn_value_error
from deepseek_tui.server.threads.errors import TurnConflictError, TurnNotActiveError
from deepseek_tui.workspace.execution import WorktreePendingError


@pytest.mark.parametrize(
    ("exc", "status", "code"),
    [
        (TurnConflictError("Thread already has an active turn"), 409, "turn_conflict"),
        (TurnNotActiveError("Thread is not loaded"), 409, "turn_not_active"),
        (
            TurnNotActiveError("Turn t1 is not active on thread thr1"),
            409,
            "turn_not_active",
        ),
        (WorktreePendingError(), 409, "worktree_pending"),
        (
            MissingApiKeyError("missing_api_key: no API key for provider 'kimi'"),
            400,
            "missing_api_key",
        ),
        # Reworded message, same type → same contract.
        (TurnConflictError("a turn is already running"), 409, "turn_conflict"),
        # Fallback: plain ValueErrors with the historical wording still map.
        (ValueError("Thread already has an active turn"), 409, "turn_conflict"),
        (ValueError("missing_api_key: none"), 400, "missing_api_key"),
        # Unknown ValueError → 400 invalid_request.
        (ValueError("prompt is required"), 400, "invalid_request"),
    ],
)
def test_classify_turn_value_error(exc: ValueError, status: int, code: str) -> None:
    out = classify_turn_value_error(exc)
    assert isinstance(out, HTTPException)
    assert out.status_code == status
    assert out.detail["error"] == code
