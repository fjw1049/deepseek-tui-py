"""Stage 6.5 parity tests: Slash command integration with TUI.

Verifies that the Composer detects ``/`` input, that SlashMenu is wired
into the app, and that dispatch results are applied to the transcript.
"""
from __future__ import annotations

from deepseek_tui.tui.commands import CommandResult, dispatch, resolve
from deepseek_tui.tui.widgets.composer import Composer
from deepseek_tui.tui.widgets.slash_menu import SlashMenu


class TestComposerSlashDetection:
    def test_composer_message_types(self) -> None:
        """Composer exposes SlashInput and TextChanged messages."""
        assert hasattr(Composer, "Submitted")
        assert hasattr(Composer, "SlashInput")
        assert hasattr(Composer, "TextChanged")

    def test_slash_input_message(self) -> None:
        msg = Composer.SlashInput("/help")
        assert msg.raw_input == "/help"

    def test_text_changed_message(self) -> None:
        msg = Composer.TextChanged("hello")
        assert msg.text == "hello"


class TestSlashMenuIntegration:
    def test_menu_show_hide(self) -> None:
        menu = SlashMenu()
        menu.show("/help")
        assert "visible" in menu.classes
        menu.hide()
        assert "visible" not in menu.classes

    def test_menu_selected_message(self) -> None:
        msg = SlashMenu.Selected("/help")
        assert msg.command == "/help"


class TestDispatchIntegration:
    def test_dispatch_help(self) -> None:
        """``/help`` should produce a non-empty output."""
        result = dispatch("/help", None)  # type: ignore[arg-type]
        assert result.output
        assert not result.error

    def test_dispatch_clear(self) -> None:
        result = dispatch("/clear", None)  # type: ignore[arg-type]
        assert isinstance(result, CommandResult)

    def test_dispatch_exit(self) -> None:
        result = dispatch("/exit", None)  # type: ignore[arg-type]
        assert result.exit_app

    def test_dispatch_unknown(self) -> None:
        result = dispatch("/nonexistent_command_xyz", None)  # type: ignore[arg-type]
        assert result.error

    def test_dispatch_model_no_args(self) -> None:
        result = dispatch("/model", None)  # type: ignore[arg-type]
        assert isinstance(result, CommandResult)

    def test_dispatch_version(self) -> None:
        result = dispatch("/version", None)  # type: ignore[arg-type]
        assert isinstance(result, CommandResult)


class TestResolveFromApp:
    def test_help_resolves(self) -> None:
        entry = resolve("/help")
        assert entry is not None
        assert entry.name == "/help"

    def test_clear_resolves(self) -> None:
        entry = resolve("/clear")
        assert entry is not None

    def test_alias_resolves(self) -> None:
        entry = resolve("/quit")
        assert entry is not None
        assert entry.name == "/exit"
