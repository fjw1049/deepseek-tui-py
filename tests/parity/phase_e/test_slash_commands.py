"""Slash command registry and dispatcher parity tests.

Mirrors Rust ``crates/tui/src/commands/mod.rs`` test coverage. After the
2026-05-12 fake-command cleanup the local registry is a subset (~40
commands) of the Rust catalog; assertions reflect that subset:
- The full registry is registered
- Aliases resolve correctly
- P0 handlers return valid CommandResult
- Unknown commands produce an error
- Dispatch works end-to-end
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from deepseek_tui.tui.commands import (
    REGISTRY,
    CommandResult,
    dispatch,
    get_completions,
    resolve,
)


class TestRegistry:
    def test_registry_within_expected_range(self) -> None:
        # Lower bound guards against accidental over-deletion; upper bound
        # flags if someone re-adds the 2026-05-12 cleanup victims without
        # going through this audit.
        assert 35 <= len(REGISTRY) <= 50

    def test_all_names_start_with_slash(self) -> None:
        for entry in REGISTRY:
            assert entry.name.startswith("/"), entry.name

    def test_no_duplicate_names(self) -> None:
        names = [e.name for e in REGISTRY]
        assert len(names) == len(set(names))

    def test_no_duplicate_aliases(self) -> None:
        all_aliases: list[str] = []
        for entry in REGISTRY:
            all_aliases.extend(entry.aliases)
        assert len(all_aliases) == len(set(all_aliases))

    def test_expected_commands_present(self) -> None:
        """Mirror of Rust root_help_surface test (subset after cleanup)."""
        expected = [
            "/help", "/clear", "/exit", "/model", "/models",
            "/provider", "/config", "/agent", "/plan", "/yolo",
            "/export", "/save", "/sessions", "/init",
            "/context", "/tokens", "/system", "/undo", "/retry",
            "/links", "/home", "/note", "/cost",
            "/settings", "/logout",
        ]
        names = {e.name for e in REGISTRY}
        for cmd in expected:
            assert cmd in names, f"missing command: {cmd}"


class TestResolve:
    def test_resolve_by_name(self) -> None:
        entry = resolve("/help")
        assert entry is not None
        assert entry.name == "/help"

    def test_resolve_by_alias(self) -> None:
        entry = resolve("/?")
        assert entry is not None
        assert entry.name == "/help"

    def test_resolve_exit_aliases(self) -> None:
        for alias in ("/quit", "/q"):
            entry = resolve(alias)
            assert entry is not None
            assert entry.name == "/exit"

    def test_resolve_unknown_returns_none(self) -> None:
        assert resolve("/nonexistent") is None


class TestGetCompletions:
    def test_all_commands_match_slash(self) -> None:
        completions = get_completions("/")
        assert len(completions) == len(REGISTRY)

    def test_filter_narrows_results(self) -> None:
        completions = get_completions("/he")
        names = [c[0] for c in completions]
        assert "/help" in names
        assert "/exit" not in names

    def test_empty_prefix_returns_all(self) -> None:
        completions = get_completions("")
        assert len(completions) == len(REGISTRY)


class TestDispatch:
    def _mock_app(self) -> MagicMock:
        return MagicMock()

    def test_help_returns_output(self) -> None:
        result = dispatch("/help", self._mock_app())
        assert isinstance(result, CommandResult)
        assert result.output
        assert "/help" in result.output

    def test_exit_sets_exit_flag(self) -> None:
        result = dispatch("/exit", self._mock_app())
        assert result.exit_app is True

    def test_clear_returns_output(self) -> None:
        result = dispatch("/clear", self._mock_app())
        assert "clear" in result.output.lower()

    def test_links_returns_urls(self) -> None:
        result = dispatch("/links", self._mock_app())
        assert "deepseek" in result.output.lower()

    def test_home_returns_info(self) -> None:
        result = dispatch("/home", self._mock_app())
        assert result.output

    def test_unknown_command_returns_error(self) -> None:
        result = dispatch("/xyzzy", self._mock_app())
        assert result.error
        assert "unknown" in result.error.lower()

    def test_p1_command_returns_output(self) -> None:
        result = dispatch("/yolo", self._mock_app())
        assert result.output
        assert not result.error

    def test_alias_dispatch(self) -> None:
        result = dispatch("/?", self._mock_app())
        assert result.output
        assert "/help" in result.output

    def test_model_no_args(self) -> None:
        result = dispatch("/model", self._mock_app())
        assert result.output

    def test_model_with_name(self) -> None:
        result = dispatch("/model deepseek-v4-pro", self._mock_app())
        assert "deepseek-v4-pro" in result.output

    def test_init_in_tmp(self, tmp_path: Path) -> None:
        import os
        old_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            result = dispatch("/init", self._mock_app())
            assert result.output
            assert (tmp_path / "AGENTS.md").exists()
        finally:
            os.chdir(old_cwd)

    def test_note_requires_text(self) -> None:
        result = dispatch("/note", self._mock_app())
        assert result.error
        assert "Usage" in result.error

    def test_system_shows_prompt(self) -> None:
        result = dispatch("/system", self._mock_app())
        assert result.output
        assert "system prompt" in result.output.lower() or "System prompt" in result.output

    def test_agent_mode(self) -> None:
        result = dispatch("/agent", self._mock_app())
        assert "agent" in result.output.lower()

    def test_plan_mode(self) -> None:
        result = dispatch("/plan", self._mock_app())
        assert "plan" in result.output.lower()

    def test_settings_shows_config(self) -> None:
        result = dispatch("/settings", self._mock_app())
        assert result.output
        assert "provider" in result.output.lower() or "deepseek" in result.output.lower()
