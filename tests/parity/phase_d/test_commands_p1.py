"""Parity tests for P1 slash commands and CLI subcommands.

Validates the 30 P1 slash command handlers and enhanced CLI subcommands
against the behavioral expectations from the Rust reference.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

# ─── Slash command handler tests ──────────────────────────────────────────


class _FakeApp:
    """Minimal app mock for slash command handlers."""

    _config = MagicMock()
    _config.provider = "deepseek"
    _config.hooks = None


@pytest.fixture
def fake_app() -> _FakeApp:
    return _FakeApp()


def _dispatch(raw_input: str, app: _FakeApp):
    from deepseek_tui.tui.commands import dispatch
    return dispatch(raw_input, app)


class TestModelsCommand:
    def test_lists_providers(self, fake_app):
        result = _dispatch("/models", fake_app)
        assert "Available models" in result.output
        assert not result.error

    def test_alias_resolution(self, fake_app):
        from deepseek_tui.tui.commands import resolve
        assert resolve("/models") is not None


class TestProviderCommand:
    def test_show_current(self, fake_app):
        result = _dispatch("/provider", fake_app)
        assert "Current provider" in result.output

    def test_switch_valid(self, fake_app):
        result = _dispatch("/provider deepseek", fake_app)
        assert "switched" in result.output.lower()

    def test_switch_invalid(self, fake_app):
        result = _dispatch("/provider nonexistent", fake_app)
        assert result.error
        assert "Unknown provider" in result.error


class TestQueueCommand:
    def test_empty_queue(self, fake_app):
        result = _dispatch("/queue", fake_app)
        assert "empty" in result.output.lower()


class TestStashCommand:
    def test_list_empty(self, fake_app, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        result = _dispatch("/stash", fake_app)
        assert "empty" in result.output.lower() or "Stash" in result.output

    def test_push_and_pop(self, fake_app, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        push_result = _dispatch("/stash push hello world", fake_app)
        assert "Stashed as" in push_result.output

        pop_result = _dispatch("/stash pop", fake_app)
        assert "hello world" in pop_result.output

    def test_push_no_text(self, fake_app, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        result = _dispatch("/stash push", fake_app)
        assert result.error


class TestHooksCommand:
    def test_no_hooks(self, fake_app):
        result = _dispatch("/hooks", fake_app)
        assert "No hooks" in result.output or "Hooks config" in result.output


class TestSubagentsCommand:
    def test_no_agents(self, fake_app):
        result = _dispatch("/subagents", fake_app)
        assert "No active" in result.output


class TestAttachCommand:
    def test_no_args(self, fake_app):
        result = _dispatch("/attach", fake_app)
        assert result.error

    def test_file_not_found(self, fake_app):
        result = _dispatch("/attach /nonexistent/file.png", fake_app)
        assert result.error
        assert "not found" in result.error.lower()

    def test_unsupported_format(self, fake_app, tmp_path):
        f = tmp_path / "test.xyz"
        f.write_text("data")
        result = _dispatch(f"/attach {f}", fake_app)
        assert result.error
        assert "Unsupported" in result.error

    def test_supported_format(self, fake_app, tmp_path):
        f = tmp_path / "test.png"
        f.write_bytes(b"\x89PNG")
        result = _dispatch(f"/attach {f}", fake_app)
        assert "Attached" in result.output


class TestTaskCommand:
    def test_no_tasks(self, fake_app):
        result = _dispatch("/task", fake_app)
        assert "No background" in result.output


class TestJobsCommand:
    def test_no_jobs(self, fake_app):
        result = _dispatch("/jobs", fake_app)
        assert "No active" in result.output


class TestMcpCommand:
    def test_no_config(self, fake_app, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "deepseek_tui.config.paths.default_config_path",
            lambda: tmp_path / "config.toml",
        )
        result = _dispatch("/mcp", fake_app)
        assert "No MCP" in result.output


class TestCompactCommand:
    def test_trigger(self, fake_app):
        result = _dispatch("/compact", fake_app)
        assert "triggered" in result.output.lower()


class TestCyclesCommand:
    def test_no_archives(self, fake_app, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        result = _dispatch("/cycles", fake_app)
        assert "No cycle" in result.output


class TestCycleCommand:
    def test_current_cycle(self, fake_app):
        result = _dispatch("/cycle", fake_app)
        assert "cycle" in result.output.lower()


class TestRecallCommand:
    def test_no_query(self, fake_app):
        result = _dispatch("/recall", fake_app)
        assert result.error

    def test_with_query(self, fake_app):
        result = _dispatch("/recall test query", fake_app)
        assert "Searching" in result.output


class TestYoloCommand:
    def test_enable(self, fake_app):
        result = _dispatch("/yolo", fake_app)
        assert "YOLO" in result.output


class TestTrustCommand:
    def test_trust_cwd(self, fake_app):
        result = _dispatch("/trust", fake_app)
        assert "trusted" in result.output.lower()


class TestDiffCommand:
    def test_diff_output(self, fake_app):
        result = _dispatch("/diff", fake_app)
        assert result.output or result.error


class TestLspCommand:
    def test_lsp_status(self, fake_app):
        result = _dispatch("/lsp", fake_app)
        assert "LSP" in result.output


class TestShareCommand:
    def test_share_creates_file(self, fake_app, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = _dispatch("/share", fake_app)
        assert "Exported" in result.output


class TestGoalCommand:
    def test_no_args_shows_info(self, fake_app):
        result = _dispatch("/goal", fake_app)
        assert "No session goal" in result.output

    def test_set_goal(self, fake_app):
        result = _dispatch("/goal complete the migration", fake_app)
        assert "complete the migration" in result.output


class TestSkillsCommand:
    def test_no_skills(self, fake_app, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "deepseek_tui.config.paths.default_config_path",
            lambda: tmp_path / "config.toml",
        )
        result = _dispatch("/skills", fake_app)
        assert "No skills" in result.output


class TestSkillCommand:
    def test_no_args(self, fake_app):
        result = _dispatch("/skill", fake_app)
        assert result.error

    def test_not_found(self, fake_app, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "deepseek_tui.config.paths.default_config_path",
            lambda: tmp_path / "config.toml",
        )
        result = _dispatch("/skill nonexistent", fake_app)
        assert result.error


class TestReviewCommand:
    def test_review_runs(self, fake_app):
        result = _dispatch("/review", fake_app)
        assert result.output or result.error


class TestRestoreCommand:
    def test_no_args(self, fake_app):
        result = _dispatch("/restore", fake_app)
        assert result.error

    def test_with_id(self, fake_app):
        result = _dispatch("/restore abc123", fake_app)
        assert "abc123" in result.output


class TestRlmCommand:
    def test_no_args(self, fake_app):
        result = _dispatch("/rlm", fake_app)
        assert result.error

    def test_with_query(self, fake_app):
        result = _dispatch("/rlm analyze this code", fake_app)
        assert "queued" in result.output.lower()


class TestProfileCommand:
    def test_show_current(self, fake_app):
        result = _dispatch("/profile", fake_app)
        assert "default" in result.output.lower()

    def test_switch(self, fake_app):
        result = _dispatch("/profile work", fake_app)
        assert "work" in result.output


class TestCacheCommand:
    def test_show_stats(self, fake_app):
        result = _dispatch("/cache", fake_app)
        assert "cache" in result.output.lower()


# ─── Alias resolution tests ──────────────────────────────────────────────


class TestAliasResolution:
    def test_queued_alias(self):
        from deepseek_tui.tui.commands import resolve
        assert resolve("/queued") is not None
        assert resolve("/queued").name == "/queue"

    def test_park_alias(self):
        from deepseek_tui.tui.commands import resolve
        assert resolve("/park") is not None
        assert resolve("/park").name == "/stash"

    def test_hook_alias(self):
        from deepseek_tui.tui.commands import resolve
        assert resolve("/hook") is not None
        assert resolve("/hook").name == "/hooks"

    def test_agents_alias(self):
        from deepseek_tui.tui.commands import resolve
        assert resolve("/agents") is not None
        assert resolve("/agents").name == "/subagents"

    def test_image_alias(self):
        from deepseek_tui.tui.commands import resolve
        assert resolve("/image") is not None
        assert resolve("/image").name == "/attach"

    def test_recursive_alias(self):
        from deepseek_tui.tui.commands import resolve
        assert resolve("/recursive") is not None
        assert resolve("/recursive").name == "/rlm"


# ─── Command Registry completeness test ──────────────────────────────────


class TestRegistryCompleteness:
    def test_all_commands_have_handlers(self):
        """Every command in the registry should have a handler (P0 or P1)."""
        from deepseek_tui.tui.commands import REGISTRY
        from deepseek_tui.tui.commands.handlers import get_handler

        missing = []
        for entry in REGISTRY:
            if get_handler(entry.name) is None:
                missing.append(entry.name)
        assert not missing, f"Commands without handlers: {missing}"


# ─── CLI subcommand tests ─────────────────────────────────────────────────


class TestCliExec:
    def test_exec_requires_prompt(self):
        from typer.testing import CliRunner

        from deepseek_tui.cli.app import app

        runner = CliRunner()
        result = runner.invoke(app, ["exec"])
        assert result.exit_code != 0


class TestCliSessions:
    def test_sessions_runs(self):
        from typer.testing import CliRunner

        from deepseek_tui.cli.app import app

        runner = CliRunner()
        result = runner.invoke(app, ["sessions"])
        assert result.exit_code == 0 or "No saved sessions" in result.output


class TestCliMcp:
    def test_mcp_no_config(self, tmp_path, monkeypatch):
        from typer.testing import CliRunner

        from deepseek_tui.cli.app import app

        monkeypatch.setattr(
            "deepseek_tui.config.paths.default_config_path",
            lambda: tmp_path / "config.toml",
        )
        runner = CliRunner()
        result = runner.invoke(app, ["mcp"])
        assert "No MCP" in result.output or result.exit_code != 0


class TestCliMetrics:
    def test_metrics_runs(self):
        from typer.testing import CliRunner

        from deepseek_tui.cli.app import app

        runner = CliRunner()
        result = runner.invoke(app, ["metrics"])
        assert result.exit_code == 0 or "Metrics" in result.output


class TestCliApply:
    def test_apply_no_input(self):
        from typer.testing import CliRunner

        from deepseek_tui.cli.app import app

        runner = CliRunner()
        result = runner.invoke(app, ["apply"])
        assert result.exit_code != 0
