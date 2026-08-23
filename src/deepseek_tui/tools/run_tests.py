"""Test runner tool (pytest/cargo/npm auto-detection).

Not registered in the default catalog (see ``build_default_registry``).
Test commands go through ``exec_shell``.
"""

from __future__ import annotations


import asyncio
import json
from pathlib import Path

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
            "Run the project's test suite. Auto-detects the runner from "
            "project files (pyproject.toml/setup.py → pytest, Cargo.toml → "
            "cargo test, package.json → npm test); override with "
            "'command' when the project uses something else. Output is "
            "returned as JSON (exit_code, stdout, stderr) and killed after "
            "300s — for longer suites use exec_shell with background=true."
        )

    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {
                "args": {
                    "type": "string",
                    "description": (
                        "Extra arguments appended to the test command, "
                        "e.g. 'tests/test_api.py -k login -q'."
                    ),
                },
                "command": {
                    "type": "string",
                    "description": (
                        "Full test command to run instead of the "
                        "auto-detected one, e.g. 'make test'."
                    ),
                },
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
