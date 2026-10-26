"""Child agents share desktop arbitration, but never a parent's REPL or grants."""

from __future__ import annotations

import inspect
import uuid

from deepseek_tui.cua.approval import approval_question, auto_allow_response
from deepseek_tui.cua.session import CuaSession
from deepseek_tui.cua.tools import CUA_TOOLS, register_tools


async def prepare_subagent_cua(agent, runtime, context, registry, allowed_tools, cancel):
    config = getattr(runtime.config, "cua", None)
    allowed = CUA_TOOLS if allowed_tools is None else CUA_TOOLS.intersection(allowed_tools)
    if not config or not config.enabled or not allowed:
        return None
    from deepseek_tui.cua.readiness import vision_error

    error = vision_error(
        runtime.config, context.metadata.get("task_model") or runtime.config.default_text_model
    )
    if error:
        context.metadata["cua_error"] = error
        return None

    async def ask(params):
        from deepseek_tui.tools.approval import ApprovalDecision, build_approval_request
        from deepseek_tui.tools.registry import ToolCapability

        if config.auto_allow_apps and (allowed := auto_allow_response(params)):
            return allowed
        locale = getattr(getattr(runtime.config, "ui", None), "locale", "zh")
        question = approval_question(params, locale)
        handler = getattr(runtime, "approval_handler", None)
        if question is None or handler is None:
            return {"action": "cancel"}
        request = build_approval_request(
            "cua_permission",
            [ToolCapability.REQUIRES_APPROVAL],
            reason=question["question"] + ("\n仅允许本次访问" if locale.startswith("zh") else "\nAllow once only"),
        )
        request.force_prompt = True
        call_id = "cua-permission-" + uuid.uuid4().hex
        with handler.approval_scope(call_id, request):
            emit = getattr(runtime, "emit_event", None)
            if emit is not None:
                from deepseek_tui.engine.events import ApprovalRequiredEvent

                emitted = emit(ApprovalRequiredEvent(tool_call_id=call_id, request=request))
                if inspect.isawaitable(emitted):
                    await emitted
            decision = await handler.request_approval(call_id, request)
        if decision in {ApprovalDecision.APPROVED, ApprovalDecision.APPROVED_SESSION}:
            # A host session choice never expands the upstream per-app grant.
            return {"action": "accept", "content": {}}
        return {"action": "decline"}

    session = CuaSession(config, context.working_directory, "subagent-" + agent.id, ask)
    # Keep child uncertainty visible to the parent operation panel, including
    # after the child loop closes its runtime connection.
    if not hasattr(runtime.manager, "cua_sessions"):
        runtime.manager.cua_sessions = {}
    runtime.manager.cua_sessions[agent.id] = session
    session.lease.owner = getattr(runtime.manager, "cua_owner_id", None) or session.session_id
    try:
        events = [cancel, agent.cancel_token, agent.interrupt_event]
        if agent.parent_cancel is not None:
            events.append(agent.parent_cancel)
        pause = getattr(runtime.manager, "parent_pause", None)
        if pause is not None:
            events.append(pause.requested)
        # With a catalog from this process, a child that never touches the desktop
        # never starts the runtime; its first cua_js call connects.
        if not session.use_cached_catalog():
            await session.run(session.connect, events)
        register_tools(registry, session, events)
        for name in CUA_TOOLS - allowed:
            registry.remove(name)
        context.metadata["cua_session"] = session
        context.metadata["cua_turn_id"] = uuid.uuid4().hex
        return session
    except Exception as exc:
        await session.close()
        for name in CUA_TOOLS:
            registry.remove(name)
        context.metadata["cua_error"] = str(exc)
        return None
    except BaseException:
        await session.close()
        raise
