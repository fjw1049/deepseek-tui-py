"""Engine lifecycle and human authorization wiring for CUA."""

from __future__ import annotations

import logging
import time
import uuid

from deepseek_tui.cua.approval import approval_question, approval_response
from deepseek_tui.cua.session import CuaSession
from deepseek_tui.cua.tools import CUA_TOOLS, HOST_GUIDANCE, register_tools

logger = logging.getLogger(__name__)


class CuaEngineMixin:
    async def _prepare_cua(self) -> None:
        config = getattr(getattr(self, "_app_config", None), "cua", None)
        if not config or not config.enabled or self.mode == "plan":
            return
        from deepseek_tui.cua.readiness import vision_error

        error = vision_error(
            self._app_config, self.tool_context.metadata.get("task_model") or self.default_model
        )
        if error:
            self._cua_error = error
            await self._close_cua()
            for name in CUA_TOOLS:
                self.tool_registry.remove(name)
            return
        if time.monotonic() < getattr(self, "_cua_retry_after", 0):
            return
        session = getattr(self, "_cua_session", None)
        if session is None:

            async def ask(params):
                question = approval_question(params)
                if question is None:
                    return {"action": "cancel"}
                response = await self._await_user_input_raw(
                    "cua-permission-" + uuid.uuid4().hex,
                    [question],
                    purpose="cua_permission",
                )
                return approval_response(params, response)

            session = CuaSession(
                config,
                self.tool_context.working_directory,
                self._cycle_session_id or uuid.uuid4().hex,
                ask,
            )
            self._cua_session = session
        try:
            await session.run(
                session.connect, [self.handle.cancel_event, self.handle.pause.requested]
            )
            register_tools(
                self.tool_registry, session, [self.handle.cancel_event, self.handle.pause.requested]
            )
            self._cua_error = ""
        except Exception as exc:
            await session.close()
            for name in CUA_TOOLS:
                self.tool_registry.remove(name)
            self._cua_error = str(exc)
            self._cua_retry_after = (
                0
                if self.handle.cancel_event.is_set() or self.handle.pause.requested.is_set()
                else time.monotonic() + 30
            )

    def _cua_prompt(self) -> str:
        if getattr(self, "_cua_error", ""):
            return "\n\nComputer use unavailable: " + self._cua_error
        session = getattr(self, "_cua_session", None)
        if session is None or self.mode == "plan":
            return ""
        return "\n\n" + HOST_GUIDANCE + "\n\n" + session.instructions

    async def _finish_cua_turn(self) -> None:
        session = getattr(self, "_cua_session", None)
        if session is not None:
            try:
                await session.end_turn(interrupted=self.handle.cancel_event.is_set())
                if self.handle.cancel_event.is_set():
                    await session.close()
            except Exception:
                logger.warning("CUA cleanup failed; connection closed", exc_info=True)

    async def _close_cua(self) -> None:
        session = getattr(self, "_cua_session", None)
        if session is not None:
            await session.close()
