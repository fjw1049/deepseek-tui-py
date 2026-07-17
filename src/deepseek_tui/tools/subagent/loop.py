"""Sub-agent executor loop — drives one sub-agent without nesting a full Engine."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from deepseek_tui.tools.subagent.agent import SubAgent
from deepseek_tui.tools.subagent.completion import AgentRunOutput
from deepseek_tui.tools.subagent.mailbox import MailboxMessage
from deepseek_tui.tools.subagent.types import (
    DEFAULT_MAX_STEPS,
    build_subagent_system_prompt,
)
from deepseek_tui.utils import summarize_text

if TYPE_CHECKING:
    from deepseek_tui.protocol.messages import Message
    from deepseek_tui.tools.subagent.manager import SubAgentRuntime

_LOG = logging.getLogger(__name__)

# Bound mailbox I/O previews so SSE/STATUS items stay light while still
# giving the Workbench step-flow something useful to expand.
_MAILBOX_INPUT_CHARS = 2_000
_MAILBOX_OUTPUT_CHARS = 4_000
# Round narration on the step rail — short enough to read as one knowledge line.
_MAILBOX_NARRATION_CHARS = 240


def _mailbox_input_summary(arguments: Any) -> str | None:
    if arguments is None:
        return None
    try:
        raw = json.dumps(arguments, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        raw = str(arguments)
    text = summarize_text(raw, _MAILBOX_INPUT_CHARS).strip()
    return text or None


def _mailbox_output_summary(output: str | None) -> str | None:
    text = summarize_text(output or "", _MAILBOX_OUTPUT_CHARS).strip()
    return text or None


def _mailbox_round_narration(text: str, thinking: str) -> str | None:
    """One-line step-rail knowledge from the model's own preface / thinking.

    Prefer visible assistant text; fall back to thinking when the model only
    reasoned. Empty → None so the UI stays honest (tool rows only).
    """
    primary = (text or "").strip() or (thinking or "").strip()
    if not primary:
        return None
    # Prefer the first paragraph so a long think dump does not dominate the rail.
    first = primary.split("\n\n", 1)[0].strip()
    clipped = summarize_text(first or primary, _MAILBOX_NARRATION_CHARS).strip()
    return clipped or None


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
        "- Do not write the five-section Markdown report; the JSON tool call "
        "is the only deliverable.\n"
        "- If you need to inspect files or run commands first, do so, then call "
        "structured_output exactly once."
    )


# Keep wording aligned with prompts/subagent_output_format.md (five H3s).
_SUBAGENT_FINAL_REPORT_NUDGE = (
    "You have gathered enough information. Stop exploring and do NOT call any "
    "more tools. Write your final report now as your assistant message, ending "
    "with the mandatory Output contract sections as Markdown H3s: "
    "### SUMMARY, ### EVIDENCE, ### CHANGES, ### RISKS, ### BLOCKERS "
    '(use "None." / "None observed." where the contract allows). '
    "Do not propose follow-up work or ask the parent what to do next."
)

_SUBAGENT_STRUCTURED_OUTPUT_NUDGE = (
    "You have gathered enough information. Stop exploring. Your final action "
    "MUST be a single structured_output tool call whose arguments match the "
    "schema. Do not emit a prose or Markdown final answer."
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
    """Drive one sub-agent to completion without nesting a full Engine.

    True resume: when a durable transcript exists for ``agent.id``, hydrate
    messages and continue from the next LLM round instead of rebuilding from
    the original prompt.
    """
    from deepseek_tui.engine.turn import TurnLoop
    from deepseek_tui.protocol.messages import Message
    from deepseek_tui.protocol.messages import MessageRequest
    from deepseek_tui.tools.durable_transcript import (
        CONTINUE_NUDGE,
        DurableTranscript,
        clear_transcript,
        dicts_to_messages,
        load_transcript,
        messages_to_dicts,
        save_transcript,
        subagent_transcript_path,
    )
    from deepseek_tui.tools.registry import build_subagent_registry
    from deepseek_tui.tools.registry import ToolContext
    from deepseek_tui.tools.validation import (
        STRUCTURED_OUTPUT_TOOL_NAME,
        StructuredOutputTool,
    )

    use_structured_output = bool(agent.output_schema)
    system_prompt = build_subagent_system_prompt(
        agent.agent_type,
        agent.assignment,
        base_override=getattr(agent, "system_prompt", None),
        # One final-delivery contract only: Markdown report XOR JSON tool.
        include_markdown_report_contract=not use_structured_output,
    )
    extra_tools = []
    if use_structured_output:
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
            "subagent_id": agent.id,
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

    transcript_path = subagent_transcript_path(Path(agent.workspace), agent.id)
    existing = load_transcript(transcript_path)

    messages: list[Message] = []
    force_summary = False
    steps = 0
    resuming = bool(
        existing
        and existing.messages
        and existing.round_complete
        and existing.owner_id == agent.id
    )
    if resuming and existing is not None:
        messages.extend(dicts_to_messages(existing.messages))
        force_summary = existing.force_summary
        steps = max(0, int(existing.steps_taken))
    else:
        if agent.fork_messages:
            messages.extend(_messages_from_fork_dicts(agent.fork_messages))
        messages.append(Message.user(agent.prompt))

    # Queued input is real user data — fold it in before any snapshot so a
    # cancel on this round can't silently drop it (queue is drained either way).
    while True:
        try:
            text, _interrupt = agent.input_queue.get_nowait()
        except asyncio.QueueEmpty:
            break
        text = (text or "").strip()
        if text:
            messages.append(Message.user(text))

    turn_loop = TurnLoop(runtime.client)
    final_text = ""
    last_thinking = ""
    structured_value: Any | None = None
    last_usage: object | None = None
    # Only persist completed rounds. Mid-tool cancel keeps the previous snapshot.
    # Snapshot *before* the ephemeral resume nudge appended below — it's purely
    # a live prompt hint (resume regenerates it), never something we want baked
    # into the persisted transcript.
    last_complete_messages: list[Message] = list(messages)
    last_complete_steps = steps
    last_complete_force_summary = force_summary
    has_complete_checkpoint = resuming

    nudge_message = Message.user(CONTINUE_NUDGE) if resuming else None
    if nudge_message is not None:
        messages.append(nudge_message)

    async def _noop_emit(_event: object) -> None:
        return None

    def _persist_messages(msgs: list[Message]) -> list[Message]:
        # Strip the nudge even from a completed-round snapshot: once a round
        # completes it becomes part of `messages` (the model saw and acted on
        # it), so without this a checkpoint saved after resume would bake it
        # in permanently and the *next* resume would stack a fresh one on top.
        if nudge_message is None:
            return msgs
        return [m for m in msgs if m != nudge_message]

    def _save_transcript_safe(transcript: DurableTranscript) -> None:
        # Checkpoint I/O (disk full, permissions) must never mask the actual
        # control-flow signal (e.g. asyncio.CancelledError from a cancel) by
        # raising OSError out of an except-block caller.
        try:
            save_transcript(transcript_path, transcript)
        except OSError:
            _LOG.warning(
                "subagent transcript checkpoint failed agent_id=%s", agent.id,
                exc_info=True,
            )

    def _save_complete_checkpoint(reason: str) -> None:
        nonlocal last_complete_steps, last_complete_force_summary, has_complete_checkpoint
        last_complete_messages[:] = list(messages)
        last_complete_steps = steps
        last_complete_force_summary = force_summary
        has_complete_checkpoint = True
        _save_transcript_safe(
            DurableTranscript(
                owner_kind="subagent",
                owner_id=agent.id,
                messages=messages_to_dicts(_persist_messages(last_complete_messages)),
                steps_taken=last_complete_steps,
                force_summary=last_complete_force_summary,
                round_complete=True,
                checkpoint_reason=reason,
            )
        )

    def _save_cancel_checkpoint() -> None:
        if not has_complete_checkpoint:
            return
        _save_transcript_safe(
            DurableTranscript(
                owner_kind="subagent",
                owner_id=agent.id,
                messages=messages_to_dicts(_persist_messages(last_complete_messages)),
                steps_taken=last_complete_steps,
                force_summary=last_complete_force_summary,
                round_complete=True,
                checkpoint_reason="cancel",
            )
        )

    try:
        while steps < DEFAULT_MAX_STEPS:
            if _subagent_cancelled(cancel, agent):
                _save_cancel_checkpoint()
                raise asyncio.CancelledError

            steps += 1
            agent.steps_taken = steps

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
                _save_cancel_checkpoint()
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

            # Knowledge line for the Workbench step rail (before tools of this
            # round). Prefer model preface; fall back to thinking. Skip when empty.
            narration = _mailbox_round_narration(round_text, round_thinking)
            if narration and runtime.mailbox is not None:
                runtime.mailbox.send(MailboxMessage.progress(agent.id, narration))

            if not result.tool_calls:
                if round_text:
                    break
                if not force_summary and structured_value is None:
                    force_summary = True
                    nudge = (
                        _SUBAGENT_STRUCTURED_OUTPUT_NUDGE
                        if use_structured_output
                        else _SUBAGENT_FINAL_REPORT_NUDGE
                    )
                    messages.append(Message.user(nudge))
                    _save_complete_checkpoint("round")
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
                if _subagent_cancelled(cancel, agent):
                    _save_cancel_checkpoint()
                    raise asyncio.CancelledError
                input_preview = _mailbox_input_summary(tc.arguments)
                if runtime.mailbox is not None:
                    runtime.mailbox.send(
                        MailboxMessage.tool_call_started(
                            agent.id,
                            tc.name,
                            steps,
                            tool_call_id=tc.id,
                            input_summary=input_preview,
                        )
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
                            agent.id,
                            tc.name,
                            steps,
                            ok,
                            tool_call_id=tc.id,
                            input_summary=input_preview,
                            output_summary=_mailbox_output_summary(output),
                        )
                    )
                messages.append(Message.tool_result(tc.id, output, is_error=not ok))
                if structured_value is not None:
                    break
            _save_complete_checkpoint("round")
            if structured_value is not None:
                break
    except asyncio.CancelledError:
        _save_cancel_checkpoint()
        raise

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
    if not final_text and last_thinking:
        final_text = last_thinking
    clear_transcript(transcript_path)
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
