"""Tests for macOS Seatbelt sandbox integration."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

from deepseek_tui.policy.sandbox import (
    CommandSpec,
    ExecutionSandboxPolicy,
    SANDBOX_MANAGER,
    SandboxType,
    sandbox_policy_for_mode,
    sync_execution_sandbox_policy,
)
from deepseek_tui.tools.registry import ToolContext
from deepseek_tui.tools.shell import ExecShellTool


class TestExecutionSandboxPolicy:
    def test_default_should_sandbox(self) -> None:
        policy = ExecutionSandboxPolicy.default()
        assert policy.should_sandbox()
        assert not policy.has_network_access()

    def test_danger_full_access_skips_sandbox(self) -> None:
        policy = ExecutionSandboxPolicy.danger_full_access()
        assert not policy.should_sandbox()
        assert policy.has_network_access()

    def test_sandbox_policy_for_mode(self) -> None:
        workspace = Path("/tmp/workspace")
        assert sandbox_policy_for_mode("plan", workspace).kind == "read-only"
        assert sandbox_policy_for_mode("yolo", workspace).kind == "danger-full-access"
        agent = sandbox_policy_for_mode("agent", workspace)
        assert agent.kind == "workspace-write"
        assert agent.network_access is True

    def test_prepare_warns_when_sandbox_unavailable_on_any_platform(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """H8: a sandbox policy with no OS sandbox available must warn on
        every platform (not just darwin). Previously Linux silently ran
        unsandboxed because the warning was gated on ``sys.platform == "darwin"``.
        """
        from unittest.mock import patch

        from deepseek_tui.policy import sandbox as sandbox_module

        manager = sandbox_module.SandboxManager()
        spec = CommandSpec(
            program="echo",
            args=["hi"],
            cwd=tmp_path,
            sandbox_policy=sandbox_policy_for_mode("agent", tmp_path),
        )
        assert spec.sandbox_policy.should_sandbox()  # workspace-write

        # Simulate "no OS sandbox available" (the Linux / no-Seatbelt case)
        # regardless of the platform this test runs on.
        with patch.object(sandbox_module, "get_platform_sandbox", return_value=None):
            with caplog.at_level("WARNING", logger="deepseek_tui.policy.sandbox"):
                env = manager.prepare(spec)

        # Non-breaking: still runs, just unsandboxed.
        assert env.sandbox_type == SandboxType.NONE
        assert any(
            "no OS sandbox is available" in rec.message
            and "workspace-write" in rec.message
            for rec in caplog.records
        ), [rec.message for rec in caplog.records]

    def test_prepare_does_not_warn_when_sandbox_opted_out(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """danger-full-access explicitly opts out of sandboxing - no warning."""
        from unittest.mock import patch

        from deepseek_tui.policy import sandbox as sandbox_module

        manager = sandbox_module.SandboxManager()
        spec = CommandSpec(
            program="echo",
            args=["hi"],
            cwd=tmp_path,
            sandbox_policy=ExecutionSandboxPolicy.danger_full_access(),
        )
        assert not spec.sandbox_policy.should_sandbox()

        with patch.object(sandbox_module, "get_platform_sandbox", return_value=None):
            with caplog.at_level("WARNING", logger="deepseek_tui.policy.sandbox"):
                env = manager.prepare(spec)

        assert env.sandbox_type == SandboxType.NONE
        assert not [rec for rec in caplog.records if "no OS sandbox" in rec.message]


    def test_writable_roots_protect_deepseek(self, tmp_path: Path) -> None:
        deepseek_dir = tmp_path / ".deepseek"
        deepseek_dir.mkdir()
        policy = ExecutionSandboxPolicy.workspace_write(
            writable_roots=(tmp_path,),
            network_access=True,
        )
        roots = policy.get_writable_roots(tmp_path)
        assert any(r.read_only_subpaths == (deepseek_dir,) for r in roots)


class TestSandboxManager:
    def test_prepare_unsandboxed_for_yolo(self) -> None:
        spec = CommandSpec.shell(
            "echo test",
            Path("/tmp"),
            30_000,
        ).with_policy(ExecutionSandboxPolicy.danger_full_access())
        env = SANDBOX_MANAGER.prepare(spec)
        assert env.sandbox_type == SandboxType.NONE
        assert env.command == ["sh", "-c", "echo test"]

    @pytest.mark.skipif(sys.platform != "darwin", reason="macOS only")
    def test_prepare_seatbelt_wraps_command(self) -> None:
        from deepseek_tui.policy import sandbox as seatbelt

        if not seatbelt.is_available():
            pytest.skip("sandbox-exec unavailable")

        spec = CommandSpec.shell(
            "echo test",
            Path("/tmp"),
            30_000,
        ).with_policy(
            ExecutionSandboxPolicy.workspace_write(
                writable_roots=(Path("/tmp"),),
                network_access=True,
            )
        )
        env = SANDBOX_MANAGER.prepare(spec)
        assert env.sandbox_type == SandboxType.MACOS_SEATBELT
        assert env.command[0] == seatbelt.SANDBOX_EXEC_PATH
        assert env.command[-3:] == ["sh", "-c", "echo test"]


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS only")
class TestSeatbeltIntegration:
    @pytest.fixture
    def workspace(self) -> Path:
        with tempfile.TemporaryDirectory() as tmp:
            yield Path(tmp)

    async def _run(self, command: str, workspace: Path, mode: str = "agent") -> dict:
        context = ToolContext(working_directory=workspace)
        sync_execution_sandbox_policy(context, mode, workspace)
        tool = ExecShellTool()
        result = await tool.execute({"command": command}, context)
        assert isinstance(result.metadata, dict)
        return result.metadata

    @pytest.mark.asyncio
    async def test_workspace_write_succeeds(self, workspace: Path) -> None:
        from deepseek_tui.policy import sandbox as seatbelt

        if not seatbelt.is_available():
            pytest.skip("sandbox-exec unavailable")

        metadata = await self._run("touch ./sandbox_ok.txt", workspace)
        assert metadata.get("sandboxed") is True
        assert metadata.get("sandbox_denied") is not True
        assert (workspace / "sandbox_ok.txt").exists()

    @pytest.mark.asyncio
    async def test_write_outside_workspace_denied(self, workspace: Path) -> None:
        from deepseek_tui.policy import sandbox as seatbelt

        if not seatbelt.is_available():
            pytest.skip("sandbox-exec unavailable")

        metadata = await self._run("touch /etc/hosts", workspace)
        assert metadata.get("sandboxed") is True
        assert metadata.get("sandbox_denied") is True

    @pytest.mark.asyncio
    async def test_deepseek_subpath_read_only(self, workspace: Path) -> None:
        from deepseek_tui.policy import sandbox as seatbelt

        if not seatbelt.is_available():
            pytest.skip("sandbox-exec unavailable")

        deepseek_dir = workspace / ".deepseek"
        deepseek_dir.mkdir()
        config_path = deepseek_dir / "config.toml"
        config_path.write_text("x = 1\n", encoding="utf-8")

        metadata = await self._run(
            "echo hacked >> .deepseek/config.toml",
            workspace,
        )
        assert metadata.get("sandboxed") is True
        assert metadata.get("sandbox_denied") is True

    @pytest.mark.asyncio
    async def test_yolo_mode_not_sandboxed(self, workspace: Path) -> None:
        metadata = await self._run("echo ok", workspace, mode="yolo")
        assert metadata.get("sandboxed") is False
        assert metadata.get("sandbox_type") == "none"

    @pytest.mark.asyncio
    async def test_pty_path(self, workspace: Path) -> None:
        from deepseek_tui.policy import sandbox as seatbelt

        if not seatbelt.is_available():
            pytest.skip("sandbox-exec unavailable")

        context = ToolContext(working_directory=workspace)
        sync_execution_sandbox_policy(context, "agent", workspace)
        tool = ExecShellTool()
        result = await tool.execute(
            {"command": "echo pty_ok", "pty": True},
            context,
        )
        assert result.success is True
        assert "pty_ok" in result.content
        assert result.metadata.get("sandboxed") is True


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS only")
class TestSeatbeltModule:
    def test_detect_denial(self) -> None:
        from deepseek_tui.policy.sandbox import detect_denial

        assert detect_denial(1, "Operation not permitted")
        assert detect_denial(1, "Sandbox: touch denied file-write*")
        assert not detect_denial(0, "Operation not permitted")
        assert not detect_denial(1, "File not found")

    def test_generate_policy_contains_base_rules(self) -> None:
        from deepseek_tui.policy.sandbox import generate_policy

        policy = ExecutionSandboxPolicy.workspace_write(
            writable_roots=(Path("/tmp"),),
            network_access=True,
        )
        text = generate_policy(policy, Path("/tmp/test"))
        assert "(version 1)" in text
        assert "(deny default)" in text
        assert "(allow file-read*)" in text
        assert "network-outbound" in text

    def test_read_only_has_no_writable_roots(self) -> None:
        from deepseek_tui.policy.sandbox import generate_policy

        text = generate_policy(ExecutionSandboxPolicy.read_only(), Path("/tmp/test"))
        assert "WRITABLE_ROOT" not in text


def test_sync_execution_sandbox_policy() -> None:
    workspace = Path("/tmp/test-sync")
    context = ToolContext(working_directory=workspace)
    sync_execution_sandbox_policy(context, "agent", workspace)
    assert context.execution_sandbox_policy is not None
    assert context.execution_sandbox_policy.kind == "workspace-write"
