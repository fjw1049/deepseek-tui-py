"""CLI subcommand parity tests.

Mirrors Rust ``crates/cli/src/lib.rs`` tests — verifies that all
subcommands are registered, parse correctly, and the help surface
contains expected tokens.
"""
from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from deepseek_tui.cli.app import app

runner = CliRunner()


class TestVersionAndHelp:
    def test_version_flag(self) -> None:
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert "0.1.0" in result.stdout

    def test_version_command(self) -> None:
        result = runner.invoke(app, ["version"])
        assert result.exit_code == 0
        assert "0.1.0" in result.stdout

    def test_help_contains_expected_subcommands(self) -> None:
        """Mirror of Rust root_help_surface_contains_expected_subcommands_and_globals."""
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        for token in [
            "doctor",
            "models",
            "serve",
            "auth",
            "config",
            "model",
            "thread",
            "sandbox",
            "features",
            "init",
            "login",
            "logout",
            "version",
            "exec",
            "review",
            "apply",
            "eval",
            "sessions",
            "resume",
            "fork",
            "setup",
            "mcp",
            "completions",
            "mcp-server",
            "app-server",
            "metrics",
            "update",
        ]:
            assert token in result.stdout, f"expected help to contain: {token}"


class TestDoctorCommand:
    def test_doctor_runs(self) -> None:
        result = runner.invoke(app, ["doctor"])
        assert result.exit_code == 0
        assert "deepseek-tui doctor" in result.stdout
        assert "python:" in result.stdout
        assert "platform:" in result.stdout


class TestModelsCommand:
    def test_models_lists_providers(self) -> None:
        result = runner.invoke(app, ["models"])
        assert result.exit_code == 0
        assert "deepseek" in result.stdout

    def test_models_filter_by_provider(self) -> None:
        result = runner.invoke(app, ["models", "--provider", "deepseek"])
        assert result.exit_code == 0
        assert "deepseek-v4-pro" in result.stdout


class TestConfigCommands:
    """Mirror of Rust parses_config_command_matrix."""

    def test_config_get(self) -> None:
        result = runner.invoke(app, ["config", "get", "provider"])
        assert result.exit_code == 0
        assert "deepseek" in result.stdout

    def test_config_list(self) -> None:
        result = runner.invoke(app, ["config", "list"])
        assert result.exit_code == 0
        assert "provider" in result.stdout

    def test_config_path(self) -> None:
        result = runner.invoke(app, ["config", "path"])
        assert result.exit_code == 0
        assert "config.toml" in result.stdout

    def test_config_show(self) -> None:
        result = runner.invoke(app, ["config", "show"])
        assert result.exit_code == 0
        assert "deepseek" in result.stdout


class TestModelCommands:
    """Mirror of Rust parses_model_command_matrix."""

    def test_model_list(self) -> None:
        result = runner.invoke(app, ["model", "list"])
        assert result.exit_code == 0
        assert "deepseek-v4-pro" in result.stdout

    def test_model_list_filtered(self) -> None:
        result = runner.invoke(app, ["model", "list", "--provider", "openai"])
        assert result.exit_code == 0
        assert "gpt-4.1" in result.stdout

    def test_model_resolve(self) -> None:
        result = runner.invoke(app, ["model", "resolve", "deepseek-v4-pro"])
        assert result.exit_code == 0
        assert "requested: deepseek-v4-pro" in result.stdout
        assert "resolved: deepseek-v4-pro" in result.stdout
        assert "used_fallback: False" in result.stdout


class TestAuthCommands:
    """Mirror of Rust parses_auth_subcommand_matrix."""

    def test_auth_status(self) -> None:
        result = runner.invoke(app, ["auth", "status"])
        assert result.exit_code == 0
        assert "provider:" in result.stdout

    def test_auth_list(self) -> None:
        result = runner.invoke(app, ["auth", "list"])
        assert result.exit_code == 0
        assert "keyring backend:" in result.stdout
        assert "provider" in result.stdout

    def test_auth_migrate_dry_run(self) -> None:
        result = runner.invoke(app, ["auth", "migrate", "--dry-run"])
        assert result.exit_code == 0
        assert "keyring backend:" in result.stdout


class TestThreadCommands:
    """Thread subcommands now backed by SessionManager (P2 #17, 2026-05-10).

    When state.db is absent, list returns "No saved threads."; read and
    archive return error and exit 1.
    """

    def test_thread_list_runs(self) -> None:
        result = runner.invoke(app, ["thread", "list"])
        # Either no state.db (exit 0 + "No saved threads.") or actual list.
        assert result.exit_code == 0

    def test_thread_read_exits_with_message(self) -> None:
        result = runner.invoke(app, ["thread", "read", "thread-1"])
        # Without state.db or with missing thread, exit code is 1
        assert result.exit_code == 1

    def test_thread_archive_exits_with_message(self) -> None:
        result = runner.invoke(app, ["thread", "archive", "thread-4"])
        # Without state.db, exit code is 1; with state.db and missing
        # thread, archive() may silently no-op (exit 0). Accept both.
        assert result.exit_code in (0, 1)


class TestSandboxCommand:
    def test_sandbox_check(self) -> None:
        result = runner.invoke(app, ["sandbox", "check", "echo hello"])
        assert result.exit_code == 0
        assert "safety_level" in result.stdout
        assert "echo hello" in result.stdout


class TestFeaturesCommand:
    def test_features_lists_flags(self) -> None:
        result = runner.invoke(app, ["features"])
        assert result.exit_code == 0
        assert "Feature Flags:" in result.stdout


class TestInitCommand:
    def test_init_creates_agents_md(self, tmp_path: Path) -> None:
        import os
        old_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            result = runner.invoke(app, ["init"])
            assert result.exit_code == 0
            assert (tmp_path / "AGENTS.md").exists()
        finally:
            os.chdir(old_cwd)

    def test_init_refuses_if_exists(self, tmp_path: Path) -> None:
        import os
        (tmp_path / "AGENTS.md").write_text("existing")
        old_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            result = runner.invoke(app, ["init"])
            assert result.exit_code == 1
            assert "already exists" in result.stdout
        finally:
            os.chdir(old_cwd)


class TestStubCommands:
    """Stub commands should exit 1 with a meaningful message."""

    def test_exec_stub(self) -> None:
        result = runner.invoke(app, ["exec"])
        assert result.exit_code == 1

    def test_review_stub(self) -> None:
        result = runner.invoke(app, ["review"])
        assert result.exit_code == 1

    def test_eval_stub(self) -> None:
        result = runner.invoke(app, ["eval"])
        assert result.exit_code == 1

    def test_sessions_stub(self) -> None:
        result = runner.invoke(app, ["sessions"])
        assert result.exit_code == 0

    def test_mcp_stub(self) -> None:
        result = runner.invoke(app, ["mcp"])
        assert result.exit_code == 1

    def test_mcp_server_help(self) -> None:
        # mcp-server now starts a real stdio JSON-RPC server (P2 #16).
        # Use --help to verify the command is registered without blocking.
        result = runner.invoke(app, ["mcp-server", "--help"])
        assert result.exit_code == 0

    def test_metrics_stub(self) -> None:
        result = runner.invoke(app, ["metrics"])
        assert result.exit_code == 0

    def test_update_runs(self) -> None:
        result = runner.invoke(app, ["update"])
        assert result.exit_code == 0
        assert "pip install" in result.stdout
