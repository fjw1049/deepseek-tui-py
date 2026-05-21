"""Lifecycle hook executor — mirrors ``crates/tui/src/hooks.rs``.

User-defined shell commands from ``[[hooks.hooks]]`` in config.toml, triggered
at session/tool/mode/message/error/shell_env lifecycle points.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from deepseek_tui.config.models import HooksConfig, LifecycleHookEntry, ShellHookConfig

logger = logging.getLogger(__name__)

LIFECYCLE_EVENTS = frozenset(
    {
        "session_start",
        "session_end",
        "message_submit",
        "tool_call_before",
        "tool_call_after",
        "mode_change",
        "on_error",
        "shell_env",
    }
)


@dataclass
class HookContext:
    """Context passed to hooks via ``DEEPSEEK_*`` environment variables."""

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

    def to_env_vars(self) -> dict[str, str]:
        env: dict[str, str] = {}
        if self.tool_name:
            env["DEEPSEEK_TOOL_NAME"] = self.tool_name
        if self.tool_args:
            env["DEEPSEEK_TOOL_ARGS"] = self.tool_args
        if self.tool_result is not None:
            truncated = self.tool_result
            if len(truncated) > 10_000:
                truncated = truncated[:10_000] + "...[truncated]"
            env["DEEPSEEK_TOOL_RESULT"] = truncated
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
            msg = self.message
            if len(msg) > 5000:
                msg = msg[:5000] + "...[truncated]"
            env["DEEPSEEK_MESSAGE"] = msg
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
    if tool_name in {"write_file", "edit_file", "apply_patch"}:
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
        return any(h.event == event for h in self.config.hooks)

    def config_snapshot(self) -> HooksConfig:
        return self.config

    async def execute(self, event: str, context: HookContext | None = None) -> list[HookResult]:
        if not self.config.enabled:
            return []
        hooks = [h for h in self.config.hooks if h.event == event]
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
            if hook.background:
                result = await self._execute_background(hook, env_vars)
            else:
                result = await self._execute_sync(hook, env_vars)
            if not result.success:
                label = result.name or "(unnamed)"
                logger.warning(
                    "lifecycle hook failed hook=%s event=%s exit_code=%s error=%s",
                    label,
                    event,
                    result.exit_code,
                    result.error or result.stderr[:200],
                )
            results.append(result)
            if not result.success and not hook.continue_on_error:
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
        self, hook: LifecycleHookEntry, env_vars: dict[str, str]
    ) -> HookResult:
        timeout = self._timeout(hook)
        cwd = str(self._working_dir())
        try:
            proc = await asyncio.create_subprocess_shell(
                hook.command,
                cwd=cwd,
                env={**_base_env(), **env_vars},
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_b, stderr_b = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
        except asyncio.TimeoutError:
            proc.kill()  # type: ignore[union-attr]
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
        exit_code = proc.returncode
        return HookResult(
            name=hook.name,
            success=exit_code == 0,
            exit_code=exit_code,
            stdout=stdout_b.decode(errors="replace"),
            stderr=stderr_b.decode(errors="replace"),
        )

    async def _execute_background(
        self, hook: LifecycleHookEntry, env_vars: dict[str, str]
    ) -> HookResult:
        cwd = str(self._working_dir())
        asyncio.create_task(
            asyncio.create_subprocess_shell(
                hook.command,
                cwd=cwd,
                env={**_base_env(), **env_vars},
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
        )
        return HookResult(name=hook.name, success=True)

    def _matches_condition(self, hook: LifecycleHookEntry, ctx: HookContext) -> bool:
        cond = hook.condition
        if not cond:
            return True
        ctype = cond.get("type", "always")
        if ctype in ("always", ""):
            return True
        if ctype == "tool_name":
            return ctx.tool_name == cond.get("name")
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
