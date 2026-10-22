"""Engine lifecycle and human authorization wiring for CUA."""

from __future__ import annotations

import logging
import uuid

from deepseek_tui.cua.approval import approval_question, approval_response, auto_allow_response
from deepseek_tui.cua.session import CuaSession
from deepseek_tui.cua.tools import CUA_TOOLS, register_tools

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
        session = getattr(self, "_cua_session", None)
        if session is None:

            async def ask(params):
                if config.auto_allow_apps and (allowed := auto_allow_response(params)):
                    return allowed
                question = approval_question(params)
                # Nobody can answer a detached run; only always-allowed apps stay usable.
                if question is None or self.tool_context.metadata.get("unattended"):
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
        events = [self.handle.cancel_event, self.handle.pause.requested]
        try:
            # Only the first session in this process starts the runtime here; later
            # ones expose its catalog and connect on their first cua_js call.
            if not session.use_cached_catalog():
                await session.run(session.connect, events)
            register_tools(self.tool_registry, session, events)
            self._cua_error = ""
        except Exception as exc:
            await session.close()
            for name in CUA_TOOLS:
                self.tool_registry.remove(name)
            self._cua_error = str(exc)

    def _cua_surfaces(self) -> frozenset[str]:
        """Surfaces CUA can offer this turn, judged from config alone (never connects)."""
        config = getattr(getattr(self, "_app_config", None), "cua", None)
        if not config or not config.enabled or self.mode == "plan":
            return frozenset()
        from deepseek_tui.cua.readiness import vision_error

        if vision_error(
            self._app_config, self.tool_context.metadata.get("task_model") or self.default_model
        ):
            return frozenset()
        from deepseek_tui.surfaces import cua_surfaces

        return cua_surfaces(config)

    def _cua_prompt(self) -> str:
        if getattr(self, "_cua_error", ""):
            return "\n\nComputer use unavailable: " + self._cua_error
        session = getattr(self, "_cua_session", None)
        if session is None or self.mode == "plan":
            return ""
        config = getattr(getattr(self, "_app_config", None), "cua", None)
        unattended = (
            "\n\nThis run is unattended: app access requests are declined automatically, so "
            "computer use works only with apps the user already always-allows. When a step "
            "needs a person, stop and report exactly what remains."
            if self.tool_context.metadata.get("unattended")
            and not (config and config.auto_allow_apps)
            else ""
        )
        # Host guidance lives in prompts/computer_use.md (with the routing section);
        # only the runtime's own instructions and live run state are appended here.
        return "\n\n" + session.instructions + unattended

    async def _finish_cua_turn(self) -> None:
        session = getattr(self, "_cua_session", None)
        if session is not None:
            try:
                await session.end_turn(interrupted=self.handle.cancel_event.is_set())
                if self.handle.cancel_event.is_set():
                    await session.close()
            except Exception:
                logger.warning("CUA cleanup failed; connection closed", exc_info=True)

    async def _release_cua(self, *, reset: bool = False) -> None:
        """Free the desktop while someone else acts; reset also drops REPL bindings."""
        session = getattr(self, "_cua_session", None)
        if session is None:
            return
        try:
            await session.end_turn()
            if reset:
                await session.close()
        except Exception:
            logger.warning("CUA release failed; connection closed", exc_info=True)
        finally:
            if reset:
                # The caller tells the model directly; do not also fail its next call.
                session.reset_reason = ""

    async def _close_cua(self) -> None:
        session = getattr(self, "_cua_session", None)
        if session is not None:
            await session.close()
