from __future__ import annotations

import asyncio
import uuid
from asyncio.subprocess import Process
from typing import Any

from deepseek_tui.tools.base import ToolCapability, ToolError, ToolResult, ToolSpec
from deepseek_tui.tools.context import ToolContext

_PROCESS_STORE_KEY = "shell_processes"


class ExecShellTool(ToolSpec):
    def name(self) -> str:
        return "exec_shell"

    def description(self) -> str:
        return "Execute a shell command, optionally in the background."

    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "background": {"type": "boolean"},
            },
            "required": ["command"],
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.EXECUTES_CODE, ToolCapability.SANDBOXABLE]

    async def execute(self, input_data: dict[str, object], context: ToolContext) -> ToolResult:
        command = _require_string(input_data, "command")
        background = bool(input_data.get("background", False))
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
                metadata={"background": True, "pid": process.pid},
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
