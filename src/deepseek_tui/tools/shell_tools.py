from __future__ import annotations

import asyncio
import os
import pty
import shlex
import uuid
from asyncio.subprocess import Process
from typing import Any

from deepseek_tui.execpolicy.command_safety import SafetyLevel, analyze_command
from deepseek_tui.execpolicy.decision import Decision
from deepseek_tui.tools.base import ToolCapability, ToolError, ToolResult, ToolSpec
from deepseek_tui.tools.context import ToolContext

_PROCESS_STORE_KEY = "shell_processes"
_PTY_STORE_KEY = "shell_pty_processes"


class ExecShellTool(ToolSpec):
    def name(self) -> str:
        return "exec_shell"

    def description(self) -> str:
        return (
            "Execute a shell command. Supports background jobs and an "
            "optional pseudo-TTY (pty=true) for interactive programs."
        )

    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "background": {"type": "boolean"},
                "pty": {"type": "boolean"},
            },
            "required": ["command"],
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.EXECUTES_CODE, ToolCapability.SANDBOXABLE]

    async def execute(self, input_data: dict[str, object], context: ToolContext) -> ToolResult:
        command = _require_string(input_data, "command")
        background = bool(input_data.get("background", False))
        use_pty = bool(input_data.get("pty", False))

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
                command, cwd=str(context.working_directory), background=background,
                context=context,
            )

        process = await asyncio.create_subprocess_shell(
            command,
            cwd=str(context.working_directory),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        if background:
            process_id = str(uuid.uuid4())
            _process_store(context)[process_id] = process
            return ToolResult(
                success=True,
                content=process_id,
                metadata={"background": True, "pid": process.pid, "pty": False},
            )

        stdout, stderr = await process.communicate()
        return _build_shell_result(process, stdout, stderr)


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
            return ToolResult(
                success=pty_proc.exit_code == 0,
                content=text.strip(),
                metadata={
                    "returncode": pty_proc.exit_code,
                    "stdout": text,
                    "stderr": "",
                    "status": "completed",
                    "process_id": process_id,
                    "pty": True,
                },
            )
        process = _pop_process(context, process_id)
        stdout, stderr = await process.communicate()
        return _build_shell_result(
            process,
            stdout,
            stderr,
            extra_metadata={"process_id": process_id},
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


def _require_string(input_data: dict[str, object], key: str) -> str:
    value = input_data.get(key)
    if not isinstance(value, str):
        raise ToolError(f"{key} must be a string")
    return value


def _decode_stream(stream: bytes | None) -> str:
    return stream.decode("utf-8") if stream else ""


def _decode_output(stdout: bytes | None, stderr: bytes | None) -> str:
    return (_decode_stream(stdout) + _decode_stream(stderr)).strip()


def _build_shell_result(
    process: Process,
    stdout: bytes | None,
    stderr: bytes | None,
    *,
    extra_metadata: dict[str, Any] | None = None,
) -> ToolResult:
    metadata: dict[str, Any] = {
        "returncode": process.returncode,
        "stdout": _decode_stream(stdout),
        "stderr": _decode_stream(stderr),
        "status": "completed",
    }
    if extra_metadata:
        metadata.update(extra_metadata)
    return ToolResult(
        success=process.returncode == 0,
        content=_decode_output(stdout, stderr),
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
    command: str, *, cwd: str, background: bool, context: ToolContext
) -> ToolResult:
    master_fd, slave_fd = pty.openpty()
    pid = os.fork()
    if pid == 0:
        # Child: wire slave_fd to std{in,out,err}, then exec shell.
        try:
            os.close(master_fd)
            os.setsid()
            os.dup2(slave_fd, 0)
            os.dup2(slave_fd, 1)
            os.dup2(slave_fd, 2)
            if slave_fd > 2:
                os.close(slave_fd)
            os.chdir(cwd)
            os.execvp("sh", ["sh", "-c", command])
        except Exception:
            os._exit(127)

    # Parent.
    os.close(slave_fd)
    proc = PtyProcess(pid=pid, master_fd=master_fd)
    proc.start_reader()

    if background:
        process_id = str(uuid.uuid4())
        _pty_store(context)[process_id] = proc
        return ToolResult(
            success=True,
            content=process_id,
            metadata={"background": True, "pid": pid, "pty": True},
        )

    await proc.wait()
    text = proc.output.decode("utf-8", errors="replace")
    return ToolResult(
        success=proc.exit_code == 0,
        content=text.strip(),
        metadata={
            "returncode": proc.exit_code,
            "stdout": text,
            "stderr": "",
            "status": "completed",
            "pty": True,
        },
    )


def _pty_store(context: ToolContext) -> dict[str, PtyProcess]:
    store = context.metadata.get(_PTY_STORE_KEY)
    if store is None:
        store = {}
        context.metadata[_PTY_STORE_KEY] = store
    if not isinstance(store, dict):
        raise ToolError("shell pty store is invalid")
    return store


def _get_pty(context: ToolContext, process_id: str) -> PtyProcess | None:
    return _pty_store(context).get(process_id)


def _pop_pty(context: ToolContext, process_id: str) -> PtyProcess | None:
    store = _pty_store(context)
    return store.pop(process_id, None)
