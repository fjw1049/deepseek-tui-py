"""Stage 6.6 parity tests: Command palette, @file mention, StatusBar.

Verifies that the new widgets are functional and wired correctly.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from deepseek_tui.tui.widgets.command_palette import CommandPalette
from deepseek_tui.tui.widgets.file_mention import FileMention
from deepseek_tui.tui.widgets.status_bar import StatusBar


class TestCommandPalette:
    def test_construction(self) -> None:
        palette = CommandPalette()
        assert palette is not None

    def test_selected_message(self) -> None:
        msg = CommandPalette.Selected("/help")
        assert msg.command == "/help"

    def test_is_modal_screen(self) -> None:
        from textual.screen import ModalScreen
        palette = CommandPalette()
        assert isinstance(palette, ModalScreen)


class TestFileMention:
    def test_construction(self) -> None:
        widget = FileMention()
        assert widget is not None

    def test_construction_with_cwd(self, tmp_path: Any) -> None:
        widget = FileMention(working_directory=tmp_path)
        assert widget._cwd == tmp_path

    def test_find_files_in_directory(self, tmp_path: Path) -> None:
        (tmp_path / "foo.py").write_text("x")
        (tmp_path / "bar.py").write_text("y")
        (tmp_path / ".hidden").write_text("z")
        widget = FileMention(working_directory=tmp_path)
        files = widget._find_files("")
        assert "foo.py" in files
        assert "bar.py" in files
        assert ".hidden" not in files

    def test_find_files_with_prefix(self, tmp_path: Path) -> None:
        (tmp_path / "foo.py").write_text("x")
        (tmp_path / "bar.py").write_text("y")
        widget = FileMention(working_directory=tmp_path)
        files = widget._find_files("fo")
        assert "foo.py" in files
        assert "bar.py" not in files

    def test_find_files_directories(self, tmp_path: Path) -> None:
        (tmp_path / "src").mkdir()
        (tmp_path / "main.py").write_text("x")
        widget = FileMention(working_directory=tmp_path)
        files = widget._find_files("")
        assert "src/" in files
        assert "main.py" in files

    def test_show_hide(self) -> None:
        widget = FileMention()
        widget.show("test")
        assert "visible" in widget.classes
        widget.hide()
        assert "visible" not in widget.classes

    def test_selected_message(self) -> None:
        msg = FileMention.Selected("foo.py")
        assert msg.path == "foo.py"


class TestStatusBarEnriched:
    def test_default_status(self) -> None:
        bar = StatusBar()
        assert bar._status == "ready"

    def test_set_model(self) -> None:
        bar = StatusBar()
        bar.set_model("deepseek-v4-pro")
        assert bar._model == "deepseek-v4-pro"

    def test_set_mode(self) -> None:
        bar = StatusBar()
        bar.set_mode("agent")
        assert bar._mode == "agent"

    def test_set_tokens(self) -> None:
        bar = StatusBar()
        bar.set_tokens(1500)
        assert bar._tokens == 1500

    def test_set_status(self) -> None:
        bar = StatusBar()
        bar.set_status("thinking...")
        assert bar._status == "thinking..."

    def test_backward_compat(self) -> None:
        """Old callers using ``set_status`` still work."""
        bar = StatusBar()
        bar.set_status("ready")
        assert bar._status == "ready"
