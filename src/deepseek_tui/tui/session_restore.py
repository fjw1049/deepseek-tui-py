"""Session restore and approval handler.
"""

from __future__ import annotations



# ======================================================================
# From session_restore.py
# ======================================================================

"""Shared TUI session JSON → Engine + Transcript restore helpers."""


import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from deepseek_tui.protocol.messages import Message

logger = logging.getLogger(__name__)


def parse_session_messages(session_data: dict[str, Any], *, path: Path | None = None) -> list[Message]:
    """Validate session JSON and return restored messages."""
    messages_raw = session_data.get("messages")
    if not isinstance(messages_raw, list):
        raise ValueError("session file has no messages")
    return [Message.model_validate(msg) for msg in messages_raw]


def session_metadata(
    session_data: dict[str, Any], *, path: Path | None = None
) -> dict[str, Any]:
    """Return metadata dict, synthesizing minimal fields when absent."""
    metadata = session_data.get("metadata")
    if isinstance(metadata, dict):
        return metadata
    fallback_id = path.stem if path is not None else "session"
    return {"id": fallback_id, "message_count": len(session_data.get("messages") or [])}


def apply_messages_to_engine(engine: Any, messages: list[Message]) -> None:
    engine.session_messages = list(messages)


def try_restore_crash_checkpoint(engine: Any) -> tuple[list[Message], dict[str, Any]] | None:
    """Restore engine state from ``latest.json`` if a crash checkpoint exists."""
    from deepseek_tui.state.session import load_checkpoint

    try:
        raw = load_checkpoint()
    except (OSError, ValueError) as exc:
        logger.warning("crash checkpoint load failed: %s", exc)
        return None
    if raw is None:
        return None

    messages_raw = raw.get("messages")
    if not isinstance(messages_raw, list) or not messages_raw:
        return None

    try:
        messages = [Message.model_validate(msg) for msg in messages_raw]
    except Exception:  # noqa: BLE001 — pydantic validation errors
        logger.warning("crash checkpoint messages invalid", exc_info=True)
        return None

    apply_messages_to_engine(engine, messages)

    metadata = raw.get("metadata")
    meta: dict[str, Any] = metadata if isinstance(metadata, dict) else {}

    turn_counter = raw.get("turn_counter")
    if isinstance(turn_counter, int) and turn_counter >= 0:
        engine.turn_counter = turn_counter

    model = raw.get("model")
    if isinstance(model, str) and model.strip():
        engine.default_model = model.strip()

    return messages, meta


def session_started_at_iso(metadata: dict[str, Any], *, path: Path | None = None) -> str | None:
    """Best-effort ISO timestamp for filtering task sidebar rows after restore."""
    saved_at = metadata.get("saved_at")
    if isinstance(saved_at, str) and saved_at.strip():
        return saved_at.strip()
    exported_at = metadata.get("exported_at")
    if isinstance(exported_at, str) and exported_at.strip():
        return exported_at.strip()
    if path is not None:
        try:
            ts = path.stat().st_mtime
            return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
        except OSError:
            return None
    return None


# ======================================================================
# From approval_handler.py
# ======================================================================

"""TUI-backed approval handler — mirrors Rust ``tui/approval.rs``.

Stage 6.4: Bridges the engine's ``ApprovalHandler`` interface to the
Textual ``ApprovalDialog`` modal screen. When the engine requests
approval, this handler signals the TUI app to push the dialog and
awaits the user's response via an asyncio Future.
"""

import asyncio
from typing import TYPE_CHECKING

from deepseek_tui.engine.handle import ApprovalHandler
from deepseek_tui.policy.approval import ApprovalDecision, ApprovalRequest

if TYPE_CHECKING:
    from deepseek_tui.tui.app import DeepSeekTUI


class TUIApprovalHandler(ApprovalHandler):
    """Approval handler that shows a modal dialog in the TUI.

    The handler stores a reference to the Textual App so it can call
    ``push_screen`` from within the engine's async context.  The
    dialog result is communicated back via an ``asyncio.Future``.
    """

    def __init__(self, app: DeepSeekTUI) -> None:
        self._app = app

    async def request_approval(
        self,
        tool_call_id: str,
        request: ApprovalRequest,
    ) -> ApprovalDecision:
        from deepseek_tui.tui.dialogs import ApprovalDialog

        loop = asyncio.get_running_loop()
        future: asyncio.Future[bool] = loop.create_future()

        def _on_dismiss(result: bool | None) -> None:
            if not future.done():
                future.set_result(bool(result))

        risk = getattr(request, "risk_level", None)
        risk_str = (
            getattr(risk, "value", None) or (str(risk) if risk is not None else "")
        )
        presentation_risk = getattr(request, "presentation_risk", "") or ""
        if not presentation_risk and risk_str in ("medium", "high", "critical"):
            presentation_risk = "destructive"
        dialog = ApprovalDialog(
            tool_name=request.tool_name,
            reason=request.reason,
            input_summary=getattr(request, "input_summary", "") or "",
            risk_level=risk_str,
            title=getattr(request, "title", "") or "",
            impacts=list(getattr(request, "impacts", []) or []),
            presentation_risk=presentation_risk,
            primary_preview=getattr(request, "primary_preview", "") or "",
        )
        self._app.push_screen(dialog, _on_dismiss)

        approved = await future
        if approved:
            return ApprovalDecision.APPROVED
        return ApprovalDecision.DENIED
