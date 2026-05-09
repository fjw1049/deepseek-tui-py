"""Diff viewer widget — renders unified diffs with color coding.

Mirrors Rust ``tui/diff_render.rs`` (~449 LOC).
Parses unified diff format and renders with Rich styling:
- Added lines: green
- Removed lines: red
- Hunk headers: cyan
- Context lines: dim
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from rich.style import Style
from rich.text import Text
from textual.containers import VerticalScroll
from textual.widgets import Static

# ===========================================================================
# Diff parsing
# ===========================================================================

_HUNK_HEADER_RE = re.compile(
    r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)$"
)
_DIFF_FILE_OLD_RE = re.compile(r"^--- (.+)$")
_DIFF_FILE_NEW_RE = re.compile(r"^\+\+\+ (.+)$")


@dataclass(slots=True)
class DiffLine:
    """A single line in a diff."""

    kind: str  # "add", "remove", "context", "hunk_header", "file_header"
    content: str
    old_line_no: int | None = None
    new_line_no: int | None = None


@dataclass(slots=True)
class DiffHunk:
    """A single hunk in a diff."""

    header: str
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines: list[DiffLine] = field(default_factory=list)


@dataclass(slots=True)
class DiffFile:
    """A single file's diff."""

    old_path: str
    new_path: str
    hunks: list[DiffHunk] = field(default_factory=list)

    @property
    def additions(self) -> int:
        return sum(
            1 for h in self.hunks for line in h.lines if line.kind == "add"
        )

    @property
    def deletions(self) -> int:
        return sum(
            1 for h in self.hunks for line in h.lines if line.kind == "remove"
        )


def parse_unified_diff(diff_text: str) -> list[DiffFile]:
    """Parse unified diff text into structured DiffFile objects."""
    files: list[DiffFile] = []
    current_file: DiffFile | None = None
    current_hunk: DiffHunk | None = None
    old_line = 0
    new_line = 0

    for raw_line in diff_text.splitlines():
        old_match = _DIFF_FILE_OLD_RE.match(raw_line)
        if old_match:
            old_path = old_match.group(1)
            if old_path.startswith("a/"):
                old_path = old_path[2:]
            current_file = DiffFile(old_path=old_path, new_path="")
            continue

        new_match = _DIFF_FILE_NEW_RE.match(raw_line)
        if new_match and current_file is not None:
            new_path = new_match.group(1)
            if new_path.startswith("b/"):
                new_path = new_path[2:]
            current_file.new_path = new_path
            files.append(current_file)
            continue

        hunk_match = _HUNK_HEADER_RE.match(raw_line)
        if hunk_match:
            if current_file is None:
                current_file = DiffFile(old_path="unknown", new_path="unknown")
                files.append(current_file)
            old_start = int(hunk_match.group(1))
            old_count = int(hunk_match.group(2) or "1")
            new_start = int(hunk_match.group(3))
            new_count = int(hunk_match.group(4) or "1")
            current_hunk = DiffHunk(
                header=raw_line,
                old_start=old_start,
                old_count=old_count,
                new_start=new_start,
                new_count=new_count,
            )
            if current_file is not None:
                current_file.hunks.append(current_hunk)
            old_line = old_start
            new_line = new_start
            continue

        if current_hunk is None:
            continue

        if raw_line.startswith("+"):
            current_hunk.lines.append(
                DiffLine(
                    kind="add",
                    content=raw_line[1:],
                    new_line_no=new_line,
                )
            )
            new_line += 1
        elif raw_line.startswith("-"):
            current_hunk.lines.append(
                DiffLine(
                    kind="remove",
                    content=raw_line[1:],
                    old_line_no=old_line,
                )
            )
            old_line += 1
        elif raw_line.startswith(" "):
            current_hunk.lines.append(
                DiffLine(
                    kind="context",
                    content=raw_line[1:],
                    old_line_no=old_line,
                    new_line_no=new_line,
                )
            )
            old_line += 1
            new_line += 1
        elif raw_line.startswith("\\"):
            current_hunk.lines.append(
                DiffLine(kind="context", content=raw_line)
            )

    return files


# ===========================================================================
# Rich rendering
# ===========================================================================

STYLE_ADD = Style(color="green")
STYLE_REMOVE = Style(color="red")
STYLE_HUNK = Style(color="cyan", bold=True)
STYLE_CONTEXT = Style(dim=True)
STYLE_FILE_HEADER = Style(color="bright_white", bold=True)
STYLE_STATS = Style(dim=True)


def render_diff_to_rich(files: list[DiffFile], *, line_numbers: bool = True) -> Text:
    """Render parsed diff files into a Rich Text object."""
    output = Text()

    for file_idx, diff_file in enumerate(files):
        if file_idx > 0:
            output.append("\n")

        path_display = diff_file.new_path or diff_file.old_path
        stats = f" (+{diff_file.additions} -{diff_file.deletions})"
        output.append(f"{'─' * 4} {path_display}", style=STYLE_FILE_HEADER)
        output.append(stats, style=STYLE_STATS)
        output.append("\n")

        for hunk in diff_file.hunks:
            output.append(hunk.header + "\n", style=STYLE_HUNK)

            for line in hunk.lines:
                if line_numbers:
                    old_no = f"{line.old_line_no or '':<4}"
                    new_no = f"{line.new_line_no or '':<4}"
                    gutter = f"{old_no}│{new_no}│"
                else:
                    gutter = ""

                if line.kind == "add":
                    output.append(f"{gutter}+{line.content}\n", style=STYLE_ADD)
                elif line.kind == "remove":
                    output.append(f"{gutter}-{line.content}\n", style=STYLE_REMOVE)
                else:
                    output.append(f"{gutter} {line.content}\n", style=STYLE_CONTEXT)

    return output


def render_diff_summary(files: list[DiffFile]) -> Text:
    """Render a compact summary of the diff."""
    output = Text()
    total_add = sum(f.additions for f in files)
    total_del = sum(f.deletions for f in files)
    output.append(
        f"{len(files)} file(s) changed, "
        f"+{total_add} insertions, -{total_del} deletions\n",
        style=STYLE_STATS,
    )
    for f in files:
        path = f.new_path or f.old_path
        output.append(f"  {path} ", style=STYLE_FILE_HEADER)
        if f.additions:
            output.append("+" * min(f.additions, 20), style=STYLE_ADD)
        if f.deletions:
            output.append("-" * min(f.deletions, 20), style=STYLE_REMOVE)
        output.append("\n")
    return output


# ===========================================================================
# DiffViewer Textual Widget
# ===========================================================================


class DiffViewer(VerticalScroll):
    """Scrollable diff viewer widget for the TUI."""

    DEFAULT_CSS = """
    DiffViewer {
        height: 1fr;
        overflow-y: auto;
        padding: 0 1;
        background: $surface;
    }
    DiffViewer .diff-summary {
        margin-bottom: 1;
    }
    DiffViewer .diff-content {
        margin: 0;
    }
    """

    def __init__(self, diff_text: str = "") -> None:
        super().__init__()
        self._diff_text = diff_text
        self._files: list[DiffFile] = []
        self._show_line_numbers = True

    def on_mount(self) -> None:
        if self._diff_text:
            self.set_diff(self._diff_text)

    def set_diff(self, diff_text: str) -> None:
        """Parse and display a unified diff."""
        self._diff_text = diff_text
        self._files = parse_unified_diff(diff_text)
        self._render()

    def toggle_line_numbers(self) -> None:
        """Toggle line number display."""
        self._show_line_numbers = not self._show_line_numbers
        self._render()

    def _render(self) -> None:
        try:
            self.remove_children()
        except Exception:
            pass

        if not self._files:
            self.mount(Static("[dim]No diff content[/]"))
            return

        summary = render_diff_summary(self._files)
        self.mount(Static(summary, classes="diff-summary"))

        content = render_diff_to_rich(self._files, line_numbers=self._show_line_numbers)
        self.mount(Static(content, classes="diff-content"))

    @property
    def file_count(self) -> int:
        return len(self._files)

    @property
    def total_additions(self) -> int:
        return sum(f.additions for f in self._files)

    @property
    def total_deletions(self) -> int:
        return sum(f.deletions for f in self._files)


# ===========================================================================
# DiffScreen — full-screen diff modal
# ===========================================================================


class DiffScreen(Static):
    """Inline diff display widget for embedding in transcript."""

    DEFAULT_CSS = """
    DiffScreen {
        margin: 0 0 1 0;
        padding: 0 1;
    }
    """

    def __init__(self, diff_text: str, *, compact: bool = False) -> None:
        super().__init__("")
        self._diff_text = diff_text
        self._compact = compact

    def on_mount(self) -> None:
        files = parse_unified_diff(self._diff_text)
        if self._compact:
            renderable = render_diff_summary(files)
        else:
            renderable = render_diff_to_rich(files, line_numbers=True)
        self.update(renderable)
