"""Headless tool-call loop for memory pipeline agents."""

from __future__ import annotations

import inspect
from dataclasses import dataclass, field

from deepseek_tui.client.base import LLMClient
from deepseek_tui.engine.tool_parser import has_tool_call_markers, parse_tool_calls
from deepseek_tui.protocol.messages import Message, ToolUseBlock
from deepseek_tui.protocol.requests import MessageRequest
from deepseek_tui.protocol.responses import (
    StreamTextDelta,
    StreamToolCallComplete,
    ToolCall,
)
from deepseek_tui.tools.base import ToolError
from deepseek_tui.tools.context import ToolContext
from deepseek_tui.tools.registry import ToolRegistry


@dataclass(slots=True)
class MemorySubagentLoopResult:
    final_text: str = ""
    steps: int = 0
    tool_calls: int = 0
    errors: list[str] = field(default_factory=list)
    tool_results: list[tuple[str, dict, str]] = field(default_factory=list)


async def run_memory_subagent_loop(
    client: LLMClient,
    *,
    model: str,
    system_prompt: str,
    user_prompt: str,
    registry: ToolRegistry,
    context: ToolContext,
    max_steps: int = 8,
    max_tokens: int = 4096,
) -> MemorySubagentLoopResult:
    """Run a restricted, headless tool loop for memory background agents.

    This mirrors the useful core of the sub-agent loop without user-visible
    agent lifecycle state. Callers are expected to pass a narrow registry and a
    sandboxed ``ToolContext`` rooted at the memory workspace, e.g. scene_blocks.
    """
    registry.set_context(context)
    api_tools = registry.to_api_tools()
    messages = [Message.user(user_prompt)]
    final_text = ""
    errors: list[str] = []
    tool_results: list[tuple[str, dict, str]] = []
    total_tool_calls = 0

    for step in range(1, max(1, max_steps) + 1):
        chunks: list[str] = []
        tool_calls: list[ToolCall] = []
        request = MessageRequest(
            model=model,
            messages=messages,
            system_prompt=system_prompt,
            tools=api_tools,
            tool_choice={"type": "auto"} if api_tools else None,
            max_tokens=max_tokens,
        )
        stream = client.stream_with_retry(request)
        if not hasattr(stream, "__aiter__"):
            if inspect.isawaitable(stream):
                await stream
            return MemorySubagentLoopResult(
                final_text=final_text,
                steps=step - 1,
                tool_calls=total_tool_calls,
                errors=["client did not return an async event stream"],
                tool_results=tool_results,
            )
        async for event in stream:
            if isinstance(event, StreamTextDelta):
                chunks.append(event.text)
            elif isinstance(event, StreamToolCallComplete):
                tool_calls.append(event.tool_call)

        text = "".join(chunks).strip()
        if not tool_calls and text and has_tool_call_markers(text):
            parsed = parse_tool_calls(text)
            text = parsed.clean_text.strip()
            for call in parsed.tool_calls:
                tool_calls.append(
                    ToolCall(
                        id=call.id,
                        name=call.name,
                        arguments=dict(call.args) if call.args else {},
                    )
                )

        if text:
            final_text = text
            messages.append(Message.assistant(text))
        if not tool_calls:
            return MemorySubagentLoopResult(
                final_text=final_text,
                steps=step,
                tool_calls=total_tool_calls,
                errors=errors,
                tool_results=tool_results,
            )

        total_tool_calls += len(tool_calls)
        messages.append(
            Message.assistant_with_tools(
                [
                    ToolUseBlock(id=tc.id, name=tc.name, input=tc.arguments)
                    for tc in tool_calls
                ]
            )
        )
        for tool_call in tool_calls:
            output, is_error = await _execute_memory_tool(registry, context, tool_call)
            args = (
                dict(tool_call.arguments)
                if isinstance(tool_call.arguments, dict)
                else {}
            )
            tool_results.append((tool_call.name, args, output))
            if is_error:
                errors.append(output)
            messages.append(Message.tool_result(tool_call.id, output, is_error=is_error))

    return MemorySubagentLoopResult(
        final_text=final_text,
        steps=max_steps,
        tool_calls=total_tool_calls,
        errors=errors,
        tool_results=tool_results,
    )


async def _execute_memory_tool(
    registry: ToolRegistry,
    context: ToolContext,
    tool_call: ToolCall,
) -> tuple[str, bool]:
    try:
        result = await registry.execute(tool_call.name, tool_call.arguments, context)
    except ToolError as exc:
        return f"Error: {exc}", True
    except Exception as exc:  # noqa: BLE001
        return f"Error: {type(exc).__name__}: {exc}", True
    if not result.success:
        return f"Error: {result.content}", True
    return result.content, False
