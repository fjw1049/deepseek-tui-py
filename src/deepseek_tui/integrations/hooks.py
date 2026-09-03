"""Event dispatch & lifecycle hooks.

Consolidates the former hooks/ package.
"""

from __future__ import annotations



# ======================================================================
# From events.py
# ======================================================================

"""Hook event definitions."""


from dataclasses import dataclass, field
from typing import Any
from pydantic import BaseModel
import asyncio
import json
from abc import ABC, abstractmethod
from pathlib import Path
import httpx
import logging
import uuid


@dataclass
class ResponseStartEvent:
    """Response stream started."""

    response_id: str


@dataclass
class ResponseDeltaEvent:
    """Response delta received."""

    response_id: str
    delta: str


@dataclass
class ResponseEndEvent:
    """Response stream ended."""

    response_id: str


@dataclass
class ToolLifecycleEvent:
    """Tool execution lifecycle event."""

    response_id: str
    tool_name: str
    phase: str
    payload: dict[str, Any]


@dataclass
class JobLifecycleEvent:
    """Job lifecycle event."""

    job_id: str
    phase: str
    progress: int | None = None
    detail: str | None = None


@dataclass
class ApprovalLifecycleEvent:
    """Approval lifecycle event."""

    approval_id: str
    phase: str
    reason: str | None = None


@dataclass
class GenericEventFrameEvent:
    """Generic event frame wrapper."""

    frame: dict[str, Any]  # Generic event payload


@dataclass
class SessionLifecycleEvent:
    """Session lifecycle event."""

    session_id: str
    phase: str  # "start" | "end"
    turns: int | None = None


HookEvent = (
    ResponseStartEvent
    | ResponseDeltaEvent
    | ResponseEndEvent
    | ToolLifecycleEvent
    | JobLifecycleEvent
    | ApprovalLifecycleEvent
    | GenericEventFrameEvent
    | SessionLifecycleEvent
)


def event_to_dict(event: HookEvent) -> dict[str, Any]:
    """Convert hook event to JSON-serializable dict."""
    if isinstance(event, ResponseStartEvent):
        return {"type": "response_start", "response_id": event.response_id}
    elif isinstance(event, ResponseDeltaEvent):
        return {
            "type": "response_delta",
            "response_id": event.response_id,
            "delta": event.delta,
        }
    elif isinstance(event, ResponseEndEvent):
        return {"type": "response_end", "response_id": event.response_id}
    elif isinstance(event, ToolLifecycleEvent):
        return {
            "type": "tool_lifecycle",
            "response_id": event.response_id,
            "tool_name": event.tool_name,
            "phase": event.phase,
            "payload": event.payload,
        }
    elif isinstance(event, JobLifecycleEvent):
        return {
            "type": "job_lifecycle",
            "job_id": event.job_id,
            "phase": event.phase,
            "progress": event.progress,
            "detail": event.detail,
        }
    elif isinstance(event, ApprovalLifecycleEvent):
        return {
            "type": "approval_lifecycle",
            "approval_id": event.approval_id,
            "phase": event.phase,
            "reason": event.reason,
        }
    elif isinstance(event, GenericEventFrameEvent):
        return {"type": "generic_event_frame", "frame": event.frame}
    elif isinstance(event, SessionLifecycleEvent):
        d: dict[str, Any] = {
            "type": "session_lifecycle",
            "session_id": event.session_id,
            "phase": event.phase,
        }
        if event.turns is not None:
            d["turns"] = event.turns
        return d
    # Unreachable due to exhaustive union check
    return {"type": "serialization_error"}  # type: ignore[unreachable]


# ======================================================================
# From frames.py
# ======================================================================

"""Bridge protocol EventFrame models into observability hook events."""





def generic_event_frame(frame: BaseModel) -> GenericEventFrameEvent:
    """Wrap a protocol frame for :class:`HookDispatcher` emission."""
    return GenericEventFrameEvent(frame=frame.model_dump(mode="json"))


# ======================================================================
# From sinks.py
# ======================================================================

"""Hook sinks for event emission.

Three sinks:

- :class:`StdoutHookSink`: prints JSON events line-by-line
- :class:`JsonlHookSink`: appends timestamped events to a JSONL log file
- :class:`WebhookHookSink`: POSTs events to a URL with backoff retry
  (max 2 retries, 200ms × attempt backoff)
"""






class HookSink(ABC):
    """Abstract base for hook event sinks."""

    @abstractmethod
    async def emit(self, event: HookEvent) -> None:
        """Emit a hook event."""
        ...


class StdoutHookSink(HookSink):
    """Emit hook events to stdout as JSON."""

    async def emit(self, event: HookEvent) -> None:
        payload = event_to_dict(event)
        print(json.dumps(payload), flush=True)


class JsonlHookSink(HookSink):
    """Append hook events to a JSONL file."""

    def __init__(self, path: Path) -> None:
        self.path = path

    async def emit(self, event: HookEvent) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload: dict[str, Any] = {
            "at": utc_now_iso(),
            "event": event_to_dict(event),
        }
        line = json.dumps(payload) + "\n"
        await asyncio.to_thread(self._write_line, line)

    def _write_line(self, line: str) -> None:
        with self.path.open("a", encoding="utf-8") as f:
            f.write(line)


class WebhookHookSink(HookSink):
    """POST hook events to a webhook URL.

    Max 2 retries, 200ms × retries backoff. Status != 2xx triggers retry.
    """

    def __init__(self, url: str, max_retries: int = 2) -> None:
        self.url = url
        self.max_retries = max_retries
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=10.0)
        return self._client

    async def emit(self, event: HookEvent) -> None:
        client = await self._get_client()
        payload: dict[str, Any] = {
            "at": utc_now_iso(),
            "event": event_to_dict(event),
        }
        retries = 0
        while True:
            try:
                resp = await client.post(self.url, json=payload)
                if resp.is_success:
                    return
                if retries >= self.max_retries:
                    raise RuntimeError(
                        f"webhook returned non-success status {resp.status_code}"
                    )
            except httpx.HTTPError as e:
                if retries >= self.max_retries:
                    raise RuntimeError(f"webhook request failed: {e}") from e
            retries += 1
            await asyncio.sleep(0.2 * retries)

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


def _truncate(text: str, limit: int) -> str:
    """Cap hook payload strings so a huge tool result can't blow up env/stdin."""
    return text if len(text) <= limit else text[:limit] + "...[truncated]"


async def _run_shell(
    command: str,
    *,
    timeout: float,
    stdin_data: bytes = b"",
    cwd: str | None = None,
    env: dict[str, str] | None = None,
    devnull_output: bool = False,
) -> tuple[int, bytes | None, bytes | None]:
    """Run one shell hook command to completion.

    Returns ``(exit_code, stdout, stderr)`` — outputs are ``None`` with
    ``devnull_output``. Raises ``asyncio.TimeoutError`` (child killed and
    reaped) or ``OSError``.
    """
    pipe = asyncio.subprocess.DEVNULL if devnull_output else asyncio.subprocess.PIPE
    proc = await asyncio.create_subprocess_shell(
        command,
        cwd=cwd,
        env=env,
        stdin=asyncio.subprocess.PIPE,
        stdout=pipe,
        stderr=pipe,
    )
    try:
        stdout_b, stderr_b = await asyncio.wait_for(
            proc.communicate(input=stdin_data), timeout=timeout
        )
    except asyncio.TimeoutError:
        proc.kill()
        # Reap the killed child; otherwise it lingers as a zombie.
        try:
            await proc.wait()
        except (OSError, ProcessLookupError):
            pass
        raise
    return proc.returncode or 0, stdout_b, stderr_b


class ShellHookSink(HookSink):
    """Execute a shell command when a matching event fires.

    Runs command with event JSON on stdin, respects timeout. Only fires
    for events matching ``event_filter``.
    """

    def __init__(
        self, event_filter: str, command: str, timeout: float = 30.0
    ) -> None:
        self.event_filter = event_filter
        self.command = command
        self.timeout = timeout

    async def emit(self, event: HookEvent) -> None:
        event_dict = event_to_dict(event)
        if event_dict.get("type") != self.event_filter:
            return
        stdin_data = json.dumps(event_dict).encode()
        try:
            await _run_shell(
                self.command, timeout=self.timeout, stdin_data=stdin_data
            )
        except (asyncio.TimeoutError, OSError):
            pass


# ======================================================================
# From dispatcher.py
# ======================================================================

"""Hook dispatcher for broadcasting events to multiple sinks."""




logger = logging.getLogger(__name__)


class HookDispatcher:
    """Broadcast hook events to multiple sinks."""

    def __init__(self) -> None:
        self.sinks: list[HookSink] = []

    def add_sink(self, sink: HookSink) -> None:
        """Register a sink."""
        self.sinks.append(sink)

    async def emit(self, event: HookEvent) -> None:
        """Emit event to all sinks (best-effort)."""
        for sink in self.sinks:
            try:
                await sink.emit(event)
            except Exception:
                logger.warning(
                    "hook sink emit failed sink=%s event=%s",
                    type(sink).__name__,
                    type(event).__name__,
                    exc_info=True,
                )


# ======================================================================
# From executor.py
# ======================================================================

"""Lifecycle hook executor.

User-defined shell commands from ``[[hooks.hooks]]`` in config.toml, triggered
at session/tool/mode/message/error/shell_env lifecycle points.
"""



from deepseek_tui.config.models import HooksConfig, LifecycleHookEntry
from deepseek_tui.utils import utc_now_iso

logger = logging.getLogger(__name__)

LIFECYCLE_EVENTS = frozenset(
    {
        "session_start",
        "session_end",
        "message_submit",
        "tool_call_before",
        "tool_call_after",
        "turn_end",
        "subagent_stop",
        "mode_change",
        "on_error",
        "shell_env",
    }
)


@dataclass
class HookContext:
    """Context passed to hooks via ``DEEPSEEK_*`` environment variables
    and as a JSON document on stdin (Claude Code hook protocol)."""

    tool_name: str | None = None
    tool_args: str | None = None
    tool_result: str | None = None
    tool_exit_code: int | None = None
    tool_success: bool | None = None
    mode: str | None = None
    previous_mode: str | None = None
    session_id: str | None = None
    message: str | None = None
    error_message: str | None = None
    workspace: Path | None = None
    model: str | None = None
    total_tokens: int | None = None
    session_cost: float | None = None
    # True when this turn's stop was already blocked once by a turn_end /
    # subagent_stop hook. Mirrors Claude Code's ``stop_hook_active`` so
    # hooks can avoid blocking forever.
    stop_hook_active: bool = False

    def to_stdin_payload(self, event: str, dialect: str = "native") -> dict[str, Any]:
        """Build the JSON document delivered on the hook's stdin.

        Mirrors the Claude Code hook input schema: common fields
        (``session_id`` / ``cwd`` / ``hook_event_name``) plus event-specific
        fields (``tool_name`` / ``tool_input`` / ``tool_response`` /
        ``prompt`` / ``stop_hook_active``). In the ``claude`` dialect tool
        and event names are translated to Claude Code spellings so
        community hook scripts (``jq '.tool_input.file_path'``,
        ``.tool_name == "Bash"``) work unmodified.
        """
        from deepseek_tui.integrations.plugin_compat import (
            to_claude_event_name,
            to_claude_tool_name,
        )

        claude = dialect == "claude"
        payload: dict[str, Any] = {
            "session_id": self.session_id or "",
            "cwd": str(self.workspace) if self.workspace else "",
            "hook_event_name": to_claude_event_name(event) if claude else event,
        }
        if self.tool_name:
            payload["tool_name"] = (
                to_claude_tool_name(self.tool_name) if claude else self.tool_name
            )
        if self.tool_args is not None:
            tool_input: Any
            try:
                tool_input = json.loads(self.tool_args)
            except (ValueError, TypeError):
                tool_input = self.tool_args
            payload["tool_input"] = tool_input
        if event == "tool_call_after":
            if self.tool_result is not None:
                payload["tool_response"] = _truncate(self.tool_result, 10_000)
            if self.tool_success is not None:
                payload["tool_success"] = self.tool_success
        if event == "message_submit" and self.message is not None:
            payload["prompt"] = self.message
        if event in ("turn_end", "subagent_stop"):
            payload["stop_hook_active"] = self.stop_hook_active
        return payload

    def to_env_vars(self) -> dict[str, str]:
        env: dict[str, str] = {}
        if self.tool_name:
            env["DEEPSEEK_TOOL_NAME"] = self.tool_name
        if self.tool_args:
            env["DEEPSEEK_TOOL_ARGS"] = self.tool_args
        if self.tool_result is not None:
            env["DEEPSEEK_TOOL_RESULT"] = _truncate(self.tool_result, 10_000)
        if self.tool_exit_code is not None:
            env["DEEPSEEK_TOOL_EXIT_CODE"] = str(self.tool_exit_code)
        if self.tool_success is not None:
            env["DEEPSEEK_TOOL_SUCCESS"] = str(self.tool_success).lower()
        if self.mode:
            env["DEEPSEEK_MODE"] = self.mode
        if self.previous_mode:
            env["DEEPSEEK_PREVIOUS_MODE"] = self.previous_mode
        if self.session_id:
            env["DEEPSEEK_SESSION_ID"] = self.session_id
        if self.message:
            env["DEEPSEEK_MESSAGE"] = _truncate(self.message, 5000)
        if self.error_message:
            env["DEEPSEEK_ERROR"] = self.error_message
        if self.workspace:
            env["DEEPSEEK_WORKSPACE"] = str(self.workspace)
        if self.model:
            env["DEEPSEEK_MODEL"] = self.model
        if self.total_tokens is not None:
            env["DEEPSEEK_TOTAL_TOKENS"] = str(self.total_tokens)
        if self.session_cost is not None:
            env["DEEPSEEK_SESSION_COST"] = f"{self.session_cost:.6f}"
        return env


@dataclass
class HookResult:
    name: str | None
    success: bool
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    error: str | None = None
    # ── Decision channel (Claude Code hook output protocol) ──
    # Exit code 2, stdout ``{"decision": "block"}`` or a PreToolUse
    # ``permissionDecision: deny`` all set ``blocked``. What blocking
    # *means* is decided by the engine call site per event.
    blocked: bool = False
    block_reason: str | None = None
    # PreToolUse only: "allow" | "deny" | "ask" from
    # ``hookSpecificOutput.permissionDecision``.
    permission_decision: str | None = None
    # Extra context to inject into the conversation (UserPromptSubmit /
    # SessionStart stdout, or ``hookSpecificOutput.additionalContext``).
    additional_context: str | None = None
    # ``systemMessage``: a warning to surface to the user.
    system_message: str | None = None


@dataclass
class HookDecision:
    """Aggregated decision across all hooks that ran for one event.

    Deny wins over ask wins over allow (mirrors Claude Code, which runs
    matching hooks in parallel and lets any deny block).
    """

    blocked: bool = False
    reason: str | None = None
    ask: bool = False
    additional_context: list[str] = field(default_factory=list)
    system_messages: list[str] = field(default_factory=list)


def aggregate_hook_decision(results: list[HookResult]) -> HookDecision:
    """Fold individual :class:`HookResult` decisions into one outcome."""
    decision = HookDecision()
    for result in results:
        if result.blocked and not decision.blocked:
            decision.blocked = True
            decision.reason = result.block_reason
        if result.permission_decision == "ask":
            decision.ask = True
        if result.additional_context:
            decision.additional_context.append(result.additional_context)
        if result.system_message:
            decision.system_messages.append(result.system_message)
    return decision


def _apply_output_semantics(event: str, result: HookResult) -> HookResult:
    """Interpret a finished hook's exit code and stdout per the Claude
    Code hook protocol.

    * exit 2 → blocking error; stderr is the reason, stdout is ignored.
    * other non-zero exits → non-blocking error (no decision).
    * exit 0 with a JSON object on stdout → structured decision:
      top-level ``decision: "block"`` + ``reason``, ``continue: false`` +
      ``stopReason``, ``systemMessage``, and ``hookSpecificOutput``
      (``permissionDecision`` / ``permissionDecisionReason`` /
      ``additionalContext``).
    * exit 0 with non-JSON stdout → for context-injecting events
      (message_submit / session_start) the raw stdout becomes
      ``additional_context``.
    """
    if result.exit_code == 2:
        result.blocked = True
        reason = result.stderr.strip()
        result.block_reason = reason or None
        return result
    if result.exit_code != 0:
        return result

    stdout = result.stdout.strip()
    if not stdout:
        return result
    document: Any = None
    try:
        document = json.loads(stdout)
    except ValueError:
        document = None
    if not isinstance(document, dict):
        if event in ("message_submit", "session_start"):
            result.additional_context = stdout
        return result

    if document.get("decision") == "block":
        result.blocked = True
        reason = document.get("reason")
        if isinstance(reason, str) and reason.strip():
            result.block_reason = reason.strip()
    if document.get("continue") is False:
        result.blocked = True
        stop_reason = document.get("stopReason")
        if isinstance(stop_reason, str) and stop_reason.strip():
            result.block_reason = stop_reason.strip()
    system_message = document.get("systemMessage")
    if isinstance(system_message, str) and system_message.strip():
        result.system_message = system_message.strip()

    specific = document.get("hookSpecificOutput")
    if isinstance(specific, dict):
        decision = specific.get("permissionDecision")
        if isinstance(decision, str) and decision.lower() in (
            "allow",
            "deny",
            "ask",
        ):
            result.permission_decision = decision.lower()
            if result.permission_decision == "deny":
                result.blocked = True
                reason = specific.get("permissionDecisionReason")
                if isinstance(reason, str) and reason.strip():
                    result.block_reason = reason.strip()
        context = specific.get("additionalContext")
        if isinstance(context, str) and context.strip():
            result.additional_context = context.strip()
    if result.additional_context is None:
        # Community hooks commonly emit a bare top-level additionalContext
        # (e.g. superpowers). Claude Code silently drops that shape — a
        # documented pain point — so we accept it as a fallback rather
        # than lose the context.
        context = document.get("additionalContext")
        if isinstance(context, str) and context.strip():
            result.additional_context = context.strip()
    return result


def parse_env_lines(stdout: str) -> dict[str, str]:
    """Parse ``KEY=VALUE`` lines from a ``shell_env`` hook stdout."""
    out: dict[str, str] = {}
    for raw in stdout.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:]
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        out[key] = value
    return out


def _tool_category(tool_name: str | None) -> str | None:
    if not tool_name:
        return None
    if tool_name == "exec_shell":
        return "shell"
    if tool_name in {"write_file", "edit_file"}:
        return "file_write"
    if tool_name in {"read_file", "list_dir", "grep_files"}:
        return "safe"
    return "other"


class HookExecutor:
    """Execute configured lifecycle shell hooks."""

    def __init__(
        self,
        config: HooksConfig,
        default_working_dir: Path,
        session_id: str | None = None,
    ) -> None:
        self.config = config
        self.default_working_dir = default_working_dir
        self.session_id = session_id or f"sess_{uuid.uuid4().hex[:8]}"
        # When set (scenario mode via ``@plugin:name``), only that plugin's
        # hooks run alongside user/config hooks (names without a ``plugin:``
        # prefix). Other plugins' hooks are skipped until the scenario exits.
        self.scenario_plugin: str | None = None

    @classmethod
    def from_config(cls, config: HooksConfig, workspace: Path) -> HookExecutor:
        merged = _merge_legacy_shell_hooks(config)
        return cls(merged, workspace.resolve())

    @classmethod
    def disabled(cls) -> HookExecutor:
        return cls(HooksConfig(enabled=False), Path.cwd(), session_id="")

    def is_enabled(self) -> bool:
        return self.config.enabled and bool(self.config.hooks)

    def has_hooks_for_event(self, event: str) -> bool:
        if not self.config.enabled:
            return False
        return any(
            h.event == event and self._hook_allowed_in_scenario(h)
            for h in self.config.hooks
        )

    def config_snapshot(self) -> HooksConfig:
        return self.config

    @staticmethod
    def _is_foreign_plugin_hook(hook: LifecycleHookEntry, active: str) -> bool:
        """True when ``hook`` belongs to a different plugin than ``active``."""
        owner = getattr(hook, "owner_plugin_id", None)
        if owner:
            return owner.lower() != active.lower()
        name = hook.name or ""
        if ":" not in name:
            return False  # user / config hooks have no plugin prefix
        prefix = name.split(":", 1)[0].lower()
        return prefix != active.lower()

    def _hook_allowed_in_scenario(self, hook: LifecycleHookEntry) -> bool:
        active = self.scenario_plugin
        if not active:
            return True
        return not self._is_foreign_plugin_hook(hook, active)

    async def execute(self, event: str, context: HookContext | None = None) -> list[HookResult]:
        if not self.config.enabled:
            return []
        hooks = [
            h
            for h in self.config.hooks
            if h.event == event and self._hook_allowed_in_scenario(h)
        ]
        if not hooks:
            return []
        ctx = context or HookContext(session_id=self.session_id)
        if ctx.session_id is None:
            ctx.session_id = self.session_id
        env_vars = ctx.to_env_vars()
        results: list[HookResult] = []
        for hook in hooks:
            if not self._matches_condition(hook, ctx):
                continue
            dialect = getattr(hook, "io_dialect", "native") or "native"
            stdin_data = json.dumps(
                ctx.to_stdin_payload(event, dialect)
            ).encode()
            hook_env = dict(env_vars)
            plugin_root = getattr(hook, "plugin_root", None)
            if plugin_root:
                # Claude Code exports these for plugin scripts (PYTHONPATH-style
                # imports via CLAUDE_PLUGIN_ROOT). Keep DEEPSEEK_WORKSPACE too.
                hook_env["CLAUDE_PLUGIN_ROOT"] = str(plugin_root)
                if ctx.workspace is not None:
                    hook_env["CLAUDE_PROJECT_DIR"] = str(ctx.workspace)
                elif "DEEPSEEK_WORKSPACE" in hook_env:
                    hook_env["CLAUDE_PROJECT_DIR"] = hook_env["DEEPSEEK_WORKSPACE"]
            if hook.background:
                result = await self._execute_background(hook, hook_env, stdin_data)
            else:
                result = await self._execute_sync(hook, hook_env, stdin_data)
                result = _apply_output_semantics(event, result)
            if not result.success and not result.blocked:
                label = result.name or "(unnamed)"
                logger.warning(
                    "lifecycle hook failed hook=%s event=%s exit_code=%s error=%s",
                    label,
                    event,
                    result.exit_code,
                    result.error or result.stderr[:200],
                )
            elif result.blocked:
                logger.info(
                    "lifecycle hook blocked hook=%s event=%s reason=%s",
                    result.name or "(unnamed)",
                    event,
                    (result.block_reason or "")[:200],
                )
            results.append(result)
            if not result.success and not result.blocked and not hook.continue_on_error:
                break
        return results

    async def collect_shell_env_async(self, context: HookContext) -> dict[str, str]:
        merged: dict[str, str] = {}
        for result in await self.execute("shell_env", context):
            if not result.success:
                continue
            merged.update(parse_env_lines(result.stdout))
        return merged

    def _working_dir(self) -> Path:
        if self.config.working_dir is not None:
            return self.config.working_dir.expanduser()
        return self.default_working_dir

    def _timeout(self, hook: LifecycleHookEntry) -> float:
        if self.config.default_timeout_secs is not None:
            return float(self.config.default_timeout_secs)
        return float(hook.timeout_secs)

    async def _execute_sync(
        self,
        hook: LifecycleHookEntry,
        env_vars: dict[str, str],
        stdin_data: bytes = b"",
    ) -> HookResult:
        timeout = self._timeout(hook)
        try:
            exit_code, stdout_b, stderr_b = await _run_shell(
                hook.command,
                timeout=timeout,
                stdin_data=stdin_data,
                cwd=str(self._working_dir()),
                env={**_base_env(), **env_vars},
            )
        except asyncio.TimeoutError:
            return HookResult(
                name=hook.name,
                success=False,
                error=f"Hook timed out after {timeout}s",
            )
        except OSError as exc:
            return HookResult(
                name=hook.name,
                success=False,
                error=f"Failed to spawn hook: {exc}",
            )
        return HookResult(
            name=hook.name,
            success=exit_code == 0,
            exit_code=exit_code,
            stdout=stdout_b.decode(errors="replace"),
            stderr=stderr_b.decode(errors="replace"),
        )

    async def _execute_background(
        self,
        hook: LifecycleHookEntry,
        env_vars: dict[str, str],
        stdin_data: bytes = b"",
    ) -> HookResult:
        asyncio.create_task(
            self._run_background_hook(hook, env_vars, stdin_data),
            name=f"hook-bg-{hook.name or hook.event}",
        )
        return HookResult(name=hook.name, success=True)

    async def _run_background_hook(
        self,
        hook: LifecycleHookEntry,
        env_vars: dict[str, str],
        stdin_data: bytes = b"",
    ) -> None:
        # 这个 task 没人持有引用，后续在优化
        try:
            await _run_shell(
                hook.command,
                timeout=self._timeout(hook),
                stdin_data=stdin_data,
                cwd=str(self._working_dir()),
                env={**_base_env(), **env_vars},
                devnull_output=True,
            )
        except Exception:
            logger.warning(
                "background lifecycle hook failed hook=%s event=%s",
                hook.name or "(unnamed)",
                hook.event,
                exc_info=True,
            )

    def _matches_condition(self, hook: LifecycleHookEntry, ctx: HookContext) -> bool:
        cond = hook.condition
        if not cond:
            return True
        ctype = cond.get("type", "always")
        if ctype in ("always", ""):
            return True
        if ctype == "tool_name":
            return ctx.tool_name == cond.get("name")
        if ctype == "tool_name_any":
            names = cond.get("names") or []
            return ctx.tool_name in names
        if ctype == "tool_category":
            return _tool_category(ctx.tool_name) == cond.get("category")
        if ctype == "mode":
            return (ctx.mode or "").lower() == str(cond.get("mode", "")).lower()
        if ctype == "exit_code":
            return ctx.tool_exit_code == cond.get("code")
        if ctype == "all":
            nested = cond.get("conditions") or []
            return all(
                self._matches_condition(
                    LifecycleHookEntry(event=hook.event, command=hook.command, condition=n),
                    ctx,
                )
                for n in nested
                if isinstance(n, dict)
            )
        if ctype == "any":
            nested = cond.get("conditions") or []
            return any(
                self._matches_condition(
                    LifecycleHookEntry(event=hook.event, command=hook.command, condition=n),
                    ctx,
                )
                for n in nested
                if isinstance(n, dict)
            )
        return True


def _base_env() -> dict[str, str]:
    import os

    return dict(os.environ)


def _merge_legacy_shell_hooks(config: HooksConfig) -> HooksConfig:
    if not config.shell_hooks:
        return config
    entries = list(config.hooks)
    for sh in config.shell_hooks:
        entries.append(
            LifecycleHookEntry(
                event=sh.event,
                command=sh.command,
                name=sh.name,
                timeout_secs=sh.timeout_secs,
            )
        )
    return config.model_copy(update={"hooks": entries})


# ======================================================================
# From build.py
# ======================================================================

"""Construct a :class:`HookDispatcher` from application config."""



from deepseek_tui.config.models import Config


def build_hook_dispatcher(config: Config) -> HookDispatcher:
    """Wire stdout / JSONL / webhook / shell sinks from ``config.hooks``."""
    dispatcher = HookDispatcher()
    hooks_cfg = config.hooks
    if hooks_cfg.stdout:
        dispatcher.add_sink(StdoutHookSink())
    if hooks_cfg.jsonl_path is not None:
        dispatcher.add_sink(JsonlHookSink(hooks_cfg.jsonl_path.expanduser()))
    for url in hooks_cfg.webhook_urls:
        if url.strip():
            dispatcher.add_sink(WebhookHookSink(url))
    for sh in hooks_cfg.shell_hooks:
        dispatcher.add_sink(
            ShellHookSink(
                event_filter=sh.event,
                command=sh.command,
                timeout=sh.timeout_secs,
            )
        )
    return dispatcher


def build_lifecycle_hook_executor(config: Config, workspace: Path | None = None) -> HookExecutor:
    """Construct a lifecycle :class:`HookExecutor` from ``config.hooks``."""
    ws = (workspace or Path.cwd()).resolve()
    return HookExecutor.from_config(config.hooks, ws)
