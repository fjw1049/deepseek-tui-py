"""Child-process environment scrubbing.

Shell commands and MCP stdio servers must not inherit secret-like
variables (``DEEPSEEK_API_KEY`` et al.) from ``os.environ``; explicitly
declared overrides pass through.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest

from deepseek_tui.mcp.transport import (
    McpTransportError,
    StdioTransport,
    augment_mcp_path,
    resolve_mcp_command,
    sanitize_mcp_spawn_env,
)
from deepseek_tui.policy.env_filter import build_child_env, is_secret_env_name
from deepseek_tui.tools import shell


def test_secret_suffixes_detected_case_insensitive():
    for name in (
        "DEEPSEEK_API_KEY",
        "github_token",
        "AWS_SECRET_ACCESS_KEY",
        "DB_PASSWORD",
        "TLS_PRIVATE_KEY",
        "GOOGLE_CREDENTIALS",
        "APP_SECRET",
        "OPENAI_KEY",
        "APIKEY",
        "DEEPSEEK_APIKEY",
        "OPENAI_APIKEY",
        "PGPASSWORD",
        "GH_PAT",
        "PASSWORD",
    ):
        assert is_secret_env_name(name)


def test_normal_vars_not_flagged():
    for name in (
        "PATH", "HOME", "LANG", "SSH_AUTH_SOCK", "EDITOR",
        "XDG_CONFIG_HOME", "TMPDIR", "TOKENIZER",
    ):
        assert not is_secret_env_name(name)


def test_build_child_env_strips_secrets_keeps_normal():
    base = {
        "PATH": "/usr/bin",
        "HOME": "/home/x",
        "DEEPSEEK_API_KEY": "sk-1",
        "GITHUB_TOKEN": "tok",
    }
    env = build_child_env(base=base)
    assert env == {"PATH": "/usr/bin", "HOME": "/home/x"}


def test_explicit_overrides_pass_through_verbatim():
    base = {"DEEPSEEK_API_KEY": "sk-1", "PATH": "/usr/bin"}
    env = build_child_env({"DEEPSEEK_API_KEY": "explicit", "CUSTOM": "1"}, base=base)
    assert env["DEEPSEEK_API_KEY"] == "explicit"
    assert env["CUSTOM"] == "1"
    assert env["PATH"] == "/usr/bin"


class _FakeExecEnv:
    """Minimal stand-in for sandbox.ExecEnv (env/cwd/program/args only)."""

    def __init__(self, env: dict[str, str]) -> None:
        self.env = env
        self.cwd = Path("/tmp")

    def program(self) -> str:
        return "/bin/echo"

    def args(self) -> list[str]:
        return ["hi"]


class _FakeProcess:
    stderr = None
    pid = 0


async def test_shell_spawn_env_excludes_secrets(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-secret")
    captured: dict[str, object] = {}

    async def fake_exec(program, *args, **kwargs):
        captured.update(kwargs)
        return _FakeProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    await shell._spawn_from_exec_env(_FakeExecEnv({"EXPLICIT_TOKEN": "ok"}))
    env = captured["env"]
    assert "DEEPSEEK_API_KEY" not in env
    assert env["EXPLICIT_TOKEN"] == "ok"
    assert "PATH" in env


async def test_mcp_stdio_env_excludes_secrets(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-secret")
    captured: dict[str, object] = {}

    async def fake_exec(program, *args, **kwargs):
        captured.update(kwargs)
        return _FakeProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    transport = StdioTransport("server-cmd", env={"SERVER_TOKEN": "declared"})
    await transport.start()
    env = captured["env"]
    assert "DEEPSEEK_API_KEY" not in env
    assert env["SERVER_TOKEN"] == "declared"
    assert "PATH" in env


def test_augment_mcp_path_adds_missing_user_bins(tmp_path, monkeypatch):
    extra = tmp_path / "brew" / "bin"
    extra.mkdir(parents=True)
    monkeypatch.setattr(
        "deepseek_tui.mcp.transport._MCP_USER_BIN_DIRS",
        (str(extra), str(tmp_path / "missing")),
    )
    env = augment_mcp_path({"PATH": "/usr/bin:/bin"})
    parts = env["PATH"].split(":")
    assert "/usr/bin" in parts
    assert parts[0] == str(extra)
    assert str(tmp_path / "missing") not in parts


def test_resolve_mcp_command_finds_npx_on_augmented_path(tmp_path):
    npx = tmp_path / "npx"
    npx.write_text("#!/bin/sh\n")
    npx.chmod(0o755)
    env = {"PATH": os.pathsep.join(["/usr/bin", "/bin", str(tmp_path)])}
    assert resolve_mcp_command("npx", env) == str(npx)
    assert resolve_mcp_command("/usr/bin/true", env) == "/usr/bin/true"


def test_sanitize_mcp_spawn_env_drops_electron_and_npm_host_vars():
    env = sanitize_mcp_spawn_env(
        {
            "PATH": "/usr/bin",
            "HOME": "/home/x",
            "ELECTRON_RUN_AS_NODE": "1",
            "npm_config_devdir": "/tmp/node-gyp",
            "NPM_CONFIG_CACHE": "/tmp/npm-cache",
            "NODE_OPTIONS": "--require /tmp/electron-preload.js",
            "NODE_PATH": "/tmp/electron-asar",
            "HTTP_PROXY": "http://127.0.0.1:7897",
        }
    )
    assert env == {
        "PATH": "/usr/bin",
        "HOME": "/home/x",
        "HTTP_PROXY": "http://127.0.0.1:7897",
    }


async def test_mcp_stdio_env_strips_electron_host_vars(monkeypatch):
    monkeypatch.setenv("ELECTRON_RUN_AS_NODE", "1")
    monkeypatch.setenv("NODE_OPTIONS", "--require /tmp/electron-preload.js")
    monkeypatch.setenv("npm_config_devdir", "/tmp/node-gyp")
    captured: dict[str, object] = {}

    async def fake_exec(program, *args, **kwargs):
        captured.update(kwargs)
        return _FakeProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    transport = StdioTransport("server-cmd", env={"HTTP_PROXY": "http://127.0.0.1:1"})
    await transport.start()
    env = captured["env"]
    assert "ELECTRON_RUN_AS_NODE" not in env
    assert "NODE_OPTIONS" not in env
    assert "npm_config_devdir" not in env
    assert env["HTTP_PROXY"] == "http://127.0.0.1:1"


async def test_stdio_closed_error_includes_stderr() -> None:
    transport = StdioTransport(
        sys.executable,
        args=["-c", "import sys; sys.stderr.write('boom-from-child\\n'); sys.exit(2)"],
    )
    await transport.start()
    try:
        try:
            await transport.recv()
        except McpTransportError as exc:
            message = str(exc)
        else:
            raise AssertionError("expected closed-by-peer error")
        assert "boom-from-child" in message
        assert "exit=2" in message
    finally:
        await transport.stop()


def test_aws_access_key_id_flagged():
    assert is_secret_env_name("AWS_ACCESS_KEY_ID")


@pytest.mark.asyncio
async def test_pty_child_exec_replaces_environment(monkeypatch, tmp_path):
    """Exercise the actual asyncio PTY spawn, not the retired fork helper."""
    import shlex
    import sys
    from deepseek_tui.tools.registry import ToolContext

    monkeypatch.setenv("DEEPSEEK_API_KEY", "fixture-secret")
    code = "import os; print('SECRET_PRESENT=' + str('DEEPSEEK_API_KEY' in os.environ)); print('PATH_PRESENT=' + str('PATH' in os.environ))"
    result = await shell._run_pty(
        f"{shlex.quote(sys.executable)} -c {shlex.quote(code)}",
        cwd=str(tmp_path), background=False, context=ToolContext(working_directory=tmp_path),
        timeout_ms=5000,
    )
    assert result.success
    assert "SECRET_PRESENT=False" in result.content
    assert "PATH_PRESENT=True" in result.content


@pytest.mark.asyncio
@pytest.mark.parametrize("background", [True, False])
async def test_pty_background_and_timeout_return_real_pid(tmp_path, background):
    import shlex
    from deepseek_tui.tools.registry import ToolContext
    from deepseek_tui.tools.task.tools import TaskOutputTool

    context = ToolContext(working_directory=tmp_path)
    script = "import time; time.sleep(.15); print('pty finished')"
    result = await shell._run_pty(
        f"{shlex.quote(sys.executable)} -c {shlex.quote(script)}",
        cwd=str(tmp_path), background=background, context=context, timeout_ms=20,
    )
    assert result.metadata["pid"] > 0
    process_id = result.metadata["process_id"]
    try:
        output = await TaskOutputTool().execute(
            {"process_id": process_id, "block": True, "timeout_ms": 2000}, context,
        )
        assert "pty finished" in output.content
    finally:
        process = shell._get_pty(context, process_id)
        if process is not None:
            shell._kill_pty_process_group(process)
            await process.wait()
