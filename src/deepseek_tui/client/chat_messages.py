from __future__ import annotations

import json
from typing import Any

from deepseek_tui.config.provider_registry import normalize_model
from deepseek_tui.protocol.messages import (
    Message,
    Role,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
)


def build_chat_messages(
    messages: list[Message],
    *,
    system_prompt: str | None = None,
    model: str,
    reasoning_effort: str | None = None,
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    if system_prompt and system_prompt.strip():
        output.append({"role": "system", "content": system_prompt})

    include_reasoning = _should_include_reasoning(model, reasoning_effort)
    pending_tool_calls: set[str] = set()

    for message in messages:
        text_parts: list[str] = []
        thinking_parts: list[str] = []
        tool_calls: list[dict[str, Any]] = []
        tool_results: list[dict[str, Any]] = []

        for block in message.content:
            if isinstance(block, TextBlock):
                text_parts.append(block.text)
            elif isinstance(block, ThinkingBlock):
                thinking_parts.append(block.thinking)
            elif isinstance(block, ToolUseBlock):
                tool_calls.append(
                    {
                        "id": block.id,
                        "type": "function",
                        "function": {
                            "name": block.name,
                            "arguments": json.dumps(block.input, ensure_ascii=False),
                        },
                    }
                )
            elif isinstance(block, ToolResultBlock):
                tool_results.append(
                    {
                        "role": "tool",
                        "tool_call_id": block.tool_use_id,
                        "content": block.content,
                    }
                )

        if message.role is Role.USER:
            content = "\n".join(text_parts).strip()
            if content:
                output.append({"role": "user", "content": content})
            pending_tool_calls.clear()
        elif message.role is Role.SYSTEM:
            content = "\n".join(text_parts).strip()
            if content:
                output.append({"role": "system", "content": content})
            pending_tool_calls.clear()
        elif message.role is Role.ASSISTANT:
            assistant = _assistant_message(
                text_parts=text_parts,
                thinking_parts=thinking_parts,
                tool_calls=tool_calls,
                include_reasoning=include_reasoning,
            )
            if assistant is not None:
                output.append(assistant)
                pending_tool_calls = {str(call["id"]) for call in tool_calls}
            else:
                pending_tool_calls.clear()
        elif message.role is Role.TOOL:
            for tool_result in tool_results:
                if not pending_tool_calls or tool_result["tool_call_id"] in pending_tool_calls:
                    output.append(tool_result)
                    pending_tool_calls.discard(tool_result["tool_call_id"])

    return _strip_orphaned_tool_calls(output)


def _assistant_message(
    *,
    text_parts: list[str],
    thinking_parts: list[str],
    tool_calls: list[dict[str, Any]],
    include_reasoning: bool,
) -> dict[str, Any] | None:
    content = "\n".join(text_parts)
    has_text = bool(content.strip())
    has_tool_calls = bool(tool_calls)
    reasoning_content = "\n".join(thinking_parts)
    has_reasoning = include_reasoning and bool(reasoning_content.strip())
    if include_reasoning and not has_reasoning and (has_text or has_tool_calls):
        reasoning_content = "(reasoning omitted)"
        has_reasoning = True

    if not has_text and not has_tool_calls and not has_reasoning:
        return None

    message: dict[str, Any] = {
        "role": "assistant",
        "content": content if has_text else "",
    }
    if has_reasoning:
        message["reasoning_content"] = reasoning_content
    if has_tool_calls:
        message["tool_calls"] = tool_calls
    return message


def _strip_orphaned_tool_calls(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    pending_ids: set[str] = set()
    pending_assistant: dict[str, Any] | None = None
    pending_tool_results: list[dict[str, Any]] = []

    def flush_pending() -> None:
        nonlocal pending_assistant, pending_ids, pending_tool_results
        if pending_assistant is None:
            return
        found_ids = {str(item.get("tool_call_id", "")) for item in pending_tool_results}
        if pending_ids and pending_ids.issubset(found_ids):
            output.append(pending_assistant)
            output.extend(pending_tool_results)
        elif pending_assistant.get("content"):
            downgraded = dict(pending_assistant)
            downgraded.pop("tool_calls", None)
            output.append(downgraded)
        pending_assistant = None
        pending_ids = set()
        pending_tool_results = []

    for message in messages:
        if message.get("role") == "assistant" and message.get("tool_calls"):
            flush_pending()
            pending_assistant = message
            pending_ids = {
                str(call.get("id", ""))
                for call in message.get("tool_calls", [])
                if isinstance(call, dict)
            }
            pending_tool_results = []
        elif message.get("role") == "tool" and pending_assistant is not None:
            pending_tool_results.append(message)
        else:
            flush_pending()
            output.append(message)
    flush_pending()
    return output


def _should_include_reasoning(model: str, reasoning_effort: str | None) -> bool:
    if reasoning_effort == "off":
        return False
    normalized = normalize_model(model).lower()
    return "deepseek" in normalized and ("v4" in normalized or normalized.endswith("reasoner"))
