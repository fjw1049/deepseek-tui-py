from __future__ import annotations

import asyncio
import logging
import os
import pty
import shlex
import uuid
from asyncio.subprocess import Process
from pathlib import Path
from typing import Any

from deepseek_tui.execpolicy.command_safety import SafetyLevel, analyze_command
from deepseek_tui.execpolicy.decision import Decision
from deepseek_tui.execpolicy.sandbox import (
    CommandSpec,
    ExecEnv,
    ExecutionSandboxPolicy,
    SANDBOX_MANAGER,
    apply_sandbox_metadata,
)
from deepseek_tui.tools._validators import require_string as _require_string
from deepseek_tui.tools.base import ToolCapability, ToolError, ToolResult, ToolSpec
from deepseek_tui.tools.context import ToolContext

logger = logging.getLogger(__name__)

_PROCESS_STORE_KEY = "shell_processes"
_PTY_STORE_KEY = "shell_pty_processes"
_EXEC_ENV_STORE_KEY = "shell_exec_envs"
_MAX_STORED_PROCESSES = 20


# Default + max foreground timeouts mirror Rust shell.rs:1481-1482.
EXEC_DEFAULT_TIMEOUT_MS = 120_000
EXEC_MAX_TIMEOUT_MS = 600_000


class ExecShellTool(ToolSpec):
    def name(self) -> str:
        return "exec_shell"

    def description(self) -> str:
        return (
            "Execute a shell command. Supports background jobs (background=true) "
            "and an optional pseudo-TTY (pty=true) for interactive programs. "
            "Foreground commands are killed after timeout_ms milliseconds "
            "(default 120000, max 600000)."
        )

    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "background": {"type": "boolean"},
                "pty": {"type": "boolean"},
                "timeout_ms": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": EXEC_MAX_TIMEOUT_MS,
                    "description": (
                        f"Foreground timeout in milliseconds. "
                        f"Default {EXEC_DEFAULT_TIMEOUT_MS}, max {EXEC_MAX_TIMEOUT_MS}."
                    ),
                },
            },
            "required": ["command"],
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.EXECUTES_CODE, ToolCapability.SANDBOXABLE]

    async def execute(self, input_data: dict[str, object], context: ToolContext) -> ToolResult:
        command = _require_string(input_data, "command")
        background = bool(input_data.get("background", False))
        use_pty = bool(input_data.get("pty", False))
        timeout_ms = _resolve_timeout_ms(input_data.get("timeout_ms"))
        logger.info(
            "exec_shell_start command=%r background=%s pty=%s timeout_ms=%d cwd=%s",
            command[:200],
            background,
            use_pty,
            timeout_ms,
            context.working_directory,
        )

        # Check command execution policy
        if context.policy:
            cmd_tokens = _parse_command_tokens(command)
            evaluation = context.policy.check(
                cmd_tokens,
                _command_safety_heuristic,
            )
            if evaluation.decision == Decision.FORBIDDEN:
                raise ToolError(
                    f"Command execution forbidden by policy: {command}"
                )
            elif evaluation.decision == Decision.PROMPT:
                return ToolResult(
                    success=False,
                    content=(
                        f"Command requires user approval before execution: {command}\n"
                        "The command was flagged by the safety policy. "
                        "Ask the user to approve or use a safer alternative."
                    ),
                )

        if use_pty:
            return await _run_pty(
                command,
                cwd=str(context.working_directory),
                background=background,
                context=context,
                timeout_ms=timeout_ms,
            )

        shell_env = await _shell_env_from_hooks(context, command)
        policy = _resolve_policy(context)
        exec_env = _prepare_shell_exec(
            command,
            context.working_directory,
            policy,
            shell_env,
            timeout_ms,
        )
        process = await _spawn_from_exec_env(exec_env)
        if background:
            process_id = str(uuid.uuid4())
            _process_store(context)[process_id] = process
            _exec_env_store(context)[process_id] = exec_env
            metadata: dict[str, Any] = {
                "background": True,
                "pid": process.pid,
                "pty": False,
                "sandboxed": exec_env.is_sandboxed(),
                "sandbox_type": exec_env.sandbox_type.value,
            }
            return ToolResult(
                success=True,
                content=process_id,
                metadata=metadata,
            )

        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=timeout_ms / 1000.0
            )
        except asyncio.TimeoutError:
            logger.warning(
                "exec_shell_timeout command=%r timeout_ms=%d pid=%s",
                command[:100],
                timeout_ms,
                process.pid,
            )
            # Kill so we don't leak a zombie when the model fires off a
            # runaway command. Best-effort terminate first to give Python
            # signal handlers a chance, then fall back to kill.
            try:
                process.terminate()
                await asyncio.wait_for(process.wait(), timeout=1.0)
            except (ProcessLookupError, asyncio.TimeoutError):
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
            return ToolResult(
                success=False,
                content=(
                    f"Command timed out after {timeout_ms} ms and was killed: "
                    f"{command}\n\n"
                    "For long-running work, use task_shell_start + task_shell_wait "
                    "on a durable task instead of foreground exec_shell."
                ),
                metadata={
                    "timed_out": True,
                    "timeout_ms": timeout_ms,
                    "returncode": process.returncode,
                    "job_hint": "task_shell_start",
                },
            )
        logger.info(
            "exec_shell_end command=%r returncode=%s stdout_bytes=%d stderr_bytes=%d",
            command[:100],
            process.returncode,
            len(stdout) if stdout else 0,
            len(stderr) if stderr else 0,
        )
        return _build_shell_result(
            process,
            stdout,
            stderr,
            exec_env=exec_env,
            command=command,
            policy=policy,
        )


def _resolve_timeout_ms(raw: object) -> int:
    """Validate timeout_ms argument; clamp to [1, EXEC_MAX_TIMEOUT_MS]."""
    if raw is None:
        return EXEC_DEFAULT_TIMEOUT_MS
    if not isinstance(raw, int) or isinstance(raw, bool):
        raise ToolError("timeout_ms must be an integer (milliseconds)")
    if raw < 1:
        raise ToolError("timeout_ms must be >= 1")
    if raw > EXEC_MAX_TIMEOUT_MS:
        raise ToolError(f"timeout_ms must be <= {EXEC_MAX_TIMEOUT_MS}")
    return raw


class ExecShellWaitTool(ToolSpec):
    def name(self) -> str:
        return "exec_shell_wait"

    def description(self) -> str:
        return "Wait for a background shell command to finish and collect output."

    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {"process_id": {"type": "string"}},
            "required": ["process_id"],
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.EXECUTES_CODE, ToolCapability.SANDBOXABLE]

    async def execute(self, input_data: dict[str, object], context: ToolContext) -> ToolResult:
        process_id = _require_string(input_data, "process_id")
        pty_proc = _pop_pty(context, process_id)
        if pty_proc is not None:
            await pty_proc.wait()
            text = pty_proc.output.decode("utf-8", errors="replace")
            exec_env = _pop_exec_env(context, process_id)
            metadata: dict[str, Any] = {
                "returncode": pty_proc.exit_code,
                "stdout": text,
                "stderr": "",
                "status": "completed",
                "process_id": process_id,
                "pty": True,
            }
            if exec_env is not None:
                apply_sandbox_metadata(
                    metadata,
                    exec_env=exec_env,
                    exit_code=pty_proc.exit_code if pty_proc.exit_code is not None else 1,
                    stderr=text,
                )
            return ToolResult(
                success=pty_proc.exit_code == 0,
                content=text.strip(),
                metadata=metadata,
            )
        process = _pop_process(context, process_id)
        exec_env = _pop_exec_env(context, process_id)
        stdout, stderr = await process.communicate()
        return _build_shell_result(
            process,
            stdout,
            stderr,
            extra_metadata={"process_id": process_id},
            exec_env=exec_env,
        )


class ExecShellInteractTool(ToolSpec):
    def name(self) -> str:
        return "exec_shell_interact"

    def description(self) -> str:
        return "Send input to a background shell command."

    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {
                "process_id": {"type": "string"},
                "input": {"type": "string"},
                "close_stdin": {"type": "boolean"},
            },
            "required": ["process_id", "input"],
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.EXECUTES_CODE, ToolCapability.SANDBOXABLE]

    async def execute(self, input_data: dict[str, object], context: ToolContext) -> ToolResult:
        process_id = _require_string(input_data, "process_id")
        data = _require_string(input_data, "input")
        close_stdin = bool(input_data.get("close_stdin", False))

        pty_proc = _get_pty(context, process_id)
        if pty_proc is not None:
            if pty_proc.done:
                raise ToolError(f"Process already finished: {process_id}")
            payload = data.encode("utf-8")
            await pty_proc.write(payload)
            if close_stdin:
                # Best-effort: closing master_fd signals EOF to child.
                pty_proc._close_master()  # noqa: SLF001
            return ToolResult(
                success=True,
                content="sent",
                metadata={
                    "process_id": process_id,
                    "close_stdin": close_stdin,
                    "pty": True,
                },
            )

        process = _get_process(context, process_id)
        stdin = process.stdin
        if stdin is None or stdin.is_closing():
            raise ToolError(f"Process stdin is not available for process_id: {process_id}")

        stdin.write(data.encode("utf-8"))
        await stdin.drain()
        if close_stdin:
            stdin.close()
            await stdin.wait_closed()

        return ToolResult(
            success=True,
            content="sent",
            metadata={"process_id": process_id, "close_stdin": close_stdin},
        )


class ExecShellCancelTool(ToolSpec):
    def name(self) -> str:
        return "exec_shell_cancel"

    def description(self) -> str:
        return "Cancel a background shell command."

    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {"process_id": {"type": "string"}},
            "required": ["process_id"],
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.EXECUTES_CODE, ToolCapability.SANDBOXABLE]

    async def execute(self, input_data: dict[str, object], context: ToolContext) -> ToolResult:
        process_id = _require_string(input_data, "process_id")
        pty_proc = _pop_pty(context, process_id)
        if pty_proc is not None:
            pty_proc.kill()
            await pty_proc.wait()
            text = pty_proc.output.decode("utf-8", errors="replace")
            return ToolResult(
                success=True,
                content="cancelled",
                metadata={
                    "process_id": process_id,
                    "returncode": pty_proc.exit_code,
                    "stdout": text,
                    "stderr": "",
                    "status": "cancelled",
                    "pty": True,
                },
            )
        process = _pop_process(context, process_id)
        process.terminate()
        stdout, stderr = await process.communicate()
        return ToolResult(
            success=True,
            content="cancelled",
            metadata={
                "process_id": process_id,
                "returncode": process.returncode,
                "stdout": _decode_stream(stdout),
                "stderr": _decode_stream(stderr),
                "status": "cancelled",
            },
        )


def _process_store(context: ToolContext) -> dict[str, Process]:
    store = context.metadata.get(_PROCESS_STORE_KEY)
    if store is None:
        store = {}
        context.metadata[_PROCESS_STORE_KEY] = store
    if not isinstance(store, dict):
        raise ToolError("shell process store is invalid")
    if len(store) > _MAX_STORED_PROCESSES:
        terminated = [
            pid for pid, proc in store.items()
            if proc.returncode is not None
        ]
        for pid in terminated:
            del store[pid]
    return store


def _get_process(context: ToolContext, process_id: str) -> Process:
    store = _process_store(context)
    process = store.get(process_id)
    if process is None:
        raise ToolError(f"Unknown process_id: {process_id}")
    return process


def _pop_process(context: ToolContext, process_id: str) -> Process:
    process = _get_process(context, process_id)
    _process_store(context).pop(process_id, None)
    return process




def _decode_stream(stream: bytes | None) -> str:
    # errors="replace": binary output (e.g. `cat image.png`) must surface as
    # a tool result, not an engine-level UnicodeDecodeError. Matches the PTY
    # path, which already decodes with replacement.
    return stream.decode("utf-8", errors="replace") if stream else ""


def _decode_output(stdout: bytes | None, stderr: bytes | None) -> str:
    return (_decode_stream(stdout) + _decode_stream(stderr)).strip()


def _build_shell_result(
    process: Process,
    stdout: bytes | None,
    stderr: bytes | None,
    *,
    extra_metadata: dict[str, Any] | None = None,
    exec_env: ExecEnv | None = None,
    command: str | None = None,
    policy: ExecutionSandboxPolicy | None = None,
) -> ToolResult:
    stdout_text = _decode_stream(stdout)
    stderr_text = _decode_stream(stderr)
    metadata: dict[str, Any] = {
        "returncode": process.returncode,
        "stdout": stdout_text,
        "stderr": stderr_text,
        "status": "completed",
    }
    if extra_metadata:
        metadata.update(extra_metadata)
    if exec_env is not None:
        apply_sandbox_metadata(
            metadata,
            exec_env=exec_env,
            exit_code=process.returncode,
            stderr=stderr_text,
        )
    content = _decode_output(stdout, stderr)
    if (
        exec_env is not None
        and policy is not None
        and metadata.get("sandbox_denied")
        and not policy.has_network_access()
        and command
        and _command_likely_needs_network(command)
    ):
        content = (
            f"{content}\n\nNetwork may be blocked by the sandbox policy."
        ).strip()
    elif (
        exec_env is not None
        and policy is not None
        and not policy.has_network_access()
        and command
        and _command_likely_needs_network(command)
        and _looks_like_network_blocked_failure(stdout_text, stderr_text)
    ):
        content = (
            f"{content}\n\nNetwork may be blocked by the sandbox policy."
        ).strip()
    return ToolResult(
        success=process.returncode == 0,
        content=content,
        metadata=metadata,
    )


def _parse_command_tokens(command: str) -> list[str]:
    """Parse shell command string into token list for policy matching."""
    try:
        return shlex.split(command)
    except ValueError:
        return [command]


def _command_safety_heuristic(tokens: list[str]) -> Decision:
    """Map command_safety analysis to Policy Decision.

    Used as the heuristics fallback when no prefix-rule matches.
    Mirrors the Rust command_safety → Policy::check integration.
    """
    cmd_str = " ".join(tokens)
    analysis = analyze_command(cmd_str)
    if analysis.level in (SafetyLevel.SAFE, SafetyLevel.WORKSPACE_SAFE):
        return Decision.ALLOW
    if analysis.level == SafetyLevel.REQUIRES_APPROVAL:
        return Decision.PROMPT
    return Decision.FORBIDDEN


# --- PTY support -----------------------------------------------------------


class PtyProcess:
    """Handle for a pty-backed background command.

    Mirrors Rust ``BackgroundShell::Pty`` (shell.rs:119-). Wraps a process
    id plus a master fd for stdin / stdout multiplex.
    """

    __slots__ = ("pid", "master_fd", "_exit_code", "_done", "_output", "_reader_task")

    def __init__(self, pid: int, master_fd: int) -> None:
        self.pid = pid
        self.master_fd = master_fd
        self._exit_code: int | None = None
        self._done = asyncio.Event()
        self._output = bytearray()
        self._reader_task: asyncio.Task[None] | None = None

    def start_reader(self) -> None:
        if self._reader_task is None:
            self._reader_task = asyncio.create_task(self._reader_loop())

    async def _reader_loop(self) -> None:
        loop = asyncio.get_running_loop()
        while True:
            try:
                data = await loop.run_in_executor(
                    None, lambda: _safe_read(self.master_fd, 4096)
                )
            except OSError:
                break
            if not data:
                break
            self._output.extend(data)
        self._close_master()
        # Wait for process exit to record status.
        try:
            pid, status = await loop.run_in_executor(
                None, lambda: os.waitpid(self.pid, 0)
            )
        except ChildProcessError:
            self._exit_code = None
        else:
            if os.WIFEXITED(status):
                self._exit_code = os.WEXITSTATUS(status)
            elif os.WIFSIGNALED(status):
                self._exit_code = -os.WTERMSIG(status)
            else:
                self._exit_code = None
        self._done.set()

    def _close_master(self) -> None:
        try:
            os.close(self.master_fd)
        except OSError:
            pass

    async def wait(self) -> None:
        await self._done.wait()

    async def write(self, data: bytes) -> None:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, lambda: os.write(self.master_fd, data))

    def kill(self) -> None:
        try:
            os.kill(self.pid, 15)
        except ProcessLookupError:
            pass

    @property
    def exit_code(self) -> int | None:
        return self._exit_code

    @property
    def output(self) -> bytes:
        return bytes(self._output)

    @property
    def done(self) -> bool:
        return self._done.is_set()


def _safe_read(fd: int, n: int) -> bytes:
    try:
        return os.read(fd, n)
    except OSError:
        return b""


async def _run_pty(
    command: str,
    *,
    cwd: str,
    background: bool,
    context: ToolContext,
    timeout_ms: int = EXEC_DEFAULT_TIMEOUT_MS,
) -> ToolResult:
    shell_env = await _shell_env_from_hooks(context, command)
    policy = _resolve_policy(context)
    exec_env = _prepare_shell_exec(
        command,
        Path(cwd),
        policy,
        shell_env,
        timeout_ms,
    )
    master_fd, slave_fd = pty.openpty()
    pid = os.fork()
    if pid == 0:
        # Child: wire slave_fd to std{in,out,err}, then exec sandboxed shell.
        try:
            os.close(master_fd)
            os.setsid()
            os.dup2(slave_fd, 0)
            os.dup2(slave_fd, 1)
            os.dup2(slave_fd, 2)
            if slave_fd > 2:
                os.close(slave_fd)
            os.chdir(cwd)
            merged_env = {**os.environ, **exec_env.env}
            for key, value in merged_env.items():
                os.environ[key] = value
            os.execvp(exec_env.command[0], exec_env.command)
        except Exception:
            os._exit(127)

    # Parent.
    os.close(slave_fd)
    proc = PtyProcess(pid=pid, master_fd=master_fd)
    proc.start_reader()

    if background:
        process_id = str(uuid.uuid4())
        _pty_store(context)[process_id] = proc
        _exec_env_store(context)[process_id] = exec_env
        return ToolResult(
            success=True,
            content=process_id,
            metadata={
                "background": True,
                "pid": pid,
                "pty": True,
                "sandboxed": exec_env.is_sandboxed(),
                "sandbox_type": exec_env.sandbox_type.value,
            },
        )

    # Foreground PTY commands get the same timeout as the non-PTY path;
    # an `await proc.wait()` with no bound could hang the tool round forever.
    timed_out = False
    try:
        await asyncio.wait_for(proc.wait(), timeout=timeout_ms / 1000)
    except asyncio.TimeoutError:
        timed_out = True
        proc.kill()
        try:
            await asyncio.wait_for(proc.wait(), timeout=5)
        except asyncio.TimeoutError:
            try:
                os.kill(proc.pid, 9)
            except ProcessLookupError:
                pass
    text = proc.output.decode("utf-8", errors="replace")
    if timed_out:
        return ToolResult(
            success=False,
            content=(
                f"Command timed out after {timeout_ms}ms (pty)."
                + (f"\nPartial output:\n{text.strip()}" if text.strip() else "")
            ),
            metadata={
                "returncode": proc.exit_code,
                "stdout": text,
                "stderr": "",
                "status": "timeout",
                "pty": True,
            },
        )
    metadata: dict[str, Any] = {
        "returncode": proc.exit_code,
        "stdout": text,
        "stderr": "",
        "status": "completed",
        "pty": True,
    }
    apply_sandbox_metadata(
        metadata,
        exec_env=exec_env,
        exit_code=proc.exit_code if proc.exit_code is not None else 1,
        stderr=text,
    )
    return ToolResult(
        success=proc.exit_code == 0,
        content=text.strip(),
        metadata=metadata,
    )


async def _shell_env_from_hooks(context: ToolContext, command: str) -> dict[str, str] | None:
    """Merge ``shell_env`` lifecycle hook output into the subprocess environment."""
    import os

    from deepseek_tui.hooks.executor import HookContext, HookExecutor

    executor = context.metadata.get("hook_executor")
    if not isinstance(executor, HookExecutor) or not executor.has_hooks_for_event("shell_env"):
        return None
    hook_ctx = HookContext(
        tool_name="exec_shell",
        tool_args=command,
        workspace=context.working_directory,
        session_id=executor.session_id,
    )
    extra = await executor.collect_shell_env_async(hook_ctx)
    if not extra:
        return None
    return {**os.environ, **extra}


def _pty_store(context: ToolContext) -> dict[str, PtyProcess]:
    store = context.metadata.get(_PTY_STORE_KEY)
    if store is None:
        store = {}
        context.metadata[_PTY_STORE_KEY] = store
    if not isinstance(store, dict):
        raise ToolError("shell pty store is invalid")
    if len(store) > _MAX_STORED_PROCESSES:
        terminated = [
            pid for pid, proc in store.items()
            if proc.exit_code is not None
        ]
        for pid in terminated:
            del store[pid]
    return store


def _get_pty(context: ToolContext, process_id: str) -> PtyProcess | None:
    return _pty_store(context).get(process_id)


def _pop_pty(context: ToolContext, process_id: str) -> PtyProcess | None:
    store = _pty_store(context)
    return store.pop(process_id, None)


def _exec_env_store(context: ToolContext) -> dict[str, ExecEnv]:
    store = context.metadata.get(_EXEC_ENV_STORE_KEY)
    if store is None:
        store = {}
        context.metadata[_EXEC_ENV_STORE_KEY] = store
    if not isinstance(store, dict):
        raise ToolError("shell exec env store is invalid")
    return store


def _pop_exec_env(context: ToolContext, process_id: str) -> ExecEnv | None:
    return _exec_env_store(context).pop(process_id, None)


def _resolve_policy(
    context: ToolContext,
    override: ExecutionSandboxPolicy | None = None,
) -> ExecutionSandboxPolicy:
    if override is not None:
        return override
    if context.elevated_sandbox_policy is not None:
        return context.elevated_sandbox_policy
    if context.execution_sandbox_policy is not None:
        return context.execution_sandbox_policy
    from deepseek_tui.execpolicy.sandbox import sandbox_policy_for_mode

    return sandbox_policy_for_mode("agent", context.working_directory)


def _prepare_shell_exec(
    command: str,
    cwd: Path,
    policy: ExecutionSandboxPolicy,
    env: dict[str, str] | None,
    timeout_ms: int,
) -> ExecEnv:
    spec = CommandSpec.shell(command, cwd, timeout_ms).with_policy(policy)
    if env:
        spec = spec.with_env(env)
    return SANDBOX_MANAGER.prepare(spec)


async def _spawn_from_exec_env(exec_env: ExecEnv) -> Process:
    merged_env = {**os.environ, **exec_env.env}
    return await asyncio.create_subprocess_exec(
        exec_env.program(),
        *exec_env.args(),
        cwd=str(exec_env.cwd),
        env=merged_env,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )


def _extract_primary_command(command: str) -> str | None:
    normalized = command.strip()
    if not normalized:
        return None
    for separator in ("&&", "||", ";", "|"):
        if separator in normalized:
            normalized = normalized.split(separator, 1)[0].strip()
    return normalized.split(None, 1)[0] if normalized else None


def _command_likely_needs_network(command: str) -> bool:
    normalized = command.lower()
    primary = _extract_primary_command(normalized)
    if not primary:
        return False
    primary = primary.rsplit("/", 1)[-1]
    if primary in {
        "curl",
        "wget",
        "fetch",
        "nc",
        "netcat",
        "ncat",
        "ssh",
        "scp",
        "sftp",
        "rsync",
        "ftp",
        "ping",
        "traceroute",
        "nslookup",
        "dig",
        "host",
        "nmap",
        "gh",
        "hub",
    }:
        return True
    if primary == "git":
        return any(
            needle in normalized
            for needle in (
                " fetch",
                " pull",
                " clone",
                " ls-remote",
                " submodule",
                " push",
            )
        )
    if primary == "cargo":
        return any(
            needle in normalized
            for needle in (" install", " fetch", " update", " publish", " search")
        )
    if primary in {"npm", "pnpm", "yarn"}:
        return any(
            needle in normalized
            for needle in (" install", " i", " add", " update", " publish")
        )
    return False


def _looks_like_network_blocked_failure(stdout: str, stderr: str) -> bool:
    output = f"{stdout}\n{stderr}".lower()
    patterns = (
        "could not resolve host",
        "failed to resolve",
        "temporary failure in name resolution",
        "name or service not known",
        "nodename nor servname provided",
        "no address associated",
        "failed to connect",
        "couldn't connect",
        "connection timed out",
        "connection reset",
    )
    return any(pattern in output for pattern in patterns)
