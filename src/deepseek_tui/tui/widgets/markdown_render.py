"""Markdown rich-text rendering widget.

Mirrors Rust ``tui/markdown_render.rs`` (~559 LOC) + integration into Transcript.
Provides streaming-capable markdown rendering with syntax highlighting for
code blocks, tables, links, and inline formatting.

Uses Textual's built-in Markdown widget as the base renderer with custom
extensions for streaming updates and DeepSeek-specific rendering.
"""

from __future__ import annotations

import re

from rich.markdown import Markdown as RichMarkdown
from rich.panel import Panel
from rich.style import Style
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text
from textual.widgets import Static

# ===========================================================================
# MarkdownRenderer — streaming markdown to Rich renderables
# ===========================================================================


class MarkdownRenderer:
    """Converts markdown text to Rich-renderable output.

    Designed for streaming: call ``update(text)`` as new content arrives,
    then ``render()`` to get the current Rich renderable.
    """

    def __init__(self, *, theme: str = "monokai") -> None:
        self._text: str = ""
        self._theme = theme
        self._finalized = False

    @property
    def text(self) -> str:
        return self._text

    def update(self, text: str) -> None:
        self._text = text

    def append(self, delta: str) -> None:
        self._text += delta

    def finalize(self) -> None:
        self._finalized = True

    def render(self) -> RichMarkdown | Text:
        """Return a Rich renderable for the current content."""
        if not self._text.strip():
            return Text("")
        try:
            return RichMarkdown(self._text, code_theme=self._theme)
        except Exception:
            return Text(self._text)

    def render_with_cursor(self) -> Text | RichMarkdown:
        """Render with a blinking cursor for streaming."""
        if self._finalized:
            return self.render()
        if not self._text.strip():
            return Text("▌", style="blink")
        try:
            md = RichMarkdown(self._text + " ▌", code_theme=self._theme)
            return md
        except Exception:
            return Text(self._text + " ▌")


# ===========================================================================
# Code block extraction and rendering
# ===========================================================================

_CODE_BLOCK_RE = re.compile(
    r"```(\w+)?\n(.*?)```", re.DOTALL
)

_INLINE_CODE_RE = re.compile(r"`([^`]+)`")


def extract_code_blocks(text: str) -> list[dict[str, str]]:
    """Extract fenced code blocks from markdown text."""
    blocks = []
    for match in _CODE_BLOCK_RE.finditer(text):
        lang = match.group(1) or "text"
        code = match.group(2).rstrip("\n")
        blocks.append({"language": lang, "code": code})
    return blocks


def render_code_block(code: str, language: str = "text") -> Syntax:
    """Render a code block with syntax highlighting."""
    return Syntax(
        code,
        language,
        theme="monokai",
        line_numbers=True,
        word_wrap=True,
    )


def render_code_block_panel(code: str, language: str = "text", title: str = "") -> Panel:
    """Render a code block inside a panel with optional title."""
    syntax = render_code_block(code, language)
    panel_title = title or language
    return Panel(syntax, title=panel_title, border_style="dim")


# ===========================================================================
# Table rendering
# ===========================================================================

_TABLE_ROW_RE = re.compile(r"^\|(.+)\|$", re.MULTILINE)
_TABLE_SEP_RE = re.compile(r"^\|[-:|]+\|$", re.MULTILINE)


def render_markdown_table(text: str) -> Table | None:
    """Parse a simple markdown table and return a Rich Table, or None if invalid."""
    lines = text.strip().splitlines()
    if len(lines) < 2:
        return None

    rows: list[list[str]] = []
    sep_idx: int | None = None
    for i, line in enumerate(lines):
        line = line.strip()
        if not line.startswith("|") or not line.endswith("|"):
            continue
        cells = [c.strip() for c in line.split("|")[1:-1]]
        if _TABLE_SEP_RE.match(line):
            sep_idx = i
            continue
        rows.append(cells)

    if not rows:
        return None

    headers = rows[0] if sep_idx == 1 or sep_idx is None else rows[0]
    data = rows[1:] if len(rows) > 1 else []

    table = Table(show_header=True, header_style="bold", border_style="dim")
    for h in headers:
        table.add_column(h)
    for row in data:
        while len(row) < len(headers):
            row.append("")
        table.add_row(*row[:len(headers)])

    return table


# ===========================================================================
# Link and reference rendering
# ===========================================================================

_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")


def extract_links(text: str) -> list[tuple[str, str]]:
    """Extract [text](url) links from markdown."""
    return _LINK_RE.findall(text)


def render_link(text: str, url: str) -> Text:
    """Render a clickable link with Rich markup."""
    link_text = Text(text, style=Style(color="cyan", underline=True, link=url))
    return link_text


# ===========================================================================
# Heading rendering
# ===========================================================================


def render_heading(text: str, level: int) -> Text:
    """Render a markdown heading."""
    prefix = "#" * level + " "
    styles = {
        1: Style(bold=True, color="bright_white"),
        2: Style(bold=True, color="cyan"),
        3: Style(bold=True, color="green"),
    }
    style = styles.get(level, Style(bold=True))
    return Text(prefix + text, style=style)


# ===========================================================================
# Blockquote rendering
# ===========================================================================


def render_blockquote(text: str) -> Panel:
    """Render a blockquote."""
    return Panel(
        Text(text, style="italic"),
        border_style="dim green",
        padding=(0, 1),
    )


# ===========================================================================
# Diff-aware markdown rendering
# ===========================================================================


def has_diff_block(text: str) -> bool:
    """Check if text contains a diff code block."""
    return "```diff" in text


# ===========================================================================
# MarkdownCell — Textual widget for rendering markdown in transcript
# ===========================================================================


class MarkdownCell(Static):
    """A Textual Static widget that renders markdown content using Rich."""

    DEFAULT_CSS = """
    MarkdownCell {
        margin: 0 0 1 0;
    }
    """

    def __init__(self, initial_text: str = "") -> None:
        super().__init__("")
        self._renderer = MarkdownRenderer()
        if initial_text:
            self._renderer.update(initial_text)
            self._refresh_display()

    def append(self, delta: str) -> None:
        """Append streaming delta."""
        self._renderer.append(delta)
        self._refresh_display()

    def set_content(self, text: str) -> None:
        """Replace all content."""
        self._renderer.update(text)
        self._refresh_display()

    def finalize(self) -> None:
        """Mark as complete (remove cursor)."""
        self._renderer.finalize()
        self._refresh_display()

    def _refresh_display(self) -> None:
        renderable = self._renderer.render_with_cursor()
        self.update(renderable)


# ===========================================================================
# AssistantMarkdownCell — assistant response with markdown rendering
# ===========================================================================


class AssistantMarkdownCell(Static):
    """Displays assistant response with full markdown rendering (live-updating).

    Drop-in replacement for the plain-text _AssistantCell with Rich Markdown.
    """

    DEFAULT_CSS = """
    AssistantMarkdownCell {
        margin: 0 0 1 0;
    }
    """

    def __init__(self) -> None:
        super().__init__("")
        self._buffer: str = ""
        self._finalized: bool = False

    def append(self, text: str) -> None:
        self._buffer += text
        self._refresh()

    def finalize(self) -> None:
        self._finalized = True
        self._refresh()

    @property
    def content_text(self) -> str:
        return self._buffer

    def _refresh(self) -> None:
        if not self._buffer.strip():
            cursor = "" if self._finalized else "▌"
            self.update(f"[bold green]Assistant:[/] {cursor}")
            return
        try:
            cursor = "" if self._finalized else " ▌"
            md = RichMarkdown(self._buffer + cursor, code_theme="monokai")
            self.update(md)
        except Exception:
            cursor = "" if self._finalized else "[blink]▌[/]"
            self.update(f"[bold green]Assistant:[/] {self._buffer}{cursor}")


# ===========================================================================
# Utility: estimate render height
# ===========================================================================


def estimate_rendered_height(text: str, width: int = 80) -> int:
    """Estimate how many terminal lines the rendered markdown will occupy."""
    lines = text.count("\n") + 1
    long_lines = sum(1 for line in text.splitlines() if len(line) > width)
    return lines + long_lines
