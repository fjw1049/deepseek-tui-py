"""Tool execution dispatch and argument repair.

Consolidates dispatch.py, executors.py, arg_repair.py.
Tool dispatch — plan/execute helpers for the per-turn tool batch.

Owns:
  * The ``multi_tool_use.parallel`` payload parser.
  * Policy predicates: parallel batch, plan-mode stop/force, MCP safety.
  * Tool execution plan/outcome types.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from deepseek_tui.tools.registry import ToolError
import json as _json
import logging as _logging
import os as _os
import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING
from collections.abc import Awaitable, Callable
import json
import re

# --- Types ---------------------------------------------------------------


@dataclass
class ToolExecutionPlan:
    """Per-tool execution plan built before dispatch."""

    index: int
    id: str
    name: str
    input: dict[str, Any]
    caller: str | None = None
    interactive: bool = False
    approval_required: bool = False
    approval_description: str = "Tool execution requires approval"
    supports_parallel: bool = False
    read_only: bool = False
    blocked_error: ToolError | None = None


# --- Error formatting -----------------------------------------------------


def format_tool_error(err: Exception, tool_name: str) -> str:
    """Format a tool error into a human-friendly message."""
    msg = str(err)
    lower = msg.lower()
    if "invalid input" in lower:
        return f"Invalid input for tool '{tool_name}': {msg}"
    if "missing" in lower and "field" in lower:
        return f"Tool '{tool_name}' is missing a required field: {msg}"
    if "path escape" in lower or "workspace" in lower:
        return (
            f"Path escapes workspace: {msg}. "
            "Use a workspace-relative path or enable trust mode."
        )
    if "timeout" in lower:
        return f"Tool '{tool_name}' timed out: {msg}"
    if "not available" in lower:
        if "current tool catalog" in lower or "did you mean" in lower:
            return msg
        return (
            f"Tool '{tool_name}' is not available: {msg}. "
            "Check mode, feature flags, or tool name."
        )
    if "permission" in lower or "denied" in lower:
        return (
            f"Tool '{tool_name}' was denied: {msg}. "
            "Adjust approval mode or request permission."
        )
    return msg


# --- Parallel tool calls --------------------------------------------------


def _normalize_parallel_tool_name(raw: str) -> str:
    name = raw.strip()
    for prefix in ("functions.", "tools.", "tool."):
        if name.startswith(prefix):
            return name[len(prefix) :]
    return name


def parse_parallel_tool_calls(
    input_data: dict[str, Any],
) -> list[tuple[str, dict[str, Any]]]:
    """Parse a multi_tool_use.parallel payload into (name, params) pairs."""
    tool_uses = input_data.get("tool_uses")
    if not isinstance(tool_uses, list) or not tool_uses:
        raise ToolError(
            "multi_tool_use.parallel requires at least one tool call in 'tool_uses'"
        )

    calls: list[tuple[str, dict[str, Any]]] = []
    for item in tool_uses:
        if not isinstance(item, dict):
            continue
        name = (
            item.get("recipient_name")
            or item.get("tool_name")
            or item.get("name")
            or item.get("tool")
        )
        if not isinstance(name, str):
            raise ToolError("Each tool_use must have a 'recipient_name' or 'name'")
        params = (
            item.get("parameters")
            or item.get("input")
            or item.get("args")
            or item.get("arguments")
            or {}
        )
        if not isinstance(params, dict):
            params = {}
        calls.append((_normalize_parallel_tool_name(name), params))

    return calls


# --- Dispatch policy ------------------------------------------------------


def should_parallelize_tool_batch(plans: list[ToolExecutionPlan]) -> bool:
    """True if all tools in the batch are safe for parallel execution."""
    if not plans:
        return False
    return all(
        p.read_only and p.supports_parallel and not p.approval_required and not p.interactive
        for p in plans
    )


def should_stop_after_plan_tool(
    mode: str, tool_name: str, success: bool
) -> bool:
    """In Plan mode, stop after a successful update_plan."""
    return mode == "plan" and tool_name == "update_plan" and success


def should_force_update_plan_first(mode: str, content: str) -> bool:
    """In Plan mode, detect quick-plan requests that skip repo exploration."""
    if mode != "plan":
        return False

    lower = content.lower()
    plan_needles = (
        "quick plan", "short plan", "simple plan",
        "3-step plan", "3 step plan", "three-step plan", "three step plan",
        "high-level plan", "high level plan",
        "give me a plan", "make a plan", "outline a plan", "draft a plan",
    )
    if not any(n in lower for n in plan_needles):
        return False

    exploration_needles = (
        "inspect the repo", "inspect the code", "explore the repo",
        "search the repo", "read the code", "review the code",
        "analyze the code", "investigate", "look through",
        "understand the current", "ground it in the codebase",
        "based on the codebase",
    )
    return not any(n in lower for n in exploration_needles)


# --- MCP tool policy ------------------------------------------------------

_MCP_PARALLEL_SAFE = frozenset(
    {
        "list_mcp_resources",
        "list_mcp_resource_templates",
        "mcp_read_resource",
        "read_mcp_resource",
        "mcp_get_prompt",
    }
)


def is_mcp_tool(name: str) -> bool:
    """Check if a tool name refers to an MCP tool."""
    if name in _MCP_PARALLEL_SAFE:
        return True
    if name.startswith("mcp__"):
        return True
    return name.startswith("mcp_")


def mcp_tool_is_parallel_safe(name: str) -> bool:
    return name in _MCP_PARALLEL_SAFE


def mcp_tool_is_read_only(name: str) -> bool:
    return name in _MCP_PARALLEL_SAFE


def mcp_tool_approval_description(name: str) -> str:
    if mcp_tool_is_read_only(name):
        return f"Read-only MCP tool '{name}'"
    return f"MCP tool '{name}' may have side effects"


# --- Audit logging (formerly engine/tool_execution.py) -----------------------


_audit_logger = _logging.getLogger(__name__)


def emit_tool_audit(event: dict[str, Any]) -> None:
    """Append a JSONL audit line to ``$DEEPSEEK_TOOL_AUDIT_LOG`` if set.

    Silent no-op when the env var is unset or the write fails.
    """
    path_str = _os.environ.get("DEEPSEEK_TOOL_AUDIT_LOG")
    if not path_str:
        return
    try:
        line = _json.dumps(event, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return
    from pathlib import Path

    path = Path(path_str)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


# Real executors for Task and SubAgent — replace the sleep-50ms stubs.
# Sub-agents run ``run_subagent_loop`` (shared SubAgentManager, no nested Engine).
# Tasks run a single Engine turn with the **shared** process TaskManager injected.



from deepseek_tui.engine.events import (
    AgentRoundCompleteEvent,
    ErrorEvent,
    ToolResultEvent,
    TurnCancelledEvent,
    TurnCompleteEvent,
    UserInputRequiredEvent,
)
from deepseek_tui.engine.handle import EngineHandle
from deepseek_tui.tools.task import CRON_PROMPT_MARKER

if TYPE_CHECKING:
    from deepseek_tui.tools.subagent import SubAgent
    from deepseek_tui.tools.subagent import AgentRunOutput
    from deepseek_tui.tools.task import ExecutionTask, TaskExecutionResult

logger = logging.getLogger(__name__)

# Durable background tasks (not short interactive turns). Align round budget
# with the main Engine / sub-agent loop (100); keep a wall-clock ceiling so a
# wedged emit/queue cannot run forever. Cron stays tighter — scheduled jobs
# should finish promptly — but still large enough for search + a few tool
# rounds rather than toy limits that abort mid-work.
TASK_MAX_TOOL_ROUND_TRIPS = 100
CRON_MAX_TOOL_ROUND_TRIPS = 40
# 2h ordinary / 15min cron. Timeout → TIMED_OUT (resumable via transcript).
TASK_WALL_CLOCK_SECONDS = 7200
CRON_TASK_WALL_CLOCK_SECONDS = 900


def _is_cron_task(prompt: str) -> bool:
    return prompt.lstrip().startswith(CRON_PROMPT_MARKER)


# Primary argument shown next to a tool name in the task run log, so a line
# reads like ``read_file · src/x.py`` instead of a bare, cryptic tool name.
_TOOL_PRIMARY_ARG: dict[str, str] = {
    "read_file": "path",
    "write_file": "path",
    "edit_file": "path",
    "list_dir": "path",
    "apply_patch": "path",
    "exec_shell": "command",
    "exec_shell_interact": "input",
    "grep_files": "pattern",
    "file_search": "pattern",
    "web_search": "query",
    "fetch_url": "url",
    "git_show": "ref",
    "load_skill": "name",
    "task_create": "prompt",
    "agent_spawn": "prompt",
    "delegate_to_agent": "prompt",
}


def _tool_primary_arg(name: str, args: dict[str, Any]) -> str:
    """Pick the most descriptive scalar argument for *name* (best-effort)."""
    value: Any = None
    key = _TOOL_PRIMARY_ARG.get(name)
    if key is not None:
        value = args.get(key)
    if not isinstance(value, str) or not value.strip():
        value = next(
            (v for v in args.values() if isinstance(v, str) and v.strip()), None
        )
    if not isinstance(value, str):
        return ""
    collapsed = " ".join(value.split())
    return collapsed[:120]


def _describe_tool_call(
    name: str, args: dict[str, Any], success: bool, content: str
) -> str:
    """Build one readable run-log line for a finished tool call."""
    arg = _tool_primary_arg(name, args)
    label = f"{name} · {arg}" if arg else name
    if success:
        return label
    reason = " ".join((content or "").split())[:160]
    return f"{label} — {reason}" if reason else label


async def _collect_turn_events(
    handle: EngineHandle,
    cancel: asyncio.Event,
    on_tool_event: Callable[..., Awaitable[None]] | None = None,
) -> tuple[str, str | None]:
    """Drain events until turn end. Returns (final_assistant_text, error_message).

    When ``on_tool_event`` is provided, the task's "run log" is streamed as
    ``(kind, summary[, detail])`` triples that read like a mini conversation:

    * ``("text", ...)`` — the model's own narration for a round (what it is
      about to do / reasoning), taken from the round's preface text.
    * ``("tool", ...)`` / ``("tool_error", ...)`` — a single readable line per
      tool call, e.g. ``read_file · src/x.py`` or ``exec_shell · pytest -q``,
      with the failure reason appended on error. Optional ``detail`` carries a
      truncated tool output for the Workbench step-flow expand panel.
    """
    from deepseek_tui.automation.delivery import assistant_message_text
    from deepseek_tui.utils import summarize_text

    final_text = ""
    error_msg: str | None = None
    # tool_call_id -> arguments, captured at round-complete so the result
    # event (which omits arguments) can be rendered with its key parameter.
    pending_args: dict[str, dict[str, Any]] = {}

    async def _emit_tool_event(
        kind: str, summary: str, detail: str | None = None
    ) -> None:
        if on_tool_event is None:
            return
        try:
            await on_tool_event(kind, summary, detail)
        except TypeError:
            # Older/test callbacks that only accept (kind, summary).
            await on_tool_event(kind, summary)

    async for event in handle.events():
        if cancel.is_set():
            await handle.cancel("executor_cancelled")
            break

        if isinstance(event, ErrorEvent):
            error_msg = event.message
        elif isinstance(event, AgentRoundCompleteEvent):
            for call in event.tool_calls:
                pending_args[call.id] = dict(call.arguments or {})
            if on_tool_event is not None:
                narration = (event.preface_text or "").strip()
                if narration:
                    await _emit_tool_event("text", narration, narration)
        elif isinstance(event, ToolResultEvent):
            if on_tool_event is not None:
                args = pending_args.pop(event.tool_call_id, {})
                kind = "tool" if event.success else "tool_error"
                summary = _describe_tool_call(
                    event.tool_name, args, event.success, event.content
                )
                detail = summarize_text(event.content or "", 4_000) or None
                await _emit_tool_event(kind, summary, detail)
        elif isinstance(event, UserInputRequiredEvent):
            future = handle.pending_user_inputs.get(event.tool_call_id)
            if future and not future.done():
                future.set_result(
                    {"error": "Background executors cannot request user input"}
                )
        elif isinstance(event, TurnCompleteEvent):
            final_text = assistant_message_text(event.assistant_message)
            break
        elif isinstance(event, TurnCancelledEvent):
            break

    return final_text, error_msg


async def _run_task_engine_turn(
    task: ExecutionTask, cancel: asyncio.Event
) -> "TaskExecutionResult":
    from deepseek_tui.client.factory import build_llm_client
    from deepseek_tui.config.loader import ConfigLoader
    from deepseek_tui.config.models import FeatureConfig, HooksConfig
    from deepseek_tui.engine.orchestrator import Engine
    from deepseek_tui.engine.handle import AutoApprovalHandler, DenyApprovalHandler
    from deepseek_tui.tools.runtime import create_tool_runtime
    from deepseek_tui.tools.task import TaskExecutionResult

    cfg = ConfigLoader().load()
    cfg = cfg.model_copy(deep=True)
    cfg.features = FeatureConfig(
        tasks=True,
        subagents=True,
        mcp=True,
        automations=False,
    )
    cfg.hooks = HooksConfig(enabled=False, hooks=[])
    handle = EngineHandle()
    client = build_llm_client(cfg)
    workspace = Path(task.workspace).resolve()  # noqa: ASYNC240

    shared_mcp = getattr(task.task_manager, "_shared_mcp_manager", None)
    runtime = await create_tool_runtime(
        config=cfg,
        working_directory=workspace,
        shared_task_manager=task.task_manager,
        mcp_manager=shared_mcp,
        start_mcp=False,
    )

    # Tasks run detached — there is no interactive channel to surface an
    # approval prompt. auto_approve=True lets the task use privileged tools;
    # otherwise DenyApprovalHandler refuses them so the model sees a refusal
    # instead of hanging on a prompt nobody can answer. Passing None would
    # fall through to Engine.__init__'s AutoApprovalHandler() default and
    # silently make every task auto-approved.
    approval_handler = (
        AutoApprovalHandler() if task.auto_approve else DenyApprovalHandler()
    )
    max_rounds = (
        CRON_MAX_TOOL_ROUND_TRIPS
        if _is_cron_task(task.prompt)
        else TASK_MAX_TOOL_ROUND_TRIPS
    )

    engine = await Engine.create(
        handle=handle,
        client=client,
        config=cfg,
        working_directory=workspace,
        default_model=task.model,
        max_tool_round_trips=max_rounds,
        approval_handler=approval_handler,
        tool_runtime=runtime,
    )
    engine.tool_context.trust_mode = task.trust_mode
    engine.tool_context.active_task_id = task.id
    engine.tool_context.metadata["task_id"] = task.id
    # Engine.create attaches SubAgentRuntime before the task id is known;
    # bind it now so nested sub-agents inherit the nest-depth guard.
    sub_mgr = engine.tool_context.subagent_manager
    if sub_mgr is not None and hasattr(sub_mgr, "bind_active_task_id"):
        sub_mgr.bind_active_task_id(task.id)

    from deepseek_tui.tools.durable_transcript import (
        CONTINUE_NUDGE,
        DurableTranscript,
        clear_transcript,
        dicts_to_messages,
        load_transcript,
        messages_to_dicts,
        save_transcript,
        task_transcript_path,
    )

    manager = getattr(task, "task_manager", None)
    # Go through TaskManager's public accessor rather than reaching into its
    # private ``_cfg`` — keeps this decoupled from TaskManager's internals.
    data_dir_fn = getattr(manager, "data_dir", None)
    data_dir = data_dir_fn() if callable(data_dir_fn) else None
    transcript_path = (
        task_transcript_path(Path(data_dir), task.id)
        if data_dir is not None
        else None
    )
    existing = load_transcript(transcript_path) if transcript_path else None
    resuming = bool(
        existing
        and existing.messages
        and existing.round_complete
        and existing.owner_id == task.id
    )
    if resuming and existing is not None:
        engine.session_messages = dicts_to_messages(existing.messages)

    async def _on_turn_checkpoint(messages: list[Any], steps: int) -> None:
        if transcript_path is None:
            return
        # Offload the blocking write-tmp+rename so a checkpoint on every tool
        # round doesn't stall the event loop for other tasks/agents. The
        # caller (orchestrator/core.py) already awaits this when it returns a
        # coroutine.
        await asyncio.to_thread(
            save_transcript,
            transcript_path,
            DurableTranscript(
                owner_kind="task",
                owner_id=task.id,
                messages=messages_to_dicts(messages),
                steps_taken=int(steps),
                force_summary=False,
                round_complete=True,
                checkpoint_reason="round",
            ),
        )

    engine.tool_context.metadata["on_turn_checkpoint"] = _on_turn_checkpoint

    async def _record_tool_event(
        kind: str, summary: str, detail: str | None = None
    ) -> None:
        mgr = getattr(task, "task_manager", None)
        recorder = getattr(mgr, "record_tool_timeline", None)
        if recorder is None:
            return
        try:
            await recorder(task.id, kind, summary, detail)
        except TypeError:
            try:
                await recorder(task.id, kind, summary)
            except Exception:  # noqa: BLE001 -- progress logging must never break the task
                logger.debug(
                    "task_tool_timeline_record_failed id=%s", task.id, exc_info=True
                )
        except Exception:  # noqa: BLE001 -- progress logging must never break the task
            logger.debug("task_tool_timeline_record_failed id=%s", task.id, exc_info=True)

    # Consume events concurrently with the turn. run_single_turn emits into a
    # bounded queue (maxsize=4096); awaiting the turn first then draining
    # deadlocks once the queue fills (long streams / tool chatter).
    #
    # Also bridge the TaskManager cancel token onto handle.cancel_event.
    # run_single_turn() calls reset_cancel() at entry, so we re-assert after
    # the turn becomes active (or immediately if cancel was already set).
    async def _bridge_cancel() -> None:
        await cancel.wait()
        handle._cancel_reason = "executor_cancelled"
        handle.cancel_event.set()

    turn_prompt = CONTINUE_NUDGE if resuming else task.prompt

    async def _run_turn_bridged() -> None:
        turn_task = asyncio.create_task(
            engine.run_single_turn(turn_prompt, model=task.model)
        )
        try:
            while not handle.is_turn_active() and not turn_task.done():
                await asyncio.sleep(0)
            if cancel.is_set():
                handle._cancel_reason = "executor_cancelled"
                handle.cancel_event.set()
            await turn_task
        except BaseException:
            if not turn_task.done():
                turn_task.cancel()
                try:
                    await turn_task
                except (asyncio.CancelledError, Exception):
                    pass
            raise

    bridge_task = asyncio.create_task(_bridge_cancel())
    collect_task = asyncio.create_task(
        _collect_turn_events(handle, cancel, on_tool_event=_record_tool_event)
    )
    try:
        try:
            await _run_turn_bridged()
        except BaseException:
            # Turn blew up without a terminal event — stop the collector so
            # we don't hang forever on handle.events().
            if not collect_task.done():
                collect_task.cancel()
                try:
                    await collect_task
                except (asyncio.CancelledError, Exception):
                    pass
            raise
        try:
            result_text, error_msg = await asyncio.wait_for(
                collect_task, timeout=30.0
            )
        except asyncio.TimeoutError:
            collect_task.cancel()
            try:
                await collect_task
            except (asyncio.CancelledError, Exception):
                pass
            return TaskExecutionResult(
                summary="",
                error="Task ended without a turn completion event",
            )
        if error_msg:
            return TaskExecutionResult(
                summary=result_text or "Task failed",
                detail=None,
                error=error_msg,
            )
        if cancel.is_set():
            return TaskExecutionResult(summary=result_text, error="canceled")
        if transcript_path is not None:
            clear_transcript(transcript_path)
        return TaskExecutionResult(summary=result_text, detail=None, error=None)
    finally:
        bridge_task.cancel()
        try:
            await bridge_task
        except (asyncio.CancelledError, Exception):
            pass
        if not collect_task.done():
            collect_task.cancel()
            try:
                await collect_task
            except (asyncio.CancelledError, Exception):
                pass
        # shutdown() (not shutdown_session()) so the per-task LLM client
        # built above is closed — otherwise every task leaks its HTTP
        # connection pool. SessionEndedEvent is swallowed by try/except
        # inside shutdown(); drain_events() clears it either way.
        await engine.shutdown()
        handle.drain_events()


async def real_task_executor(
    task: ExecutionTask, cancel: asyncio.Event
) -> "TaskExecutionResult":
    """Run one Engine turn for a queued task (shared TaskManager)."""
    from deepseek_tui.tools.task import TaskExecutionResult

    wall_clock = (
        CRON_TASK_WALL_CLOCK_SECONDS
        if _is_cron_task(task.prompt)
        else TASK_WALL_CLOCK_SECONDS
    )
    try:
        return await asyncio.wait_for(
            _run_task_engine_turn(task, cancel),
            timeout=wall_clock,
        )
    except asyncio.TimeoutError:
        # Stop the in-flight turn, but do NOT treat timeout as user cancel.
        # Finalize path keys off ``timed_out=True`` → TaskStatus.TIMED_OUT.
        cancel.set()
        logger.warning(
            "[task_executor] wall-clock timeout task_id=%s after=%ds cron=%s",
            task.id,
            wall_clock,
            _is_cron_task(task.prompt),
        )
        return TaskExecutionResult(
            summary="",
            error=f"Task timed out after {wall_clock}s",
            timed_out=True,
        )


async def real_subagent_executor(agent: SubAgent, cancel: asyncio.Event) -> AgentRunOutput:
    """Drive ``run_subagent_loop`` — no nested Engine / managers."""
    from deepseek_tui.tools.subagent import run_subagent_loop
    from deepseek_tui.tools.subagent import AgentRunOutput

    runtime = agent.loop_runtime
    if runtime is None:
        raise RuntimeError(
            "Sub-agent loop runtime is missing; Engine.create must call "
            "SubAgentManager.attach_loop_runtime"
        )
    out = await run_subagent_loop(agent, runtime, cancel)
    if isinstance(out, AgentRunOutput):
        return out
    return AgentRunOutput(text=str(out), structured=None)


# Deterministic JSON argument repair ladder.
# LLM streaming can produce malformed JSON in tool call arguments:
# - Truncated streams → unclosed braces/brackets
# - Control characters (0x00-0x1F) inside string values
# - Trailing commas before } or ]
# - Excess closing delimiters from delta corruption
# The repair ladder attempts increasingly aggressive fixes, guaranteeing
# a valid dict is always returned (worst case: empty {}).


# Max input size — beyond this we bail to {} to avoid pathological regex.
_MAX_INPUT_BYTES = 1_048_576  # 1 MiB


def repair(raw: str) -> dict:
    """Attempt to parse *raw* as JSON, applying repairs if needed.

    Always returns a dict. Never raises.
    """
    if not raw or not raw.strip():
        return {}

    if len(raw) > _MAX_INPUT_BYTES:
        return {}

    # Stage 1: strict parse
    result = _try_parse(raw)
    if result is not None:
        return result

    # Stage 2: strip control chars inside string values
    cleaned = _strip_control_chars_in_strings(raw)
    if cleaned != raw:
        result = _try_parse(cleaned)
        if result is not None:
            return result
    else:
        cleaned = raw

    # Stage 3: strip trailing commas before } or ]
    no_trailing = _strip_trailing_commas(cleaned)
    if no_trailing != cleaned:
        result = _try_parse(no_trailing)
        if result is not None:
            return result
    else:
        no_trailing = cleaned

    # Stage 4: balance braces/brackets
    balanced = _balance_braces(no_trailing)
    if balanced != no_trailing:
        result = _try_parse(balanced)
        if result is not None:
            return result

    # Stage 5: strip excess closers
    stripped = _strip_excess_closers(no_trailing)
    if stripped != no_trailing:
        result = _try_parse(stripped)
        if result is not None:
            return result

    # Fallback: empty object
    return {}


def _try_parse(s: str) -> dict | None:
    """Return parsed dict or None."""
    try:
        obj = json.loads(s)
    except (json.JSONDecodeError, ValueError):
        return None
    if isinstance(obj, dict):
        return obj
    # Non-dict JSON (e.g. array, scalar) — wrap it
    return {"value": obj}


def _strip_control_chars_in_strings(s: str) -> str:
    """Remove 0x00-0x1F (except \\t \\n \\r) that appear inside JSON strings."""
    out: list[str] = []
    in_string = False
    escape_next = False
    for ch in s:
        if escape_next:
            out.append(ch)
            escape_next = False
            continue
        if ch == '\\' and in_string:
            out.append(ch)
            escape_next = True
            continue
        if ch == '"':
            in_string = not in_string
            out.append(ch)
            continue
        if in_string and ord(ch) < 0x20 and ch not in ('\t', '\n', '\r'):
            continue  # drop control char
        out.append(ch)
    return "".join(out)


# Pattern: comma followed by optional whitespace then } or ]
_TRAILING_COMMA_RE = re.compile(r',\s*([}\]])')


def _strip_trailing_commas(s: str) -> str:
    """Remove trailing commas before closing delimiters."""
    return _TRAILING_COMMA_RE.sub(r'\1', s)


def _balance_braces(s: str) -> str:
    """Append missing closing braces/brackets."""
    stack: list[str] = []
    in_string = False
    escape_next = False
    for ch in s:
        if escape_next:
            escape_next = False
            continue
        if ch == '\\' and in_string:
            escape_next = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch in ('{', '['):
            stack.append('}' if ch == '{' else ']')
        elif ch in ('}', ']'):
            if stack and stack[-1] == ch:
                stack.pop()
    # Append missing closers in reverse order
    if stack:
        return s + "".join(reversed(stack))
    return s


def _strip_excess_closers(s: str) -> str:
    """Remove excess } or ] that have no matching opener."""
    stack: list[str] = []
    keep: list[bool] = [True] * len(s)
    in_string = False
    escape_next = False
    for i, ch in enumerate(s):
        if escape_next:
            escape_next = False
            continue
        if ch == '\\' and in_string:
            escape_next = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch in ('{', '['):
            stack.append(ch)
        elif ch == '}':
            if stack and stack[-1] == '{':
                stack.pop()
            else:
                keep[i] = False
        elif ch == ']':
            if stack and stack[-1] == '[':
                stack.pop()
            else:
                keep[i] = False
    if all(keep):
        return s
    return "".join(ch for ch, k in zip(s, keep) if k)