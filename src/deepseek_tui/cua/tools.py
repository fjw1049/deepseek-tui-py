"""Expose only runtime-supplied public tools through the existing tool registry."""

from __future__ import annotations

import asyncio
import re
from dataclasses import replace
from typing import Any

from deepseek_tui.cua.session import CuaSession
from deepseek_tui.surfaces import CUA_TOOLS  # noqa: F401 - re-exported for CUA wiring
from deepseek_tui.tools.registry import ToolCapability, ToolContext, ToolError, ToolResult, ToolSpec
from deepseek_tui.utils import current_tool, current_turn

MAX_CUA_TEXT_BYTES = 64 * 1024
# Runtime text blocks this large are remembered so a verbatim repeat can be shortened.
REPEATED_TEXT_MIN_BYTES = 4096
MAX_REMEMBERED_TEXTS = 8
# Large web views list only part of their tree; persistent navigation often sits past the cut.
_AX_TRUNCATED = re.compile(r"\(showing \d+-(\d+) of (\d+) items\)")
_COORDINATE_CLICK = re.compile(r"\.click\(\s*\[")
AX_TRUNCATED_NOTE = (
    "[Host note: this accessibility tree is truncated. Elements past the listed range exist "
    "but are not shown, so an unlisted element is not evidence that it is absent, and a '+' "
    "line can be an element that moved into the range. Locate unlisted targets with a screenshot.]"
)
COORDINATE_CLICK_NOTE = (
    "[Host note: a coordinate click does not report what it hit. Before the next action, "
    "confirm the intended target took effect; if not, look for the target's element index in "
    "a fresh accessibility tree before trying coordinates again.]"
)
HANDOFF_NOTICE = (
    "[CUA session reset for desktop handoff. Old JavaScript variables and element references "
    "are invalid. Use cua_observe before rebuilding bindings and acting.]"
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


def cua_surface(meta: Any) -> dict[str, str] | None:
    """What this call last touched, from the runtime's own result metadata (UI only).

    Native apps carry their bundle id; the live preview captures that app's window.
    Browser calls carry no app: an agent tab need not be the window's visible tab, so
    the preview shows the call's own screenshots instead of capturing the window.
    """
    surface = meta.get("codex/toolSurface") if isinstance(meta, dict) else None
    if not isinstance(surface, dict):
        return None
    if surface.get("kind") == "computerUse":
        app = surface.get("app")
        app_id = app.get("appId") if isinstance(app, dict) else None
        return {"kind": "app", "app_id": app_id} if isinstance(app_id, str) and app_id else None
    if surface.get("kind") == "browserUse":
        return {"kind": "browser"}
    return None


def collapse_repeated_texts(messages, new: int, texts: list[str]) -> None:
    """Shorten a large runtime text that the newest CUA results repeat from earlier context.

    Every new connection makes the runtime return its first-call guide again (about 24 KB)
    while the earlier copy is still above. Only a copy present right now is referenced;
    when pruning or compaction later drops it, add_documentation_reminder asks for a fresh
    read. An explicit rewriteDocumentation call always keeps its result whole.
    """
    from deepseek_tui.protocol.messages import ToolResultBlock, ToolUseBlock

    if new <= 0 or not texts:
        return
    calls = {b.id: b for m in messages for b in m.content if isinstance(b, ToolUseBlock)}
    earlier = [b for m in messages[:-new] for b in m.content if isinstance(b, ToolResultBlock)]
    for index in range(len(messages) - new, len(messages)):
        message, blocks, changed = messages[index], [], False
        for block in message.content:
            call = calls.get(getattr(block, "tool_use_id", ""))
            if (isinstance(block, ToolResultBlock) and call is not None
                    and call.name in CUA_TOOLS
                    and "rewriteDocumentation" not in str(call.input.get("code", ""))):
                content = block.content
                for text in texts:
                    source = next((b.tool_use_id for b in earlier if text in b.content), None)
                    if source and text in content:
                        content = content.replace(text, (
                            f"[Same {len(text)}-character runtime text as the result of tool "
                            f"call {source} above; not repeated.]"
                        ))
                if content != block.content:
                    block, changed = block.model_copy(update={"content": content}), True
            blocks.append(block)
        if changed:
            messages[index] = message.model_copy(update={"content": blocks})


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
        delivery = context.metadata.get("task_delivery")
        context.metadata["cua_session"] = self.session
        observing = self.descriptor["name"] == "observe"
        if delivery is not None:
            delivery.cua_used = True
            delivery.cua_observation_evidence.clear()
            if not observing:
                if self.session.last_surface:
                    delivery.cua_verification_target = self.session.last_surface
        try:
            result = await self._execute(input_data, context)
        except BaseException:
            if delivery is not None:
                delivery.cua_failed_evidence = set(delivery.evidence)
            raise
        if not result.success and delivery is not None:
            delivery.cua_failed_evidence = set(delivery.evidence)
        if not result.success and self.descriptor["name"] == "js":
            self.session.invalidate_observation("CUA code failed; inspect its actual effects.")
        if not observing:
            result = replace(result, metadata={**result.metadata, "task_evidence": False})
        return result

    async def _execute(self, input_data: dict[str, Any], context: ToolContext) -> ToolResult:
        from deepseek_tui.mcp.execute import mcp_response_to_tool_result

        turn = context.metadata.get("cua_turn_id") or current_turn()
        call_id = context.metadata.get("cua_call_id") or current_tool()
        payload = await self.session.run(
            lambda: self.session.call(self.descriptor["name"], input_data, turn, call_id),
            self.cancel_events,
        )
        for item in payload.get("content") or []:
            text = item.get("text") if isinstance(item, dict) else None
            if isinstance(text, str) and len(text.encode("utf-8")) >= REPEATED_TEXT_MIN_BYTES:
                texts = self.session.large_texts
                texts[:] = [t for t in texts if t != text][-(MAX_REMEMBERED_TEXTS - 1):] + [text]
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
        metadata = {**result.metadata, "cua_runtime_content": True}
        if self.descriptor["name"] == "observe":
            observation = payload.get("observation")
            metadata["task_evidence"] = result.success and isinstance(observation, dict)
            if isinstance(observation, dict):
                metadata["cua_observation"] = observation
                # Inspecting a different app cannot verify the app we just operated.
                observed_surface = cua_surface(payload.get("_meta"))
                delivery = context.metadata.get("task_delivery")
                required = (delivery.cua_verification_target if delivery
                            else self.session.last_surface)
                metadata["cua_verifies_target"] = required is None or observed_surface == required
        if surface := cua_surface(payload.get("_meta")):
            metadata["cua_surface"] = surface
            if self.descriptor["name"] != "observe" or not (
                self.session.outside_change or self.session.reset_reason
            ):
                self.session.last_surface = surface
            delivery = context.metadata.get("task_delivery")
            if delivery is not None and self.descriptor["name"] == "js":
                delivery.cua_verification_target = surface
        result = replace(result, images=images, metadata=metadata)
        if not result.success and "is not a function" in result.content:
            # JavaScript's own TypeError: the model guessed an API.
            result = replace(result, content=result.content + (
                "\nThat API does not exist. Use only the APIs in the documentation returned by "
                "the first call; await cua.rewriteDocumentation() shows it again."
            ))
        if result.success:
            notes = []
            ranges = _AX_TRUNCATED.findall(result.content)
            if any(int(shown) < int(total) for shown, total in ranges):
                notes.append(AX_TRUNCATED_NOTE)
            if _COORDINATE_CLICK.search(str(input_data.get("code", ""))):
                notes.append(COORDINATE_CLICK_NOTE)
            if notes:
                result = replace(result, content="\n".join([result.content, *notes]))
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


class CuaObserveTool(CuaTool):
    """A bounded observation path, independent of model-written JavaScript."""

    def __init__(self, session: CuaSession, cancel_events=None):
        super().__init__(session, {"name": "observe"}, cancel_events)

    def description(self) -> str:
        return (
            "Observe a native app or an existing browser tab without clicks or text input. "
            "Supply app (name/bundle id), or browser and tab_id from the runtime inventory. "
            "Returns full accessibility state and a screenshot through the same CUA runtime; "
            "existing access permissions apply. Use after actions to verify the expected "
            "change, when the user changes the interface, and before finish_task. "
            "For text-verifiable changes, supply expect with exact visible text fragments "
            "that would show success. A missing fragment means not yet verified, not absent. "
            "Works after a reset; does not restore old JavaScript bindings. "
            "An unknown submission remains unresolved even when inspection succeeds."
        )

    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {
            "app": {"type": "string", "minLength": 1},
            "browser": {"type": "string", "minLength": 1},
            "tab_id": {"type": "string", "minLength": 1},
            "expect": {"type": "array", "maxItems": 8,
                       "items": {"type": "string", "minLength": 1}},
        }, "additionalProperties": False,
            "oneOf": [{"required": ["app"]}, {"required": ["browser", "tab_id"]}]}

    async def execute(self, input_data: dict[str, Any], context: ToolContext) -> ToolResult:
        target = {k: v for k, v in input_data.items() if k != "expect"}
        expected = input_data.get("expect", [])
        if (set(target) not in ({"app"}, {"browser", "tab_id"})
                or any(not isinstance(v, str) or not v.strip() or len(v) > 2048
                       for v in target.values())
                or not isinstance(expected, list) or len(expected) > 8
                or any(not isinstance(v, str) or not v.strip() or len(v) > 2048 for v in expected)):
            raise ToolError("Supply app, or browser and tab_id; no code or other fields.")
        result = await super().execute(input_data, context)
        checks = result.metadata.get("cua_observation", {}).get("expectations", [])
        if checks:
            summary = "\n".join(
                ("Observed: " if check["matched"] else "Not verified: ") + check["text"]
                for check in checks)
            result = replace(result, content=result.content + "\nExpected text checks:\n" + summary)
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
    existing = registry.get("cua_observe") if registry.contains("cua_observe") else None
    if not isinstance(existing, CuaObserveTool) or existing.session is not session:
        registry.register(CuaObserveTool(session, cancel_events))
