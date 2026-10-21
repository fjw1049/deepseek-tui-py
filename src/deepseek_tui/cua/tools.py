"""Expose only runtime-supplied public tools through the existing tool registry."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import Any

from deepseek_tui.cua.session import CuaSession
from deepseek_tui.surfaces import CUA_TOOLS  # noqa: F401 - re-exported for CUA wiring
from deepseek_tui.tools.registry import ToolCapability, ToolContext, ToolError, ToolResult, ToolSpec
from deepseek_tui.utils import current_tool, current_turn

MAX_CUA_TEXT_BYTES = 64 * 1024
HANDOFF_NOTICE = (
    "[CUA session reset for desktop handoff. Old JavaScript variables and element references "
    "are invalid. Start with a documented CUA entry point and observe again before acting.]"
)


_DESKTOP_ACTION_TEXT = {
    "zh": ("需要你在电脑上操作", "我已完成", "完成后继续原任务", "跳过这一步", "不做这一步，让助手另找办法"),
    "en": ("Your help on the computer", "Done", "Continue the task", "Skip this step",
           "Let the assistant find another way"),
}


def desktop_action_question(reason: str, locale: str | None) -> dict[str, Any]:
    header, done, done_hint, skip, skip_hint = _DESKTOP_ACTION_TEXT.get(
        (locale or "zh")[:2], _DESKTOP_ACTION_TEXT["en"]
    )
    return {
        "header": header,
        "id": "desktop_action",
        "question": reason,
        "options": [
            {"label": done, "description": done_hint},
            {"label": skip, "description": skip_hint},
        ],
    }


def desktop_action_result(question: dict[str, Any], response: dict[str, Any]) -> dict[str, Any]:
    done, skip = (option["label"] for option in question["options"])
    choice, text = "dismissed", ""
    answers = response.get("answers") or []
    for answer in answers.values() if isinstance(answers, dict) else answers:
        if isinstance(answer, dict):
            keys = ("label", "value", "selected_option", "answer", "text")
            values = [answer.get(k) for k in keys]
        else:
            values = [answer]
        text = next((v for v in values if isinstance(v, str) and v.strip()), text)
        if done in values:
            choice = "done"
        elif skip in values:
            choice = "skip"
        elif text:
            choice = "information"
    guidance = {
        "done": "The user reports the step is done. That is their statement, not a verified "
                "result: observe the desktop again and confirm before relying on it.",
        "skip": "The user declined this step. Do not ask again without new evidence; find "
                "another authorized route or report what remains blocked.",
        "information": "The user replied with information instead; incorporate it.",
        "dismissed": "The user dismissed the request. Do not repeat it without new evidence.",
    }[choice]
    return {
        "choice": choice,
        "user_text": text if choice == "information" else "",
        "instructions": guidance + " " + HANDOFF_NOTICE,
    }


def add_documentation_reminder(messages) -> None:
    from deepseek_tui.protocol.messages import Message, MessageOrigin

    text = (
        "[CUA context was compacted or tool documentation was pruned. Before further computer "
        "use, call await cua.rewriteDocumentation() and read its complete output. "
        "If the connection was reset, start with a documented entry point instead.]"
    )
    messages[:] = [
        m
        for m in messages
        if not (m.origin == MessageOrigin.SYSTEM_REMINDER and m.text_content() == text)
    ]
    messages.append(Message.user(text, origin=MessageOrigin.SYSTEM_REMINDER))


class CuaTool(ToolSpec):
    def __init__(
        self,
        session: CuaSession,
        descriptor: dict[str, Any],
        cancel_events: list[asyncio.Event] | None = None,
    ):
        self.session = session
        self.descriptor = descriptor
        self.cancel_events = cancel_events or []

    def name(self) -> str:
        return "cua_" + self.descriptor["name"]

    def description(self) -> str:
        return self.descriptor["description"]

    def input_schema(self) -> dict[str, Any]:
        return self.descriptor["inputSchema"]

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.EXECUTES_CODE, ToolCapability.REQUIRES_APPROVAL]

    def supports_parallel(self) -> bool:
        return False

    async def execute(self, input_data: dict[str, Any], context: ToolContext) -> ToolResult:
        from deepseek_tui.mcp.execute import mcp_response_to_tool_result

        turn = context.metadata.get("cua_turn_id") or current_turn()
        call_id = context.metadata.get("cua_call_id") or current_tool()
        if self.session.reset_reason:
            reason, self.session.reset_reason = self.session.reset_reason, ""
            raise ToolError(
                reason + " Start with a documented CUA entry point and re-observe; "
                "do not reuse old variables or replay an uncertain action."
            )
        payload = await self.session.run(
            lambda: self.session.call(self.descriptor["name"], input_data, turn, call_id),
            self.cancel_events,
        )
        result = mcp_response_to_tool_result(self.name(), payload)
        images = [
            image.model_copy(
                update={
                    "source": {
                        **(image.source or {}),
                        "kind": "cua",
                        "tool": self.name(),
                        "session_id": self.session.session_id,
                        "turn_id": turn,
                        "tool_call_id": call_id,
                    }
                }
            )
            for image in result.images
        ]
        result = replace(
            result, images=images, metadata={**result.metadata, "cua_runtime_content": True}
        )
        if len(result.content.encode("utf-8")) > MAX_CUA_TEXT_BYTES:
            from deepseek_tui.tools.runtime import write_spillover

            try:
                path = await asyncio.to_thread(write_spillover, call_id, result.content)
                recovery = (
                    f"Full output saved to {path}. Read it in bounded sections with read_file."
                )
            except OSError:
                recovery = (
                    "The full output could not be saved. Request a smaller read-only observation."
                )
            return replace(
                result,
                success=False,
                content=(
                    "CUA executed, but its text output exceeded the context budget. "
                    "Do not replay the action. No partial API documentation is shown. "
                    + recovery
                    + " If this is API documentation, read all of it before further CUA actions."
                ),
            )
        return result


def register_tools(
    registry: Any, session: CuaSession, cancel_events: list[asyncio.Event] | None = None
) -> None:
    for descriptor in session.descriptors:
        name = "cua_" + descriptor["name"]
        if registry.contains(name):
            existing = registry.get(name)
            if (
                isinstance(existing, CuaTool)
                and existing.session is session
                and existing.descriptor == descriptor
            ):
                continue
        registry.register(CuaTool(session, descriptor, cancel_events))
