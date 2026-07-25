"""Validation tools and structured output.

Consolidates validation_tools.py, structured_output_tool.py, _validators.py.
"""

from __future__ import annotations



# Test runner tool.
#
import asyncio
import json
from pathlib import Path
from typing import Any

from deepseek_tui.tools.registry import (
    ToolCapability,
    ToolError,
    ToolResult,
    ToolSpec,
)
from deepseek_tui.tools.registry import ToolContext

MAX_OUTPUT_CHARS = 40_000


class RunTestsTool(ToolSpec):
    """Test runner adapted for Python projects."""

    def name(self) -> str:
        return "run_tests"

    def description(self) -> str:
        return (
            "Run project tests. Detects pytest/cargo/npm and executes "
            "with optional extra arguments."
        )

    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {
                "args": {"type": "string"},
                "command": {"type": "string"},
            },
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.EXECUTES_CODE, ToolCapability.SANDBOXABLE]

    async def execute(
        self, input_data: dict[str, object], context: ToolContext
    ) -> ToolResult:
        extra_args = str(input_data.get("args", "")).strip()
        custom_cmd = input_data.get("command")

        workspace = context.working_directory
        if custom_cmd:
            cmd_str = str(custom_cmd)
        else:
            cmd_str = _detect_test_command(workspace)
        if extra_args:
            cmd_str = f"{cmd_str} {extra_args}"

        from deepseek_tui.tools.shell import check_command_policy, spawn_sandboxed_shell

        refusal = check_command_policy(cmd_str, context)
        if refusal is not None:
            return refusal

        proc: asyncio.subprocess.Process | None = None
        exec_env = None
        try:
            proc, exec_env = await spawn_sandboxed_shell(
                cmd_str, workspace, context, timeout_ms=300_000
            )
            stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=300)
        except asyncio.TimeoutError as exc:
            if proc is not None:
                try:
                    proc.kill()
                    await proc.wait()
                except (OSError, ProcessLookupError):
                    pass
            raise ToolError("Test run timed out after 300s") from exc

        stdout = (stdout_b or b"").decode("utf-8", errors="replace")
        stderr = (stderr_b or b"").decode("utf-8", errors="replace")
        rc = proc.returncode or 0

        stdout = _truncate(stdout, MAX_OUTPUT_CHARS)
        stderr = _truncate(stderr, MAX_OUTPUT_CHARS)

        payload = {
            "success": rc == 0,
            "exit_code": rc,
            "stdout": stdout,
            "stderr": stderr,
            "command": cmd_str,
            "sandboxed": exec_env.is_sandboxed() if exec_env else False,
            "sandbox_type": exec_env.sandbox_type.value if exec_env else "none",
        }
        return ToolResult(
            success=True,
            content=json.dumps(payload, ensure_ascii=False),
            metadata=payload,
        )


def _detect_test_command(workspace: Path) -> str:
    if (workspace / "pyproject.toml").exists() or (workspace / "setup.py").exists():
        return "python -m pytest"
    if (workspace / "Cargo.toml").exists():
        return "cargo test"
    if (workspace / "package.json").exists():
        return "npm test"
    return "python -m pytest"


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    omitted = len(text) - limit
    return text[:limit] + f"\n\n[output truncated; {omitted} chars omitted]"


# Terminating structured-output tool for sub-agent workflows.


STRUCTURED_OUTPUT_TOOL_NAME = "structured_output"


def _schema_to_tool_input(schema: dict[str, Any]) -> dict[str, object]:
    """Wrap JSON Schema as tool parameters object."""
    if schema.get("type") == "object" and "properties" in schema:
        out: dict[str, object] = {
            "type": "object",
            "properties": schema.get("properties", {}),
            "required": schema.get("required", []),
        }
        if "additionalProperties" in schema:
            out["additionalProperties"] = schema["additionalProperties"]
        return out
    return {
        "type": "object",
        "properties": {"output": schema},
        "required": ["output"],
    }


class StructuredOutputTool(ToolSpec):
    """Capture validated params as the sub-agent final answer and stop the loop."""

    def __init__(self, schema: dict[str, Any]) -> None:
        self._schema = schema

    def name(self) -> str:
        return STRUCTURED_OUTPUT_TOOL_NAME

    def description(self) -> str:
        return (
            "Return the final machine-readable result for this sub-agent task. "
            "Call exactly once when finished."
        )

    def input_schema(self) -> dict[str, object]:
        return _schema_to_tool_input(self._schema)

    def _unwrap_input(self, input_data: dict[str, Any]) -> Any:
        if self._schema.get("type") == "object" and "properties" in self._schema:
            return input_data
        return input_data.get("output")

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.READ_ONLY]

    async def execute(
        self, input_data: dict[str, Any], context: ToolContext
    ) -> ToolResult:
        del context
        value = self._unwrap_input(input_data)
        try:
            import jsonschema

            jsonschema.validate(instance=value, schema=self._schema)
        except Exception as exc:  # noqa: BLE001
            return ToolResult(
                success=False,
                content=f"structured_output validation failed: {exc}",
            )
        return ToolResult(
            success=True,
            content="Structured output received.",
            metadata={
                "value": value,
                "terminate_subagent": True,
            },
        )


# Shared input validation helpers for tool implementations.
#
# Extracted from per-tool duplicates to reduce ~100 lines of redundancy
# across 12+ tool files.
#



def require_string(input_data: dict[str, object], key: str) -> str:
    """Extract a required string parameter or raise ToolError."""
    value = input_data.get(key)
    if not isinstance(value, str):
        raise ToolError(f"{key} must be a string")
    return value


def optional_string(input_data: dict[str, object], key: str) -> str | None:
    """Extract an optional string parameter or raise ToolError if wrong type."""
    value = input_data.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ToolError(f"{key} must be a string")
    return value


def optional_int(input_data: dict[str, object], key: str) -> int | None:
    """Extract an optional integer parameter or raise ToolError if wrong type."""
    value = input_data.get(key)
    if value is None:
        return None
    if not isinstance(value, int):
        raise ToolError(f"{key} must be an integer")
    return value


def optional_bool(data: dict[str, Any], key: str) -> bool | None:
    """Extract an optional boolean parameter or raise ToolError if wrong type."""
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, bool):
        raise ToolError(f"{key} must be a boolean")
    return value


def optional_string_list(
    input_data: dict[str, object], key: str
) -> list[str] | None:
    """Extract an optional list of strings or raise ToolError if wrong type."""
    value = input_data.get(key)
    if value is None:
        return None
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ToolError(f"{key} must be a list of strings")
    return value
