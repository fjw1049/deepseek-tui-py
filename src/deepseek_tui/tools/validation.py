"""Validation tools and structured output.

Consolidates validation_tools.py, structured_output_tool.py, _validators.py.
"""

from __future__ import annotations



# Data validation + test runner + revert turn tools.
#
import asyncio
import json
from pathlib import Path
from typing import Any

from deepseek_tui.tools.registry import (
    ApprovalRequirement,
    ToolCapability,
    ToolError,
    ToolResult,
    ToolSpec,
)
from deepseek_tui.tools.registry import ToolContext

MAX_OUTPUT_CHARS = 40_000


class ValidateDataTool(ToolSpec):
    def name(self) -> str:
        return "validate_data"

    def description(self) -> str:
        return "Validate JSON or TOML content from inline input or a workspace file."

    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
                "format": {
                    "type": "string",
                    "enum": ["auto", "json", "toml"],
                    "default": "auto",
                },
            },
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.READ_ONLY, ToolCapability.SANDBOXABLE]

    def supports_parallel(self) -> bool:
        return True

    async def execute(
        self, input_data: dict[str, object], context: ToolContext
    ) -> ToolResult:
        path_str = input_data.get("path")
        content = input_data.get("content")
        fmt = str(input_data.get("format", "auto"))

        if path_str and content:
            raise ToolError("Provide either 'path' or 'content', but not both.")
        if not path_str and not content:
            raise ToolError("Missing required field: path or content")

        if path_str:
            resolved = context.resolve_path(str(path_str))
            raw = resolved.read_text(encoding="utf-8")
            source = str(path_str)
            ext = resolved.suffix.lstrip(".").lower() if resolved.suffix else None
        else:
            raw = str(content)
            source = "inline"
            ext = None

        if fmt == "json":
            return _validate_json(raw, source)
        if fmt == "toml":
            return _validate_toml(raw, source)

        if ext == "json":
            return _validate_json(raw, source)
        if ext == "toml":
            return _validate_toml(raw, source)

        json_ok = _try_json(raw)
        if json_ok is not None:
            payload = {"valid": True, "format": "json", "source": source, "summary": json_ok}
            return ToolResult(success=True, content=json.dumps(payload))
        toml_ok = _try_toml(raw)
        if toml_ok is not None:
            payload = {"valid": True, "format": "toml", "source": source, "summary": toml_ok}
            return ToolResult(success=True, content=json.dumps(payload))

        return ToolResult(
            success=False,
            content="Validation failed in auto mode: content is neither valid JSON nor TOML.",
        )


def _validate_json(raw: str, source: str) -> ToolResult:
    try:
        parsed = json.loads(raw)
        summary = _summarize_json(parsed)
        payload = {"valid": True, "format": "json", "source": source, "summary": summary}
        return ToolResult(success=True, content=json.dumps(payload))
    except json.JSONDecodeError as e:
        return ToolResult(success=False, content=f"Invalid JSON: {e}")


def _validate_toml(raw: str, source: str) -> ToolResult:
    try:
        import tomllib
    except ModuleNotFoundError:
        import tomli as tomllib  # type: ignore[no-redef]
    try:
        parsed = tomllib.loads(raw)
        summary = {
            "top_level": "table",
            "entries": len(parsed),
            "keys_preview": list(parsed.keys())[:10],
        }
        payload = {"valid": True, "format": "toml", "source": source, "summary": summary}
        return ToolResult(success=True, content=json.dumps(payload))
    except Exception as e:  # noqa: BLE001
        return ToolResult(success=False, content=f"Invalid TOML: {e}")


def _try_json(raw: str) -> dict[str, Any] | None:
    try:
        return _summarize_json(json.loads(raw))
    except (json.JSONDecodeError, TypeError):
        return None


def _try_toml(raw: str) -> dict[str, Any] | None:
    try:
        import tomllib
    except ModuleNotFoundError:
        import tomli as tomllib  # type: ignore[no-redef]
    try:
        parsed = tomllib.loads(raw)
        return {"top_level": "table", "entries": len(parsed)}
    except Exception:  # noqa: BLE001
        return None


def _summarize_json(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return {
            "top_level": "object",
            "entries": len(value),
            "keys_preview": list(value.keys())[:10],
        }
    if isinstance(value, list):
        return {"top_level": "array", "entries": len(value)}
    return {"top_level": type(value).__name__}


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

        from deepseek_tui.tools.shell import check_command_policy

        refusal = check_command_policy(cmd_str, context)
        if refusal is not None:
            return refusal

        try:
            proc = await asyncio.wait_for(
                asyncio.create_subprocess_shell(
                    cmd_str,
                    cwd=str(workspace),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                ),
                timeout=300,
            )
            stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=300)
        except asyncio.TimeoutError as exc:
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


class RevertTurnTool(ToolSpec):
    """Revert-turn tool.

    Since Python does not have the SnapshotRepo (side-git) system yet,
    this tool returns an informative error directing the user to use
    ``git stash`` or ``git checkout`` instead.
    """

    MAX_OFFSET = 50

    def name(self) -> str:
        return "revert_turn"

    def description(self) -> str:
        return (
            "Roll back workspace files to a snapshot taken before a recent turn. "
            "turn_offset is 1-based: 1 = most recent turn (max 50)."
        )

    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {
                "turn_offset": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": self.MAX_OFFSET,
                },
            },
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.WRITES_FILES, ToolCapability.REQUIRES_APPROVAL]

    def approval_requirement(self) -> ApprovalRequirement:
        return ApprovalRequirement.REQUIRED

    async def execute(
        self, input_data: dict[str, object], context: ToolContext
    ) -> ToolResult:
        offset = int(input_data.get("turn_offset", 1))
        if offset < 1 or offset > self.MAX_OFFSET:
            raise ToolError(
                f"turn_offset must be between 1 and {self.MAX_OFFSET}; got {offset}"
            )

        workspace = context.working_directory
        try:
            proc = await asyncio.create_subprocess_exec(
                "git", "log", "--oneline", f"-{offset + 1}",
                cwd=str(workspace),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
            if proc.returncode != 0:
                return ToolResult(
                    success=False,
                    content="No git history available for revert.",
                )
            raw_lines = stdout.decode("utf-8", errors="replace").strip().splitlines()
            lines = [line for line in raw_lines if line.strip()]
            if len(lines) <= offset:
                return ToolResult(
                    success=False,
                    content=(
                        f"Only {len(lines)} commit(s) exist; "
                        f"turn_offset={offset} is out of range."
                    ),
                )

            target_sha = lines[offset].split()[0]
            co_proc = await asyncio.create_subprocess_exec(
                "git", "checkout", target_sha, "--", ".",
                cwd=str(workspace),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, co_err = await asyncio.wait_for(co_proc.communicate(), timeout=30)
            if co_proc.returncode != 0:
                err_text = co_err.decode("utf-8", errors="replace").strip()
                return ToolResult(
                    success=False,
                    content=f"git checkout failed: {err_text}",
                )
            return ToolResult(
                success=True,
                content=(
                    f"revert_turn(offset={offset}): restored to "
                    f"{target_sha[:8]}. Workspace files reverted."
                ),
            )
        except (asyncio.TimeoutError, FileNotFoundError):
            return ToolResult(
                success=False,
                content="git not available or timed out.",
            )


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
