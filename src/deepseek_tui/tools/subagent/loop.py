"""Sub-agent executor loop — drives one sub-agent without nesting a full Engine."""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import nullcontext
from collections.abc import Coroutine
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeVar

from deepseek_tui.tools.subagent.agent import SubAgent
from deepseek_tui.tools.subagent.completion import (
    AgentRunOutput,
    has_summary_section,
)
from deepseek_tui.tools.subagent.mailbox import MailboxMessage
from deepseek_tui.tools.subagent.types import (
    DEFAULT_MAX_STEPS,
    build_subagent_system_prompt,
)
from deepseek_tui.utils import summarize_text
from deepseek_tui.engine.ui_progress import UiProgress
from deepseek_tui.surfaces import is_task_call
from deepseek_tui.engine.completion import TurnFacts

if TYPE_CHECKING:
    from deepseek_tui.protocol.messages import Message
    from deepseek_tui.tools.subagent.manager import SubAgentRuntime

_T = TypeVar("_T")


async def _await_input_interrupt(
    work: Coroutine[Any, Any, _T], interrupt: asyncio.Event
) -> _T | None:
    """Interrupt generation/approval waits, never an already-running tool."""
    pending = asyncio.create_task(work)
    interrupted = asyncio.create_task(interrupt.wait())
    try:
        await asyncio.wait((pending, interrupted), return_when=asyncio.FIRST_COMPLETED)
        if interrupt.is_set():
            return None
        return await pending
    finally:
        if not pending.done() and not pending.cancelling():
            pending.cancel()
        interrupted.cancel()
        await asyncio.gather(pending, interrupted, return_exceptions=True)


_LOG = logging.getLogger(__name__)

# Bound mailbox I/O previews so SSE/STATUS items stay light while still
# giving the Workbench step-flow something useful to expand.
_MAILBOX_INPUT_CHARS = 2_000
_MAILBOX_OUTPUT_CHARS = 10_240
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


async def _subagent_auto_approve_enabled(
    auto_approve: bool,
    runtime: "SubAgentRuntime | None",
) -> bool:
    """Prefer the parent handler's live turn flag over a create-time snapshot."""
    handler = getattr(runtime, "approval_handler", None) if runtime else None
    check = getattr(handler, "auto_approve_enabled", None) if handler is not None else None
    if callable(check):
        return bool(await check())
    return bool(auto_approve)


async def _run_subagent_tool(
    registry: object,
    context: object,
    *,
    tool_name: str,
    tool_input: dict[str, Any],
    auto_approve: bool,
    tool_call_id: str = "",
    runtime: SubAgentRuntime | None = None,
    model: str = "",
    interrupt: asyncio.Event | None = None,
    pause_generation: int | None = None,
) -> tuple[bool, str]:
    """Run one tool for a sub-agent; ``ok`` comes from the result, not its text."""
    from deepseek_tui.tools.approval import (
        ApprovalDecision,
        approval_request_for_tool,
        enrich_approval_request,
    )
    from deepseek_tui.tools.registry import ToolContext, ToolError
    from deepseek_tui.tools.registry import ToolRegistry

    assert isinstance(registry, ToolRegistry)
    # Fold retired tool names onto merged successors (same as the parent
    # orchestrator) so sub-agents inherit the deprecation window.
    from deepseek_tui.engine.dispatch import normalize_legacy_tool_call

    tool_name, normalized_input = normalize_legacy_tool_call(tool_name, tool_input)
    tool_input = normalized_input if isinstance(normalized_input, dict) else tool_input
    _reject_subagent_interactive_shell(tool_name, tool_input)
    if getattr(context, "metadata", {}).get("cron_restricted"):
        from deepseek_tui.engine.tool_profiles import cron_tool_allowed

        from deepseek_tui.automation.permissions import browser_authorized

        if not cron_tool_allowed(tool_name, allow_browser=browser_authorized(context)):
            from deepseek_tui.tools.user_input import unattended_tool_denial

            return False, unattended_tool_denial(context, tool_name,
                f"'{tool_name}' is unavailable in unattended automation").content
    if not registry.contains(tool_name):
        # Filtered out by the sub-agent's type allowlist (or hallucinated by
        # the model). Return a clean error rather than letting registry.get()
        # raise an uncaught ToolError out of the loop.
        return False, (
            f"Error: Tool '{tool_name}' is not available to this sub-agent "
            "type and was blocked."
        )
    tool = registry.get(tool_name)
    if isinstance(context, ToolContext) and context.metadata.get("cron_restricted"):
        from deepseek_tui.tools.user_input import unattended_tool_denial

        for path, writing in tool.path_accesses(tool_input):
            access = context.check_path(path, write=writing, allow_read_roots=not writing)
            if not access.allowed or (writing and not context._within(
                    access.path, context.working_directory.resolve())):
                return False, unattended_tool_denial(context, tool_name,
                    f"Path requires interactive authorization: {path}").content
    policy = getattr(getattr(runtime, "config", None), "approval_policy", None)
    if policy is None and hasattr(context, "metadata"):
        policy = (context.metadata or {}).get("approval_policy")  # type: ignore[union-attr]
    # Live parent-session flag (YOLO / turn auto_approve), not Engine.create snapshot.
    effective_auto = await _subagent_auto_approve_enabled(auto_approve, runtime)
    from deepseek_tui.tools.approval import (
        NEVER_BLOCKED_PREFIX,
        path_access_prompt,
        removal_prompt,
    )

    args_or_none = tool_input if isinstance(tool_input, dict) else None
    removal = (
        removal_prompt(tool, args_or_none, context, policy)
        if isinstance(context, ToolContext)
        else None
    )
    # Same path rule as the parent gate; grants are shared with the parent.
    path_prompt = (
        path_access_prompt(tool, args_or_none, context, policy)
        if isinstance(context, ToolContext)
        else None
    )
    required = (
        removal.request if removal is not None
        else path_prompt.request if path_prompt is not None
        else approval_request_for_tool(tool, policy, args_or_none)
    )
    from deepseek_tui.automation.permissions import browser_authorized

    if tool_name == "browser_use" and context.metadata.get("cron_restricted") and browser_authorized(context):
        required = None
    if required is not None and required.force_prompt and getattr(context, "metadata", {}).get("cron_restricted"):
        from deepseek_tui.tools.user_input import unattended_tool_denial

        return False, unattended_tool_denial(context, tool_name, required.reason or "Interactive approval required").content
    if required is not None and (required.reason or "").startswith(NEVER_BLOCKED_PREFIX):
        return False, f"Error: {path_prompt.denial_message() if path_prompt else required.reason}"
    from deepseek_tui.integrations.hooks import HookContext, aggregate_hook_decision

    hook_executor = getattr(runtime, "hook_executor", None)
    hook_ctx = HookContext(tool_name=tool_name, tool_args=json.dumps(tool_input),
                           workspace=getattr(context, "working_directory", None))
    hook_results = await hook_executor.execute("tool_call_before", hook_ctx) if hook_executor else []
    hook_decision = aggregate_hook_decision(hook_results)
    if hook_decision.blocked:
        return False, f"Error: Tool call blocked by hook: {hook_decision.reason}"
    path_approved = False
    forced = required is not None and required.force_prompt
    approval_request = None if effective_auto and not forced else required
    if hook_decision.ask:
        from deepseek_tui.tools.approval import build_approval_request

        approval_request = build_approval_request(tool_name, [], reason="Hook requested confirmation")
    if approval_request is not None:
        handler = getattr(runtime, "approval_handler", None) if runtime else None
        if handler is None:
            return False, (
                f"Error: Tool {tool_name} requires approval and cannot run "
                "inside this sub-agent without a parent approval bridge"
            )
        args = tool_input if isinstance(tool_input, dict) else {}
        enrich_approval_request(
            approval_request,
            tool_name,
            args,
            tool_description=approval_request.reason,
            working_directory=getattr(context, "working_directory", None),
        )
        call_id = tool_call_id or f"subagent-{tool_name}"
        # Mirror Engine tooling: auto-approve short-circuits inside
        # request_approval without registering on ApprovalBridge. Emitting
        # ApprovalRequiredEvent in that case races the UI (ghost card / 404).
        still_needs_prompt = True
        check = getattr(handler, "auto_approve_enabled", None)
        if callable(check) and not approval_request.force_prompt:
            still_needs_prompt = not bool(await check())
        emit = getattr(runtime, "emit_event", None) if runtime else None
        from deepseek_tui.engine.handle import ApprovalHandler

        scope = (
            handler.approval_scope(call_id, approval_request)
            if still_needs_prompt and isinstance(handler, ApprovalHandler)
            else nullcontext()
        )
        with scope:
            if still_needs_prompt and emit is not None:
                from deepseek_tui.engine.events import ApprovalRequiredEvent

                maybe = emit(
                    ApprovalRequiredEvent(tool_call_id=call_id, request=approval_request)
                )
                if asyncio.iscoroutine(maybe):
                    await maybe
            decision = (
                await _await_input_interrupt(
                    handler.request_approval(call_id, approval_request), interrupt
                )
                if interrupt is not None
                else await handler.request_approval(call_id, approval_request)
            )
            if decision is None:
                return False, "Error: Not executed: approval interrupted by new user input."
        if decision not in (
            ApprovalDecision.APPROVED,
            ApprovalDecision.APPROVED_SESSION,
        ):
            if removal is not None and approval_request is removal.request:
                return False, f"Error: {removal.denial}"
            if path_prompt is not None and approval_request is path_prompt.request:
                return False, f"Error: {path_prompt.denial_message()}"
            return False, f"Error: Tool {tool_name} denied by approval policy"
        if removal is not None and context.metadata.get("turn_facts") is not None:
            context.metadata["turn_facts"].approved_removals.update(removal.paths)
        if path_prompt is not None and approval_request is path_prompt.request:
            approval_request.remembered = decision is ApprovalDecision.APPROVED_SESSION
            path_approved = True
    pause = getattr(getattr(runtime, "manager", None), "parent_pause", None)
    if pause is not None and (pause.paused or (
        pause_generation is not None and pause.generation != pause_generation
    )):
        return False, "Error: Not executed: human intervention invalidated this operation."
    execution_context = (
        path_prompt.grant(context)  # type: ignore[union-attr]
        if path_approved and path_prompt is not None
        else context
    )
    progress = context.metadata.get("ui_progress")
    if progress is not None and is_task_call(tool_name, tool_input) and (
            blocked := progress.blocked_content(tool_name)):
        return False, f"Error: {blocked}"
    if tool_name in {"cua_act", "cua_js", "cua_js_reset", "cua_observe"}:
        context.metadata["cua_call_id"] = tool_call_id
    try:
        session = context.metadata.get("cua_session")
        handed_off = tool_name == "agent" and session is not None and await session.handoff()
        with pause.tool_execution() if pause is not None else nullcontext():
            result = await registry.execute(tool_name, tool_input, execution_context)  # type: ignore[arg-type]
        if handed_off:
            from dataclasses import replace
            from deepseek_tui.cua.tools import HANDOFF_NOTICE

            result = replace(result, content=result.content + "\n\n" + HANDOFF_NOTICE)
            context.metadata["ui_progress"].reset()
        if hook_executor:
            from dataclasses import replace

            hook_ctx.tool_result = result.content
            hook_ctx.tool_success = result.success
            hook_ctx.tool_exit_code = result.metadata.get("returncode")
            post = aggregate_hook_decision(await hook_executor.execute("tool_call_after", hook_ctx))
            feedback = hook_decision.additional_context + post.additional_context
            if post.blocked and post.reason:
                feedback.append(post.reason)
            if feedback:
                result = replace(result, content=result.content + "\n[hook feedback]\n" + "\n".join(feedback))
        from dataclasses import replace

        progress = context.metadata.get("ui_progress")
        if progress is not None and tool_name == "request_user_input" and result.success:
            progress.reset()
        note = await asyncio.to_thread(progress.record_result, tool_name, result) if (
            progress is not None and is_task_call(tool_name, tool_input)
        ) else ""
        result = replace(result, content=result.content + note)
        context.metadata.setdefault("tool_result_metadata", {})[tool_call_id] = result.metadata
        context.metadata.setdefault("tool_result_content", {})[tool_call_id] = result.content
        if result.images:
            context.metadata.setdefault("tool_images", {})[tool_call_id] = result.images
            for image in result.images:
                context.metadata.setdefault("image_assets", {})[image.asset_id] = image.model_dump()
        if not result.success:
            return False, f"Error: {result.content}"
        # Same ingress compaction the parent orchestrator applies before a
        # tool result enters the transcript. Sub-agents used to append
        # result.content raw, so one oversized result (observed: a 7 714-path
        # file_search ≈ 320k tokens) permanently ballooned the child's
        # context and degraded every following round.
        from deepseek_tui.engine.context import compact_tool_result_for_context

        return True, compact_tool_result_for_context(
            model, tool_name, result, model_config=getattr(runtime, "config", None)
        )
    except ToolError as exc:
        return False, f"Error: {exc}"
    except Exception as exc:  # noqa: BLE001
        return False, f"Error: {exc}"


async def _execute_subagent_tool(*args: Any, **kwargs: Any) -> str:
    """Text-only view of :func:`_run_subagent_tool` (failures read ``Error: ...``)."""
    _ok, text = await _run_subagent_tool(*args, **kwargs)
    return text


def _structured_output_contract() -> str:
    return (
        "Final output contract:\n"
        "- Your final action MUST be a structured_output tool call.\n"
        "- The structured_output arguments are the return value of this subagent.\n"
        "- Do not emit a prose final answer instead of structured_output.\n"
        "- Do not write the Markdown report; the JSON tool call "
        "is the only deliverable.\n"
        "- If you need to inspect files or run commands first, do so, then call "
        "structured_output exactly once."
    )


# Keep wording aligned with prompts/sub_output.md (### SUMMARY is the only
# required heading; the rest of the report shape is the child's choice).
_SUBAGENT_FINAL_REPORT_NUDGE = (
    "You have gathered enough information. Stop exploring and do NOT call any "
    "more tools. Write your final report now as your assistant message. It "
    "must contain a `### SUMMARY` H3 stating the outcome in prose; below it, "
    "organise the rest as the task calls for, carrying the evidence, writes, "
    "risks and unfinished work that apply to your run. Do not add a heading "
    'just to write "None." under it. Do not propose follow-up work or ask the '
    "parent what to do next."
)

_SUBAGENT_STRUCTURED_OUTPUT_NUDGE = (
    "You have gathered enough information. Stop exploring. Your final action "
    "MUST be a single structured_output tool call whose arguments match the "
    "schema. Do not emit a prose or Markdown final answer."
)


# The report is there; only the heading the harness parses is missing. Saying
# "too brief" here sent children off to redo work they had already finished.
_SUBAGENT_MISSING_HEADING_NUDGE = (
    "Your report is usable but is missing the required `### SUMMARY` heading. "
    "Send the same report again with `### SUMMARY` at the top: one paragraph "
    "stating the outcome, then the rest as you wrote it. Do not call tools or "
    "redo the work."
)
# Visible text at least this long reads as a report rather than a next-step
# note ("I'll read X next"); CJK is denser than ASCII.
_REPORT_MIN_CHARS = 200
_REPORT_MIN_CHARS_CJK = 80


def _looks_like_report(text: str) -> bool:
    from deepseek_tui.tools.subagent.completion import _CJK_RE

    bound = _REPORT_MIN_CHARS_CJK if _CJK_RE.search(text) else _REPORT_MIN_CHARS
    return len(text.strip()) >= bound


_SUBAGENT_SUMMARY_CONTINUATION_NUDGE = (
    "Your previous response was too brief. The parent cannot see your "
    "context — the next assistant message is the entire handoff. Provide a "
    "more complete report: specific technical details, findings, and "
    "everything the parent must know. If the assignment is still unfinished, "
    "use tools to finish it, then write the report."
)


# A round that came back FAILED, or whose response was cut off at the output
# cap, is re-run on this budget before the whole run fails. The transport layer
# has already spent its own retries by the time either reaches us, so this is
# deliberately small: enough to ride out one bad upstream response, not enough
# to turn a deterministic failure into a retry storm.
MAX_SUBAGENT_ROUND_FAILURES = 2
# Consecutive stalled rounds (no text, no tool call — the model spent the round
# thinking) tolerated with the tool catalog still in hand. Past this the forced
# summary takes over, because a child that will not act still owes the parent a
# report.
MAX_SUBAGENT_EMPTY_ROUNDS = 2
# Consecutive failing tool calls before the loop says so. Tool errors arrive as
# ordinary tool results, so nothing in the transcript tells the model that this
# is the fifth identical failure rather than the first; without a marker a child
# can spend its whole step budget re-issuing one broken call.
MAX_CONSECUTIVE_TOOL_FAILURES = 5
# Long runs keep taking "one last check" after announcing the report. Every this
# many rounds the child hears how much budget it has spent. The reminder is soft
# — tools stay — and DEFAULT_MAX_STEPS remains the only hard bound.
SUBAGENT_ROUND_NUDGE_INTERVAL = 40

_SUBAGENT_STALLED_ROUND_NUDGE = (
    "That round produced no tool call and no report, so it reads as a stall "
    "rather than as finished work. A next-step note (\"I'll read X next\") "
    "is a stall too — say it with a tool call, or write the report. Nothing "
    "has been decided for you: you still have your tools. If the assignment "
    "is unfinished, take the next concrete action now. If it is genuinely "
    "finished, write the report."
)

_SUBAGENT_TOOL_FAILURE_NUDGE = (
    "Your last {n} tool calls in a row all came back as errors, so repeating the "
    "same approach will not get you further. Read what the errors actually say, "
    "then change something concrete: a different path, a different tool, or a "
    "smaller step you can verify. If the assignment cannot be done this way, say "
    "so in your report rather than retrying."
)

_SUBAGENT_ROUND_BUDGET_NUDGE = (
    "You have used {used} of {budget} rounds. If the assignment is answered, "
    "stop exploring and {deliver} now. Keep going only for a specific gap the "
    "result cannot do without — name it and close just that."
)

_SUBAGENT_TRUNCATED_NUDGE = (
    "Your previous response was cut off at the output cap before it reached an "
    "end, so it has been discarded. Do not continue from where it stopped — "
    "redo the round and make it fit: quote fewer lines, tighten the prose, and "
    "put the outcome first."
)


async def _compact_subagent_messages(messages: list[Message]) -> list[Message]:
    """Overflow relief for a child, handed to ``TurnLoop`` as ``compact_fn``.

    The parent passes an LLM-backed compaction. A child that is already over
    budget cannot afford another round-trip, and its context is dominated by
    tool output rather than dialogue, so dropping old tool bodies is both
    cheaper and better targeted. When there is nothing left to prune the
    request overflows again and the loop fails the run loudly.
    """
    from deepseek_tui.engine.capacity import clear_old_tool_results

    return clear_old_tool_results(messages)



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
    from deepseek_tui.engine import reminders
    from deepseek_tui.engine.completion_requirement import CompletionRequirement
    from deepseek_tui.engine.turn import TurnLoop, TurnOutcomeStatus
    from deepseek_tui.protocol.messages import Message, MessageOrigin
    from deepseek_tui.protocol.messages import MessageRequest
    from deepseek_tui.tools.durable_transcript import (
        CONTINUE_NUDGE,
        DurableTranscript,
        dicts_to_messages,
        load_transcript,
        messages_to_dicts,
        save_transcript,
        subagent_transcript_path,
    )
    from deepseek_tui.tools.registry import build_subagent_registry
    from deepseek_tui.tools.registry import ToolContext
    from deepseek_tui.tools.subagent.structured_output import (
        STRUCTURED_OUTPUT_TOOL_NAME,
        StructuredOutputTool,
    )

    from deepseek_tui.tools.run_conversation import RunConversation

    history = RunConversation("subagent", agent.id, agent.prompt, Path(agent.workspace))
    agent.conversation = history

    use_structured_output = agent.output_schema is not None
    # Session locale (config.ui.locale) — same source and validation as the
    # parent engine's reply_locale. Children have no ## Environment block, so
    # the language directive in the system prompt is their only signal.
    _locale = getattr(getattr(runtime.config, "ui", None), "locale", None)
    system_prompt = build_subagent_system_prompt(
        agent.agent_type,
        agent.assignment,
        base_override=getattr(agent, "system_prompt", None),
        # One final-delivery contract only: Markdown report XOR JSON tool.
        include_markdown_report_contract=not use_structured_output,
        locale_tag=_locale if _locale in ("zh", "en") else "zh",
    )
    extra_tools = []
    if use_structured_output:
        extra_tools.append(StructuredOutputTool(agent.output_schema))
        system_prompt = f"{system_prompt}\n\n{_structured_output_contract()}"
    # Type-level allowlist caps any explicit per-call subset. Applied here
    # (not in the spawn tool) so direct ``manager.spawn`` callers get the same
    # filtering as LLM-driven ``agent`` spawn calls. None means full registry.
    effective_tools = agent.allowed_tools
    default_set = agent.agent_type.allowed_tools()
    if default_set is not None:
        effective_tools = sorted(
            default_set if effective_tools is None else default_set.intersection(effective_tools)
        )
    effective_model = agent.model.split("::", 1)[-1]
    registry = build_subagent_registry(
        runtime.config,
        allowed_tools=effective_tools,
        client=runtime.client,
        root_model=effective_model,
        extra_tools=extra_tools or None,
    )
    approval_policy = getattr(runtime.config, "approval_policy", None)
    # Trust is explicit configuration only. ``auto_approve`` must NOT imply
    # it: an auto-approved (fire-and-forget) child would otherwise bypass
    # workspace path confinement and get a danger-full-access sandbox.
    trust_mode = bool(getattr(runtime, "trust_mode", False)) and not runtime.cron_restricted
    parent_task_id = getattr(runtime, "active_task_id", None)
    if isinstance(parent_task_id, str):
        parent_task_id = parent_task_id.strip() or None
    else:
        parent_task_id = None
    metadata: dict[str, Any] = {
        "subagent_id": agent.id,
        "subagent_depth": agent.spawn_depth,
        "subagent_runtime": runtime,
        "task_config": runtime.config,
        "task_model": effective_model,
        "auto_approve": runtime.auto_approve,
        "approval_policy": approval_policy,
        "cron_restricted": runtime.cron_restricted,
        "unattended": runtime.cron_restricted,
    }
    if parent_task_id is not None:
        metadata["task_id"] = parent_task_id
    # Look up the parent sink at call time so a late ThreadManager bind still
    # reaches mutations started before the monitor attached the callback.
    def _parent_mutation_sink(mut: dict[str, object]) -> None:
        sink = getattr(runtime.manager, "on_file_mutation", None)
        if callable(sink):
            sink(mut)

    context = ToolContext(
        working_directory=agent.workspace,
        trust_mode=trust_mode,
        task_manager=runtime.task_manager,
        subagent_manager=runtime.manager,
        active_task_id=parent_task_id,
        metadata=metadata,
        on_file_mutation=_parent_mutation_sink,
        pre_write_capture=getattr(runtime.manager, "pre_write_capture", None),
        mutation_agent_id=agent.id,
        policy=getattr(runtime, "policy", None),
        network_policy=getattr(runtime, "network_policy", None),
    )
    automation_browser = getattr(runtime.manager, "automation_browser", None)
    if automation_browser is not None:
        automation_browser.bind(context)
    if getattr(runtime, "path_grants", None) is not None:
        context.path_grants = runtime.path_grants
    task_checkpoints = getattr(runtime.manager, "task_file_checkpoints", None)
    if task_checkpoints is not None:
        task_checkpoints.bind(context)
    context.metadata["hook_executor"] = runtime.hook_executor
    from deepseek_tui.policy.sandbox import resolve_execution_sandbox_policy

    context.execution_sandbox_policy = resolve_execution_sandbox_policy(
        "agent",
        agent.workspace,
        trust_mode=context.trust_mode,
        sandbox_mode="workspace-write" if runtime.cron_restricted else getattr(runtime.config, "sandbox_mode", None),
        approval_policy=approval_policy if isinstance(approval_policy, str) else None,
    )
    facts = TurnFacts()
    context.metadata["turn_facts"] = facts
    context.metadata["ui_progress"] = UiProgress()
    context.metadata["session_started_at"] = agent.started_at_ms / 1000
    registry.set_context(context)
    api_tools = registry.to_api_tools()
    if runtime.cron_restricted:
        from deepseek_tui.engine.tool_profiles import filter_tools_for_profile

        from deepseek_tui.automation.permissions import browser_authorized

        api_tools = filter_tools_for_profile(api_tools, "cron", allow_browser=browser_authorized(context))

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
        force_summary = False  # A new attempt may use tools again.
        steps = max(0, int(existing.steps_taken))
    else:
        if agent.fork_messages:
            messages.extend(dicts_to_messages(agent.fork_messages))
        from deepseek_tui.engine.turn import prepare_turn_for_model

        prepared = prepare_turn_for_model(agent.prompt, workspace=agent.workspace)
        messages.append(
            Message.user(
                prepared.model_text, origin=MessageOrigin.REAL_USER, images=prepared.images
            )
        )

    from deepseek_tui.media import message_images

    context.metadata["image_assets"] = {
        img.asset_id: img.model_dump()
        for msg in messages
        for img in [*msg.image_references, *message_images(msg)]
    }

    turn_loop = TurnLoop(
        runtime.client, compact_fn=_compact_subagent_messages, model_config=runtime.config
    )
    final_text = ""
    last_thinking = ""
    structured_value: Any | None = None
    usage_totals = {"input_tokens": 0, "output_tokens": 0, "reasoning_tokens": 0}
    saw_usage = False
    structured_received = False
    attempt_start_steps = steps
    agent.max_steps_reached = False
    # Set when the budget, not the child, decided this was the last round.
    budget_forced = False
    # Consecutive bad rounds. Any round that makes progress clears them, so the
    # budgets bound a run of failures rather than a whole run's worth.
    round_failures = 0
    empty_rounds = 0
    tool_failures = 0
    # Only persist completed rounds. Mid-tool cancel keeps the previous snapshot.
    # Snapshot *before* the ephemeral resume nudge appended below — it's purely
    # a live prompt hint (resume regenerates it), never something we want baked
    # into the persisted transcript.
    last_complete_messages: list[Message] = list(messages)
    last_complete_steps = steps
    last_complete_force_summary = force_summary
    has_complete_checkpoint = resuming

    nudge_message = (
        reminders.reminder_message(reminders.SUBAGENT_OUTPUT_NUDGE, CONTINUE_NUDGE)
        if resuming
        else None
    )
    if nudge_message is not None:
        messages.append(nudge_message)

    # Forward the child's text deltas to the parent engine so the GUI can
    # stream sub-agent output live. Other events (thinking, tool calls)
    # stay swallowed — the mailbox already narrates those. ``handle.emit``
    # has no hook-bridge arm for SubAgentTextDeltaEvent, so the per-delta
    # await is just a queue put.
    _delta_emit = getattr(runtime, "emit_event", None) if runtime else None

    async def _round_emit(event: object) -> None:
        from deepseek_tui.engine.events import (
            SubAgentTextDeltaEvent, TextDeltaEvent, ThinkingDeltaEvent,
        )

        if isinstance(event, ThinkingDeltaEvent):
            history.thinking(event.thinking)
        if isinstance(event, TextDeltaEvent) and event.text:
            history.delta(event.text)
            if _delta_emit is None:
                return None
            maybe = _delta_emit(
                SubAgentTextDeltaEvent(agent_id=agent.id, text=event.text)
            )
            if asyncio.iscoroutine(maybe):
                await maybe
        return None

    # Missing ### SUMMARY: two continuations on the same memory, then accept.
    # The predicate stays has_summary_section — length alone cannot split
    # CJK stubs from real reports.
    summary_requirement = CompletionRequirement(
        name="subagent_summary",
        reminder=_SUBAGENT_SUMMARY_CONTINUATION_NUDGE,
        max_retries=2,
    )
    summary_recoveries = 0
    # A report without its heading is asked to add it once, then accepted.
    heading_requested = False

    def _try_summary_recovery() -> bool:
        nonlocal summary_recoveries, force_summary
        if use_structured_output:
            return False
        if not summary_requirement.should_recover(
            satisfied=has_summary_section(final_text),
            fired=summary_recoveries,
            abort=_subagent_cancelled(cancel, agent),
        ):
            return False
        summary_recoveries += 1
        force_summary = False
        messages.append(
            reminders.reminder_message(
                reminders.SUBAGENT_OUTPUT_NUDGE, summary_requirement.reminder
            )
        )
        return True

    # Children whose outcome this agent already saw through its own tools.
    reported_children: set[str] = set()

    async def _deliver_children() -> bool:
        """Hand this agent its children's results before it may stop.

        Only the main engine gets completion callbacks, so without this a
        child that spawned without waiting would end with its own children
        still running and their reports unread. Children still running after
        the handoff budget are stopped: nothing would read them later.
        """
        manager = runtime.manager
        child_ids = getattr(manager, "child_ids", None)
        if not callable(child_ids):
            return False
        pending = [cid for cid in child_ids(agent.id) if cid not in reported_children]
        if not pending:
            return False
        running = child_ids(agent.id, running_only=True)
        if running:
            await manager.wait(
                running, mode="all", timeout_ms=int(manager.handoff_timeout_secs * 1000)
            )
            await manager.cancel_children(agent.id)
        from deepseek_tui.tools.subagent.completion import build_completion_payload
        from deepseek_tui.tools.subagent.handoff_ledger import build_handoff_ledger

        snaps = [await manager.get_result(cid) for cid in pending]
        ledger = build_handoff_ledger(snaps)
        if ledger:
            messages.append(reminders.reminder_message(reminders.SUBAGENT_HANDOFF, ledger))
        for snap in snaps:
            reported_children.add(snap.agent_id)
            messages.append(
                reminders.reminder_message(
                    reminders.SUBAGENT_DONE, build_completion_payload(snap)
                )
            )
        return True

    # True once a subagent_stop hook has blocked completion (delivered to
    # hooks as ``stop_hook_active`` so they can avoid blocking forever).
    stop_hook_active = False

    async def _subagent_stop_allowed() -> bool:
        """Run ``subagent_stop`` (Claude "SubagentStop") hooks.

        Returns False when a hook blocks the stop; the block reason is
        appended to the transcript so the sub-agent keeps working on it.
        DEFAULT_MAX_STEPS remains the hard upper bound.
        """
        nonlocal stop_hook_active
        executor = getattr(runtime, "hook_executor", None)
        if executor is None or not executor.has_hooks_for_event("subagent_stop"):
            return True
        from deepseek_tui.integrations.hooks import (
            HookContext,
            aggregate_hook_decision,
        )

        ctx = HookContext(
            session_id=agent.id,
            workspace=Path(agent.workspace),
            model=effective_model,
            stop_hook_active=stop_hook_active,
        )
        try:
            results = await executor.execute("subagent_stop", ctx)
        except Exception:  # noqa: BLE001 — hooks must never kill the agent
            _LOG.warning("subagent_stop hooks failed", exc_info=True)
            return True
        decision = aggregate_hook_decision(results)
        if not decision.blocked:
            return True
        stop_hook_active = True
        reason = (
            decision.reason
            or "A SubagentStop hook blocked ending this sub-agent."
        )
        messages.append(
            reminders.reminder_message(
                reminders.SUBAGENT_STOP_HOOK_BLOCK,
                f"A SubagentStop hook prevented finishing: {reason}",
            )
        )
        return False

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

    cua_session = None
    try:
        from deepseek_tui.cua.subagent import prepare_subagent_cua

        cua_session = await prepare_subagent_cua(
            agent, runtime, context, registry, effective_tools, cancel,
        )
        if cua_session is not None:
            from deepseek_tui.engine.prompts import render_action_surfaces
            from deepseek_tui.surfaces import cua_surfaces

            api_tools = registry.to_api_tools()
            system_prompt += (
                "\n\n" + render_action_surfaces(cua_surfaces(runtime.config.cua))
                + "\n\n" + cua_session.instructions
            )
        elif context.metadata.get("cua_error"):
            system_prompt += "\n\nComputer use unavailable: " + context.metadata["cua_error"]
        if not any(t["function"]["name"] == "browser_use" for t in api_tools):
            system_prompt += (
                "\n\nThis child has no Workbench browser. If a step needs its UI, "
                "return that step to the parent with the target and remaining work. "
                "Do not substitute Chrome CUA merely because browser_use is absent. "
                "Chrome CUA is appropriate when the parent reports an observed browser_use "
                "technical failure or missing capability, or when the assignment requests "
                "Chrome or needs its existing session. Preserve authorization and resolve "
                "uncertain writes before switching. Public information lookup may use "
                "available search/fetch tools."
            )
        pause_generation_seen = 0
        while steps - attempt_start_steps < DEFAULT_MAX_STEPS:
            pause = getattr(runtime.manager, "parent_pause", None)
            if pause is not None:
                await pause.wait(agent.parent_cancel or cancel)
                if pause.generation != pause_generation_seen:
                    messages.append(reminders.reminder_message(
                        reminders.HUMAN_RESUME,
                        "Human intervention ended. Recheck relevant current state before "
                        "continuing the original assignment; old pending actions are invalid.",
                    ))
                    pause_generation_seen = pause.generation
                    context.metadata["ui_progress"].reset()
            pause_generation = pause.generation if pause is not None else None
            if _subagent_cancelled(cancel, agent):
                _save_cancel_checkpoint()
                raise asyncio.CancelledError

            # Consume between rounds and checkpoint before starting cancellable work.
            received_input = False
            while True:
                try:
                    text, _interrupt = agent.input_queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                text = (text or "").strip()
                if text:
                    context.metadata["ui_progress"].reset()
                    history.user(text)
                    from deepseek_tui.engine.turn import prepare_turn_for_model

                    prepared = prepare_turn_for_model(text, workspace=agent.workspace)
                    messages.append(
                        Message.user(
                            prepared.model_text,
                            origin=MessageOrigin.REAL_USER,
                            images=prepared.images,
                        )
                    )
                    for image in prepared.images:
                        context.metadata.setdefault("image_assets", {})[image.asset_id] = (
                            image.model_dump()
                        )
                    received_input = True
            agent.interrupt_event.clear()
            if received_input:
                _save_complete_checkpoint("input")

            history.settle()
            steps += 1
            agent.steps_taken = steps
            if (
                steps - attempt_start_steps == DEFAULT_MAX_STEPS
                and not force_summary
                and not structured_received
            ):
                # Last round of the budget: take the tools away so the child
                # writes its report instead of being cut off mid-exploration.
                force_summary = budget_forced = True
                messages.append(
                    reminders.reminder_message(
                        reminders.SUBAGENT_OUTPUT_NUDGE,
                        _SUBAGENT_STRUCTURED_OUTPUT_NUDGE
                        if use_structured_output
                        else _SUBAGENT_FINAL_REPORT_NUDGE,
                    )
                )

            round_tools = api_tools
            if force_summary:
                round_tools = [
                    tool for tool in api_tools
                    if (tool.get("function") or tool).get("name") == STRUCTURED_OUTPUT_TOOL_NAME
                ] if use_structured_output else []
            request = MessageRequest(
                model=effective_model,
                messages=messages,
                system_prompt=system_prompt,
                tools=round_tools,
                tool_choice={"type": "auto"} if round_tools else None,
                max_tokens=agent.agent_type.max_tokens(),
                temperature=runtime.config.effective_provider_config().temperature,
                reasoning_effort=runtime.config.reasoning_effort,
                extra_body=dict(runtime.config.effective_provider_config().extra_body),
                stream=True,
            )

            async def run_round():
                llm_gate = getattr(runtime.manager, "llm_semaphore", None)
                if llm_gate is not None:
                    async with llm_gate:
                        return await turn_loop.run(request, _round_emit, cancel, tools=round_tools)
                return await turn_loop.run(request, _round_emit, cancel, tools=round_tools)

            async def pausable_round(pause=pause, run_round=run_round):
                if pause is not None:
                    return await pause.model_request(run_round, agent.parent_cancel or cancel)
                return await run_round()

            result = await _await_input_interrupt(pausable_round(), agent.interrupt_event)
            if result is None:
                if pause is not None and pause.generation != pause_generation:
                    steps -= 1
                # No tools from a discarded generation have run. The next
                # iteration consumes the queued input at the normal boundary.
                history.discard()
                continue

            if result.usage is not None:
                saw_usage = True
                for key in usage_totals:
                    usage_totals[key] += getattr(result.usage, key, 0) or 0

            if result.cancelled:
                _save_cancel_checkpoint()
                raise asyncio.CancelledError

            if result.outcome is TurnOutcomeStatus.INTERRUPTED:
                _save_cancel_checkpoint()
                raise asyncio.CancelledError

            # Overflow is deterministic: ``compact_fn`` has already run and the
            # same messages would overflow again, so there is nothing to retry.
            if result.outcome is TurnOutcomeStatus.CONTEXT_OVERFLOW:
                raise RuntimeError(
                    "sub-agent context overflow: "
                    f"{result.error_message or 'context could not be shortened'}"
                )

            # A failed round used to be indistinguishable from "prose, no tool
            # calls": the loop broke out and the manager reported success with a
            # half-written fragment as the deliverable. Re-run it, then fail.
            if result.outcome is not TurnOutcomeStatus.SUCCESS:
                round_failures += 1
                if round_failures > MAX_SUBAGENT_ROUND_FAILURES:
                    raise RuntimeError(
                        "sub-agent LLM round failed: "
                        f"{result.error_message or 'unknown error'}"
                    )
                history.discard()
                continue

            # Truncation is deterministic too — the same request hits the same
            # cap at the same place — so the fragment is dropped and the round
            # re-run asking for less, never continued from mid-sentence.
            if result.truncated:
                round_failures += 1
                if round_failures > MAX_SUBAGENT_ROUND_FAILURES:
                    raise RuntimeError(
                        "sub-agent response truncated at the output cap on "
                        f"{round_failures} consecutive rounds; narrow the "
                        "assignment or raise the cap for this agent type"
                    )
                messages.append(
                    reminders.reminder_message(
                        reminders.SUBAGENT_OUTPUT_NUDGE, _SUBAGENT_TRUNCATED_NUDGE
                    )
                )
                from deepseek_tui.utils.user_text import user_text

                history.discard(user_text("round_truncated", _locale if _locale in ("zh", "en") else None))
                continue

            round_failures = 0

            if result.assistant_message is not None:
                messages.append(result.assistant_message)

            round_text, round_thinking = _assistant_text_and_thinking(
                result.assistant_message
            )
            # Knowledge line for the Workbench step rail (before tools of this
            # round). Prefer model preface; fall back to thinking. Skip when empty.
            narration = _mailbox_round_narration(round_text, round_thinking)
            # Not final here: stall nudges and summary recovery may still run
            # more rounds. The executor marks the delivered text final.
            history.settle(round_text, narration=None if round_text else narration)
            if round_text:
                final_text = round_text
            if round_thinking:
                last_thinking = round_thinking

            if narration and runtime.mailbox is not None:
                runtime.mailbox.send(MailboxMessage.progress(agent.id, narration))

            async def _may_stop() -> bool:
                """True when the run should end now; False means loop again."""
                nonlocal force_summary
                if await _subagent_stop_allowed():
                    if pause is not None and (
                        pause.paused or pause.generation != pause_generation
                    ):
                        return False
                    if not agent.input_queue.empty() or await _deliver_children():
                        _save_complete_checkpoint("round")
                        return False
                    return True
                # Blocked by a hook: give the agent its tools back and keep going.
                force_summary = False
                _save_complete_checkpoint("round")
                return False

            if not result.tool_calls:
                # The only stop signal is a ### SUMMARY report. Length and
                # wording do not graduate the child — no heading means the
                # assignment is still open, same as an empty thinking round.
                if round_text and has_summary_section(round_text):
                    if await _may_stop():
                        break
                    continue
                if (
                    round_text
                    and not use_structured_output
                    and "### SUMMARY" not in round_text
                    and _looks_like_report(round_text)
                ):
                    if not heading_requested:
                        heading_requested = True
                        force_summary = True
                        messages.append(
                            reminders.reminder_message(
                                reminders.SUBAGENT_OUTPUT_NUDGE,
                                _SUBAGENT_MISSING_HEADING_NUDGE,
                            )
                        )
                        _save_complete_checkpoint("round")
                        continue
                    # Asked once already: hand over what it wrote.
                    if await _may_stop():
                        break
                    continue
                # No report. Keep the tools and ask for the next concrete
                # action. Forcing the summary here used to confiscate the
                # catalog, so a child that had stalled halfway could not
                # resume even in principle.
                if (
                    not force_summary
                    and not structured_received
                    and empty_rounds < MAX_SUBAGENT_EMPTY_ROUNDS
                ):
                    empty_rounds += 1
                    messages.append(
                        reminders.reminder_message(
                            reminders.SUBAGENT_OUTPUT_NUDGE,
                            _SUBAGENT_STALLED_ROUND_NUDGE,
                        )
                    )
                    _save_complete_checkpoint("round")
                    continue
                if not force_summary and not structured_received:
                    force_summary = True
                    nudge = (
                        _SUBAGENT_STRUCTURED_OUTPUT_NUDGE
                        if use_structured_output
                        else _SUBAGENT_FINAL_REPORT_NUDGE
                    )
                    messages.append(
                        reminders.reminder_message(
                            reminders.SUBAGENT_OUTPUT_NUDGE, nudge
                        )
                    )
                    _save_complete_checkpoint("round")
                    continue
                if round_thinking and not final_text:
                    final_text = round_thinking
                if _try_summary_recovery():
                    _save_complete_checkpoint("round")
                    continue
                if await _may_stop():
                    break
                continue

            # Tool calls are progress: the stall budget bounds a run of rounds
            # that do nothing, not the run as a whole.
            empty_rounds = 0

            from deepseek_tui.protocol.messages import ToolUseBlock

            messages.append(
                Message.assistant_with_tools(
                    [
                        ToolUseBlock(id=tc.id, name=tc.name, input=tc.arguments)
                        for tc in result.tool_calls
                    ]
                )
            )

            for call_index, tc in enumerate(result.tool_calls):
                if _subagent_cancelled(cancel, agent):
                    _save_cancel_checkpoint()
                    raise asyncio.CancelledError
                if agent.interrupt_event.is_set() or (pause is not None and (
                    pause.paused or pause.generation != pause_generation
                )):
                    messages.append(
                        Message.tool_result(
                            tc.id, "Not executed: superseded by user input or human intervention.",
                            is_error=True,
                        )
                    )
                    continue
                history.tool(tc.id, tc.name, tc.arguments)
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
                        structured_received = True
                else:
                    ok, output = await _run_subagent_tool(
                        registry,
                        context,
                        tool_name=tc.name,
                        tool_input=tc.arguments,
                        auto_approve=runtime.auto_approve,
                        tool_call_id=tc.id,
                        runtime=runtime,
                        model=effective_model,
                        interrupt=agent.interrupt_event,
                        pause_generation=pause_generation,
                    )
                    # Here, not inside: denials and hook blocks return early as "Error:" text.
                    facts.record(tc.name, tc.arguments, success=ok, error=output,
                                 metadata=context.metadata.get("tool_result_metadata", {})
                                 .get(tc.id))
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
                            cua_surface=context.metadata.get("tool_result_metadata", {})
                            .get(tc.id, {}).get("cua_surface"),
                        )
                    )
                if tc.name in ("agent", "task_output", "task_stop"):
                    from deepseek_tui.tools.subagent.completion import terminal_agent_ids

                    args = tc.arguments if isinstance(tc.arguments, dict) else {}
                    restarted = args.get("resume") or (
                        args.get("agent_id") if args.get("action") == "send_input" else None
                    )
                    if isinstance(restarted, str):
                        reported_children.discard(restarted)
                    elif ok:
                        reported_children.update(terminal_agent_ids(
                            context.metadata.get("tool_result_metadata", {}).get(tc.id)
                        ))
                history.tool(
                    tc.id, tc.name, tc.arguments,
                    context.metadata.get("tool_result_content", {}).pop(tc.id, output), ok,
                    context.metadata.get("tool_result_metadata", {}).pop(tc.id, {}),
                )
                tool_failures = 0 if ok else tool_failures + 1
                messages.append(
                    Message.tool_result(
                        tc.id,
                        output,
                        is_error=not ok,
                        images=context.metadata.get("tool_images", {}).pop(tc.id, []),
                    )
                )
                if structured_received and not agent.interrupt_event.is_set():
                    for skipped in result.tool_calls[call_index + 1:]:
                        messages.append(Message.tool_result(
                            skipped.id, "Not executed: structured output completed this attempt.",
                            is_error=True,
                        ))
                    break

            if tool_failures >= MAX_CONSECUTIVE_TOOL_FAILURES:
                messages.append(
                    reminders.reminder_message(
                        reminders.SUBAGENT_OUTPUT_NUDGE,
                        _SUBAGENT_TOOL_FAILURE_NUDGE.format(n=tool_failures),
                    )
                )
                # Cleared so a child that keeps failing gets told again rather
                # than once; the step budget stays the hard bound.
                tool_failures = 0
            used = steps - attempt_start_steps
            if used % SUBAGENT_ROUND_NUDGE_INTERVAL == 0:
                messages.append(
                    reminders.reminder_message(
                        reminders.SUBAGENT_OUTPUT_NUDGE,
                        _SUBAGENT_ROUND_BUDGET_NUDGE.format(
                            used=used,
                            budget=DEFAULT_MAX_STEPS,
                            deliver=(
                                "make your structured_output call"
                                if use_structured_output
                                else "write your final report"
                            ),
                        ),
                    )
                )
            _save_complete_checkpoint("round")
            if agent.interrupt_event.is_set():
                structured_value = None
                structured_received = False
                force_summary = False
                continue
            if structured_received:
                break
        else:
            # Reached only when the loop condition went false. Every `break`
            # above is the child ending its own run, so this is the one exit
            # that means the budget ran out from under it. Whatever it did write
            # still goes to the parent — labelled, not passed off as finished.
            agent.max_steps_reached = True
        if budget_forced:
            # The report was written because the budget ran out; the parent
            # still needs to know the assignment may be unfinished.
            agent.max_steps_reached = True
    except asyncio.CancelledError:
        _save_cancel_checkpoint()
        raise
    finally:
        cancel_children = getattr(runtime.manager, "cancel_children", None)
        if callable(cancel_children):
            try:
                await cancel_children(agent.id)
            except Exception:  # noqa: BLE001 — cleanup must not mask the run's outcome
                _LOG.warning("subagent child cleanup failed id=%s", agent.id, exc_info=True)
        if cua_session is not None:
            try:
                await cua_session.end_turn(interrupted=_subagent_cancelled(cancel, agent))
            finally:
                await cua_session.close()
                # Only an unreviewed outcome keeps a finished child on the parent panel.
                manager = runtime.manager
                if not cua_session.unresolved and getattr(manager, "cua_sessions", {}).pop(
                        agent.id, None) is not None:
                    # Keep the panel's revision monotonic after the child leaves the sum.
                    manager.cua_retired_revision = (
                        getattr(manager, "cua_retired_revision", 0) + cua_session.control_revision)
        if runtime.mailbox is not None and saw_usage:
            runtime.mailbox.send(MailboxMessage.token_usage(agent.id, effective_model, usage_totals))


    agent.steps_taken = steps
    if use_structured_output and not structured_received:
        raise RuntimeError("sub-agent did not return structured_output")
    if not final_text and last_thinking:
        final_text = last_thinking
    # The parent reads this report, so unlike a main turn's note these facts belong in it.
    pending = facts.pending(context.metadata)
    problems = ["Step budget exhausted"] if agent.max_steps_reached else []
    task_outcome = facts.outcome(pending, problems, "en")
    if note := facts.note(pending, problems, "en"):
        final_text = f"{final_text}\n\n{note}".strip()
    # Keep the checkpoint for resume (the break paths exit without saving).
    # Report shape is not a reason to wipe memory — Kimi leaves context
    # memory in place after distillSummary. close() is the only wipe.
    _save_complete_checkpoint("round")
    return AgentRunOutput(text=final_text, structured=structured_value,
                          structured_received=structured_received, task_outcome=task_outcome)
