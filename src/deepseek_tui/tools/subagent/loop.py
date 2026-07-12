"""Sub-agent executor loop — drives one sub-agent without nesting a full Engine."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from deepseek_tui.tools.subagent.agent import SubAgent
from deepseek_tui.tools.subagent.completion import AgentRunOutput
from deepseek_tui.tools.subagent.mailbox import MailboxMessage
from deepseek_tui.tools.subagent.types import (
    DEFAULT_MAX_STEPS,
    build_subagent_system_prompt,
)

if TYPE_CHECKING:
    from deepseek_tui.protocol.messages import Message
    from deepseek_tui.tools.subagent.manager import SubAgentRuntime


def _subagent_cancelled(
    cancel: asyncio.Event,
    agent: SubAgent,
) -> bool:
    if cancel.is_set() or agent.cancel_token.is_set():
        return True
    return agent.parent_cancel is not None and agent.parent_cancel.is_set()


def _reject_subagent_interactive_shell(tool_name: str, input_data: dict[str, Any]) -> None:
    if tool_name != "exec_shell":
        return
    # The exec_shell schema exposes the PTY switch as ``pty``; also check
    # the legacy ``interactive`` spelling defensively.
    if input_data.get("pty") is True or input_data.get("interactive") is True:
        raise RuntimeError(
            "Sub-agents cannot use exec_shell with pty=true "
            "(would take over the parent TUI terminal)"
        )


async def _execute_subagent_tool(
    registry: object,
    context: object,
    *,
    tool_name: str,
    tool_input: dict[str, Any],
    auto_approve: bool,
) -> str:
    from deepseek_tui.tools.registry import ApprovalRequirement, ToolError
    from deepseek_tui.tools.registry import ToolRegistry

    assert isinstance(registry, ToolRegistry)
    _reject_subagent_interactive_shell(tool_name, tool_input)
    tool = registry.get(tool_name)
    if not auto_approve and tool.approval_requirement() != ApprovalRequirement.AUTO:
        return (
            f"Error: Tool {tool_name} requires approval and cannot run "
            "inside this sub-agent unless the parent session is auto-approved"
        )
    try:
        result = await registry.execute(tool_name, tool_input, context)  # type: ignore[arg-type]
        if not result.success:
            return f"Error: {result.content}"
        return result.content
    except ToolError as exc:
        return f"Error: {exc}"
    except Exception as exc:  # noqa: BLE001
        return f"Error: {exc}"


def _structured_output_contract() -> str:
    return (
        "Final output contract:\n"
        "- Your final action MUST be a structured_output tool call.\n"
        "- The structured_output arguments are the return value of this subagent.\n"
        "- Do not emit a prose final answer instead of structured_output.\n"
        "- If you need to inspect files or run commands first, do so, then call "
        "structured_output exactly once."
    )


_SUBAGENT_FINAL_REPORT_NUDGE = (
    "You have gathered enough information. Stop exploring and do NOT call any "
    "more tools. Write your final report now as your message: summarize your "
    "findings, conclusions, and any recommendations in full prose."
)


def _assistant_text_and_thinking(message: Any | None) -> tuple[str, str]:
    """Split an assistant message into its visible text and reasoning text.

    Reasoning models (DeepSeek V4/R1) routinely emit their final answer in the
    thinking channel with an empty text block on the terminal round. Harvesting
    only text blocks then completes the sub-agent with an empty result, so the
    caller falls back to reasoning to guarantee a usable deliverable.
    """
    from deepseek_tui.protocol.messages import TextBlock, ThinkingBlock

    if message is None:
        return "", ""
    text_parts: list[str] = []
    think_parts: list[str] = []
    for block in message.content:
        if isinstance(block, TextBlock):
            text_parts.append(block.text)
        elif isinstance(block, ThinkingBlock):
            if block.thinking.strip():
                think_parts.append(block.thinking)
    thinking = "\n".join(think_parts).strip()
    # Drop "(reasoning omitted)" placeholder lines so they never surface as a
    # sub-agent's result (mirrors the renderer's sanitizeReasoningPlaceholders).
    if thinking:
        thinking = "\n".join(
            line
            for line in thinking.splitlines()
            if line.strip().lower() != "(reasoning omitted)"
        ).strip()
    return "".join(text_parts).strip(), thinking


async def run_subagent_loop(
    agent: SubAgent,
    runtime: SubAgentRuntime,
    cancel: asyncio.Event,
) -> AgentRunOutput:
    """Drive one sub-agent to completion without nesting a full Engine."""
    from deepseek_tui.engine.turn import TurnLoop
    from deepseek_tui.protocol.messages import Message
    from deepseek_tui.protocol.messages import MessageRequest
    from deepseek_tui.tools.registry import build_subagent_registry
    from deepseek_tui.tools.registry import ToolContext
    from deepseek_tui.tools.validation import (
        STRUCTURED_OUTPUT_TOOL_NAME,
        StructuredOutputTool,
    )

    system_prompt = build_subagent_system_prompt(
        agent.agent_type,
        agent.assignment,
        base_override=getattr(agent, "system_prompt", None),
    )
    extra_tools = []
    if agent.output_schema:
        extra_tools.append(StructuredOutputTool(agent.output_schema))
        system_prompt = f"{system_prompt}\n\n{_structured_output_contract()}"
    registry = build_subagent_registry(
        runtime.config,
        allowed_tools=agent.allowed_tools,
        client=runtime.client,
        root_model=agent.model,
        extra_tools=extra_tools or None,
    )
    context = ToolContext(
        working_directory=agent.workspace,
        trust_mode=False,
        task_manager=runtime.task_manager,
        subagent_manager=runtime.manager,
        metadata={
            "subagent_depth": agent.spawn_depth,
            "subagent_runtime": runtime,
            "auto_approve": runtime.auto_approve,
        },
    )
    from deepseek_tui.policy.sandbox import sandbox_policy_for_mode

    context.execution_sandbox_policy = sandbox_policy_for_mode(
        "agent",
        agent.workspace,
    )
    registry.set_context(context)
    api_tools = registry.to_api_tools()

    messages: list[Message] = []
    if agent.fork_messages:
        messages.extend(_messages_from_fork_dicts(agent.fork_messages))
    messages.append(Message.user(agent.prompt))

    turn_loop = TurnLoop(runtime.client)
    final_text = ""
    last_thinking = ""
    structured_value: Any | None = None
    steps = 0
    last_usage: object | None = None
    force_summary = False

    async def _noop_emit(_event: object) -> None:
        return None

    for _ in range(DEFAULT_MAX_STEPS):
        if _subagent_cancelled(cancel, agent):
            raise asyncio.CancelledError

        steps += 1
        agent.steps_taken = steps

        # On a forced-summary round we strip tools so the model has no choice
        # but to emit its final report as text.
        round_tools = [] if force_summary else api_tools
        request = MessageRequest(
            model=agent.model,
            messages=messages,
            system_prompt=system_prompt,
            tools=round_tools,
            tool_choice={"type": "auto"} if round_tools else None,
            max_tokens=4096,
            stream=True,
        )
        llm_gate = getattr(runtime.manager, "llm_semaphore", None)
        if llm_gate is not None:
            async with llm_gate:
                result = await turn_loop.run(
                    request,
                    _noop_emit,
                    cancel,
                    tools=round_tools,
                )
        else:
            result = await turn_loop.run(
                request,
                _noop_emit,
                cancel,
                tools=round_tools,
            )

        if result.usage is not None:
            last_usage = result.usage

        if result.cancelled:
            raise asyncio.CancelledError

        if result.assistant_message is not None:
            messages.append(result.assistant_message)

        round_text, round_thinking = _assistant_text_and_thinking(
            result.assistant_message
        )
        if round_text:
            final_text = round_text
        if round_thinking:
            last_thinking = round_thinking

        if not result.tool_calls:
            if round_text:
                # Genuine prose final answer.
                break
            # No text and no tool calls: the model stalled on a reasoning-only
            # round (e.g. "let me also look at ..." with nothing actionable).
            # Nudge it once, tools off, to produce a real report before we fall
            # back to surfacing raw reasoning as the deliverable.
            if not force_summary and structured_value is None:
                force_summary = True
                messages.append(Message.user(_SUBAGENT_FINAL_REPORT_NUDGE))
                continue
            if round_thinking:
                final_text = round_thinking
            break

        from deepseek_tui.protocol.messages import ToolUseBlock

        messages.append(
            Message.assistant_with_tools(
                [
                    ToolUseBlock(id=tc.id, name=tc.name, input=tc.arguments)
                    for tc in result.tool_calls
                ]
            )
        )

        for tc in result.tool_calls:
            if runtime.mailbox is not None:
                runtime.mailbox.send(
                    MailboxMessage.tool_call_started(agent.id, tc.name, steps)
                )
            if tc.name == STRUCTURED_OUTPUT_TOOL_NAME:
                tool_result = await registry.execute(tc.name, tc.arguments, context)
                output = (
                    tool_result.content
                    if tool_result.success
                    else f"Error: {tool_result.content}"
                )
                ok = tool_result.success
                if ok and tool_result.metadata.get("terminate_subagent"):
                    structured_value = tool_result.metadata.get("value")
            else:
                output = await _execute_subagent_tool(
                    registry,
                    context,
                    tool_name=tc.name,
                    tool_input=tc.arguments,
                    auto_approve=runtime.auto_approve,
                )
                ok = not output.startswith("Error:")
            if runtime.mailbox is not None:
                runtime.mailbox.send(
                    MailboxMessage.tool_call_completed(
                        agent.id, tc.name, steps, ok
                    )
                )
            messages.append(Message.tool_result(tc.id, output, is_error=not ok))
            if structured_value is not None:
                break
        if structured_value is not None:
            break

    if runtime.mailbox is not None and last_usage is not None:
        runtime.mailbox.send(
            MailboxMessage.token_usage(
                agent.id,
                agent.model,
                {
                    "input_tokens": getattr(last_usage, "input_tokens", 0),
                    "output_tokens": getattr(last_usage, "output_tokens", 0),
                    "reasoning_tokens": getattr(last_usage, "reasoning_tokens", 0),
                },
            )
        )

    agent.steps_taken = steps
    if agent.output_schema and structured_value is None:
        raise RuntimeError("sub-agent did not return structured_output")
    # Last-resort fallback: a sub-agent that ran out of steps (or whose terminal
    # text was empty) still owes the parent *something* to read back.
    if not final_text and last_thinking:
        final_text = last_thinking
    return AgentRunOutput(text=final_text, structured=structured_value)


def _messages_from_fork_dicts(raw_messages: list[dict[str, Any]]) -> list[Message]:
    from deepseek_tui.protocol.messages import Message

    out: list[Message] = []
    for item in raw_messages:
        try:
            out.append(Message.model_validate(item))
        except Exception:  # noqa: BLE001
            continue
    return out
