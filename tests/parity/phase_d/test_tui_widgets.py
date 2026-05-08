"""Parity tests for P1 TUI widgets.

Tests cover: Sidebar, HelpPanel, Pickers, MarkdownRenderer, DiffViewer.
"""

from __future__ import annotations

from pathlib import Path

# ===========================================================================
# Sidebar tests
# ===========================================================================


class TestSidebar:
    def test_entry_display_time_recent(self) -> None:
        import time

        from deepseek_tui.tui.widgets.sidebar import SidebarEntry

        entry = SidebarEntry(
            id="abc123",
            name="Test Session",
            preview="hello world",
            updated_at=int(time.time()) - 60,
        )
        assert entry.display_time != ""

    def test_entry_display_time_zero(self) -> None:
        from deepseek_tui.tui.widgets.sidebar import SidebarEntry

        entry = SidebarEntry(id="x", name="", preview="", updated_at=0)
        assert entry.display_time == ""

    def test_from_thread_metadata(self) -> None:
        from deepseek_tui.tui.widgets.sidebar import Sidebar

        metadata = [
            {
                "id": "t1", "name": "Session 1", "preview": "hi",
                "updated_at": 100, "model_provider": "deepseek-chat",
            },
            {"id": "t2", "name": "", "preview": "world", "updated_at": 200, "archived_at": 500},
        ]
        entries = Sidebar.from_thread_metadata(metadata)
        assert len(entries) == 2
        assert entries[0].id == "t1"
        assert entries[0].model == "deepseek-chat"
        assert entries[1].archived is True

    def test_sidebar_filter(self) -> None:
        from deepseek_tui.tui.widgets.sidebar import Sidebar, SidebarEntry

        sidebar = Sidebar()
        entries = [
            SidebarEntry(id="1", name="Python project", preview="", updated_at=100),
            SidebarEntry(id="2", name="Rust rewrite", preview="", updated_at=200),
            SidebarEntry(id="3", name="Testing", preview="", updated_at=50),
        ]
        sidebar.set_entries(entries)
        assert len(sidebar._filtered) == 3

        sidebar.filter_text = "rust"
        sidebar._apply_filter()
        assert len(sidebar._filtered) == 1
        assert sidebar._filtered[0].id == "2"


# ===========================================================================
# HelpPanel tests
# ===========================================================================


class TestHelpPanel:
    def test_keybind_sections_nonempty(self) -> None:
        from deepseek_tui.tui.widgets.help_panel import KEYBIND_SECTIONS

        assert len(KEYBIND_SECTIONS) >= 5
        for name, bindings in KEYBIND_SECTIONS:
            assert name
            assert len(bindings) >= 1
            for key, desc in bindings:
                assert key
                assert desc

    def test_help_panel_instantiates(self) -> None:
        from deepseek_tui.tui.widgets.help_panel import HelpPanel

        panel = HelpPanel()
        assert panel is not None


# ===========================================================================
# Pickers tests
# ===========================================================================


class TestPickers:
    def test_model_picker_has_defaults(self) -> None:
        from deepseek_tui.tui.widgets.pickers import AVAILABLE_MODELS, ModelPicker

        assert len(AVAILABLE_MODELS) >= 2
        picker = ModelPicker()
        assert picker._items == AVAILABLE_MODELS

    def test_mode_picker_has_defaults(self) -> None:
        from deepseek_tui.tui.widgets.pickers import AVAILABLE_MODES, ModePicker

        assert len(AVAILABLE_MODES) >= 3
        picker = ModePicker()
        assert picker._items == AVAILABLE_MODES

    def test_provider_picker_has_defaults(self) -> None:
        from deepseek_tui.tui.widgets.pickers import AVAILABLE_PROVIDERS, ProviderPicker

        assert len(AVAILABLE_PROVIDERS) >= 3
        picker = ProviderPicker()
        assert picker._items == AVAILABLE_PROVIDERS

    def test_file_picker_collects_files(self, tmp_path: Path) -> None:
        from deepseek_tui.tui.widgets.pickers import _collect_files

        (tmp_path / "hello.py").write_text("pass")
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "world.py").write_text("pass")
        (tmp_path / "__pycache__").mkdir()
        (tmp_path / "__pycache__" / "cache.pyc").write_text("binary")

        items = _collect_files(tmp_path, 100, "**/*", {"__pycache__", ".git"})
        paths = [v for v, _ in items]
        assert "hello.py" in paths
        assert "sub/world.py" in paths
        assert "__pycache__/cache.pyc" not in paths

    def test_file_picker_respects_max(self, tmp_path: Path) -> None:
        from deepseek_tui.tui.widgets.pickers import _collect_files

        for i in range(20):
            (tmp_path / f"file_{i}.txt").write_text("x")

        items = _collect_files(tmp_path, 5, "**/*", set())
        assert len(items) == 5

    def test_session_picker_custom_items(self) -> None:
        from deepseek_tui.tui.widgets.pickers import SessionPicker

        sessions = [("id1", "Session One"), ("id2", "Session Two")]
        picker = SessionPicker(sessions)
        assert len(picker._items) == 2

    def test_picker_filtering(self) -> None:
        from deepseek_tui.tui.widgets.pickers import ModelPicker

        picker = ModelPicker([
            ("a", "Alpha model"),
            ("b", "Beta model"),
            ("c", "Gamma model"),
        ])
        assert len(picker._filtered) == 3


# ===========================================================================
# Markdown renderer tests
# ===========================================================================


class TestMarkdownRenderer:
    def test_renderer_basic(self) -> None:
        from deepseek_tui.tui.widgets.markdown_render import MarkdownRenderer

        renderer = MarkdownRenderer()
        renderer.update("# Hello\nWorld")
        result = renderer.render()
        assert result is not None

    def test_renderer_streaming(self) -> None:
        from deepseek_tui.tui.widgets.markdown_render import MarkdownRenderer

        renderer = MarkdownRenderer()
        renderer.append("Hello ")
        renderer.append("**bold**")
        assert "Hello **bold**" in renderer.text

    def test_renderer_finalize(self) -> None:
        from deepseek_tui.tui.widgets.markdown_render import MarkdownRenderer

        renderer = MarkdownRenderer()
        renderer.update("Done")
        renderer.finalize()
        result = renderer.render()
        assert result is not None

    def test_extract_code_blocks(self) -> None:
        from deepseek_tui.tui.widgets.markdown_render import extract_code_blocks

        text = "before\n```python\ndef hello():\n    pass\n```\nafter"
        blocks = extract_code_blocks(text)
        assert len(blocks) == 1
        assert blocks[0]["language"] == "python"
        assert "def hello" in blocks[0]["code"]

    def test_extract_code_blocks_multiple(self) -> None:
        from deepseek_tui.tui.widgets.markdown_render import extract_code_blocks

        text = "```js\nconsole.log(1)\n```\n\n```rust\nfn main(){}\n```"
        blocks = extract_code_blocks(text)
        assert len(blocks) == 2
        assert blocks[0]["language"] == "js"
        assert blocks[1]["language"] == "rust"

    def test_render_code_block(self) -> None:
        from deepseek_tui.tui.widgets.markdown_render import render_code_block

        syntax = render_code_block("print('hi')", "python")
        assert syntax is not None

    def test_render_heading(self) -> None:
        from deepseek_tui.tui.widgets.markdown_render import render_heading

        h = render_heading("Title", 1)
        assert "Title" in str(h)

    def test_extract_links(self) -> None:
        from deepseek_tui.tui.widgets.markdown_render import extract_links

        text = "See [docs](https://example.com) and [api](https://api.example.com)"
        links = extract_links(text)
        assert len(links) == 2
        assert links[0] == ("docs", "https://example.com")

    def test_has_diff_block(self) -> None:
        from deepseek_tui.tui.widgets.markdown_render import has_diff_block

        assert has_diff_block("```diff\n+added\n```")
        assert not has_diff_block("```python\npass\n```")

    def test_render_markdown_table(self) -> None:
        from deepseek_tui.tui.widgets.markdown_render import render_markdown_table

        table_text = "| Name | Value |\n|------|-------|\n| foo | 1 |\n| bar | 2 |"
        table = render_markdown_table(table_text)
        assert table is not None

    def test_estimate_rendered_height(self) -> None:
        from deepseek_tui.tui.widgets.markdown_render import estimate_rendered_height

        text = "line1\nline2\nline3"
        height = estimate_rendered_height(text)
        assert height >= 3


# ===========================================================================
# Diff viewer tests
# ===========================================================================


SAMPLE_DIFF = """\
--- a/src/main.py
+++ b/src/main.py
@@ -1,5 +1,6 @@
 import os
+import sys
 
 def main():
-    print("hello")
+    print("hello world")
     pass
"""


class TestDiffViewer:
    def test_parse_unified_diff_basic(self) -> None:
        from deepseek_tui.tui.widgets.diff_viewer import parse_unified_diff

        files = parse_unified_diff(SAMPLE_DIFF)
        assert len(files) == 1
        assert files[0].old_path == "src/main.py"
        assert files[0].new_path == "src/main.py"
        assert files[0].additions == 2
        assert files[0].deletions == 1

    def test_parse_hunk_lines(self) -> None:
        from deepseek_tui.tui.widgets.diff_viewer import parse_unified_diff

        files = parse_unified_diff(SAMPLE_DIFF)
        hunk = files[0].hunks[0]
        assert hunk.old_start == 1
        assert hunk.new_start == 1
        kinds = [line.kind for line in hunk.lines]
        assert "add" in kinds
        assert "remove" in kinds
        assert "context" in kinds

    def test_parse_multi_file_diff(self) -> None:
        from deepseek_tui.tui.widgets.diff_viewer import parse_unified_diff

        diff = """\
--- a/foo.py
+++ b/foo.py
@@ -1,2 +1,3 @@
 line1
+added
 line2
--- a/bar.py
+++ b/bar.py
@@ -1 +1 @@
-old
+new
"""
        files = parse_unified_diff(diff)
        assert len(files) == 2
        assert files[0].new_path == "foo.py"
        assert files[1].new_path == "bar.py"

    def test_render_diff_to_rich(self) -> None:
        from deepseek_tui.tui.widgets.diff_viewer import (
            parse_unified_diff,
            render_diff_to_rich,
        )

        files = parse_unified_diff(SAMPLE_DIFF)
        output = render_diff_to_rich(files)
        text_str = str(output)
        assert "src/main.py" in text_str
        assert "import sys" in text_str

    def test_render_diff_summary(self) -> None:
        from deepseek_tui.tui.widgets.diff_viewer import (
            parse_unified_diff,
            render_diff_summary,
        )

        files = parse_unified_diff(SAMPLE_DIFF)
        summary = render_diff_summary(files)
        text_str = str(summary)
        assert "1 file" in text_str

    def test_diff_line_numbers(self) -> None:
        from deepseek_tui.tui.widgets.diff_viewer import parse_unified_diff

        files = parse_unified_diff(SAMPLE_DIFF)
        hunk = files[0].hunks[0]
        add_lines = [ln for ln in hunk.lines if ln.kind == "add"]
        assert add_lines[0].new_line_no is not None
        assert add_lines[0].new_line_no >= 1

    def test_empty_diff(self) -> None:
        from deepseek_tui.tui.widgets.diff_viewer import parse_unified_diff

        files = parse_unified_diff("")
        assert files == []

    def test_diff_viewer_properties(self) -> None:
        from deepseek_tui.tui.widgets.diff_viewer import DiffViewer

        viewer = DiffViewer(SAMPLE_DIFF)
        viewer._diff_text = SAMPLE_DIFF
        from deepseek_tui.tui.widgets.diff_viewer import parse_unified_diff

        viewer._files = parse_unified_diff(SAMPLE_DIFF)
        assert viewer.file_count == 1
        assert viewer.total_additions == 2
        assert viewer.total_deletions == 1


# ===========================================================================
# Integration: imports and widget construction
# ===========================================================================


class TestWidgetImports:
    def test_all_widgets_importable(self) -> None:
        from deepseek_tui.tui.widgets import (
            ApprovalDialog,
            AssistantMarkdownCell,
            CommandPalette,
            Composer,
            DiffScreen,
            DiffViewer,
            FileMention,
            FilePicker,
            HelpPanel,
            MarkdownCell,
            MarkdownRenderer,
            ModelPicker,
            ModePicker,
            ProviderPicker,
            SessionPicker,
            Sidebar,
            SidebarEntry,
            SlashMenu,
            StatusBar,
            ToolCell,
            Transcript,
        )
        assert all([
            ApprovalDialog, AssistantMarkdownCell, CommandPalette,
            Composer, DiffScreen, DiffViewer, FileMention, FilePicker,
            HelpPanel, MarkdownCell, MarkdownRenderer, ModelPicker,
            ModePicker, ProviderPicker, SessionPicker, Sidebar,
            SidebarEntry, SlashMenu, StatusBar, ToolCell, Transcript,
        ])

    def test_app_composes_with_sidebar(self) -> None:
        from deepseek_tui.tui.app import DeepSeekTUI

        app = DeepSeekTUI()
        assert app is not None
        assert len(app.BINDINGS) >= 4
