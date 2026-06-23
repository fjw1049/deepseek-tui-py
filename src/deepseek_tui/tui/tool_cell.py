"""Tool cell widgets — InlineToolCell (single-line) + BlockToolCell (panel).

Dual-mode tool display inspired by opencode's InlineTool / BlockTool split:

- **InlineToolCell**: Compact single-line for read-only tools (grep, read, ls, git).
  Consecutive inline cells stack with zero margin for visual density.
- **BlockToolCell**: Panel with left border for mutation tools (edit, write, shell).
  Shows expandable content (diff, output) with breathing room.

Both cells share the same status lifecycle:
  running → awaiting → done/failed/denied

External content always passes through ``rich.markup.escape``.
"""

from __future__ import annotations

import json
import re
import time

from rich.console import Group as _Group
from rich.console import RenderableType
from rich.markup import escape
from rich.text import Text
from textual import events
from textual.binding import Binding
from textual.widgets import Static

from deepseek_tui.tui.cards import PagerScreen
from deepseek_tui.tui.tool_classify import ToolDisplay, classify_tool

_DETAIL_RAIL = "▏"
_TOOL_HEADER_SUMMARY_LIMIT = 56
_PREVIEW_LINE_LIMIT = 10

# ── Agent ID extraction (shared) ─────────────────────────────────────

_COMPACT_DELEGATE_TOOLS = frozenset(
    {"agent_spawn", "delegate_to_agent", "spawn_agent", "agent_result", "agent_wait"}
)
_SPAWNED_ID_RE = re.compile(r"spawned\s+(\S+)")


def _extract_agent_id(result: str) -> str | None:
    text = (result or "").strip()
    if not text:
        return None
    spawned = _SPAWNED_ID_RE.search(text)
    if spawned:
        return spawned.group(1)
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None
    if isinstance(parsed, dict):
        agent_id = parsed.get("agent_id")
        if isinstance(agent_id, str) and agent_id.strip():
            return agent_id.strip()
    return None


def _is_compact_delegate_tool(tool_name: str) -> bool:
    return tool_name in _COMPACT_DELEGATE_TOOLS


# ── Shared helpers ────────────────────────────────────────────────────


def _looks_like_diff(text: str) -> bool:
    if not text:
        return False
    head = text.splitlines()[:8]
    has_hunk = any(line.startswith("@@") and "@@" in line[2:] for line in head)
    has_file = any(
        line.startswith(("--- ", "+++ ", "diff --git ")) for line in head
    )
    return has_hunk and has_file


def _summarize_args(arguments: dict[str, object] | None) -> str | None:
    """1-line ≤56-char summary of the first meaningful argument value."""
    if not arguments:
        return None
    for value in arguments.values():
        if value is None:
            continue
        s = str(value).strip()
        if not s:
            continue
        s = s.splitlines()[0]
        if len(s) > _TOOL_HEADER_SUMMARY_LIMIT:
            s = s[: _TOOL_HEADER_SUMMARY_LIMIT - 1] + "…"
        return s
    return None


def _head_tail_preview(
    text: str, *, max_lines: int = _PREVIEW_LINE_LIMIT
) -> tuple[list[str], int]:
    """Sample head + tail. Returns (visible_lines, omitted_count)."""
    lines = text.splitlines()
    if len(lines) <= max_lines:
        return lines, 0
    half = max_lines // 2
    head = lines[:half]
    tail = lines[-half:]
    omitted = len(lines) - len(head) - len(tail)
    return [*head, "…", *tail], omitted


def _elapsed_str(started: float, finished: float | None) -> str:
    if finished is None:
        return ""
    secs = max(0.0, finished - started)
    if secs < 0.1:
        return ""
    return f" · {secs:.1f}s"


def _status_bullet(status: str) -> str:
    return {
        "running": "·",
        "awaiting": "?",
        "done": "•",
        "failed": "✗",
        "denied": "⊘",
    }.get(status, "·")


def _state_color(status: str) -> str:
    return {
        "running": "yellow",
        "awaiting": "yellow",
        "done": "dim",
        "failed": "red",
        "denied": "red",
    }.get(status, "yellow")


# ======================================================================
# InlineToolCell — single-line compact display
# ======================================================================


class InlineToolCell(Static):
    """Single-line tool cell for read-only / lightweight operations.

    Visual states:
      pending:  ~ verb summary...
      running:  [yellow]· icon verb summary[/]
      done:     [dim]icon verb summary · elapsed[/]
      failed:   [red]✗ icon verb summary — error[/]
      denied:   [strikethrough dim]⊘ verb summary[/]
    """

    DEFAULT_CSS = "InlineToolCell { margin: 0; padding: 0 0 0 3; }"

    def __init__(
        self,
        tool_name: str,
        tool_call_id: str,
        arguments: dict[str, object] | None = None,
        *,
        display: ToolDisplay | None = None,
    ) -> None:
        super().__init__("")
        self.tool_name = tool_name
        self.tool_call_id = tool_call_id
        self._arguments: dict[str, object] = dict(arguments) if arguments else {}
        self._display = display or classify_tool(tool_name)
        self._status: str = "running"
        self._result: str = ""
        self._started_at: float = time.monotonic()
        self._finished_at: float | None = None
        self._refresh()

    @property
    def cell_type(self) -> str:
        return "inline"

    def set_result(self, content: str, success: bool) -> None:
        self._status = "done" if success else "failed"
        self._result = content
        self._finished_at = time.monotonic()
        self._refresh()

    def set_awaiting_approval(self) -> None:
        self._status = "awaiting"
        self._refresh()

    def set_approved(self) -> None:
        if self._status == "awaiting":
            self._status = "running"
        self._refresh()

    def set_denied(self, reason: str = "") -> None:
        self._status = "denied"
        if reason:
            self._result = reason
        self._finished_at = time.monotonic()
        self._refresh()

    def _format_summary(self) -> str:
        """Build the display string from args (path, pattern, command, etc.)."""
        summary = _summarize_args(self._arguments)
        if summary:
            return escape(summary)
        return escape(self.tool_name)

    def _refresh(self) -> None:
        icon = self._display.icon
        verb = self._display.verb
        summary = self._format_summary()
        elapsed = _elapsed_str(self._started_at, self._finished_at)
        color = _state_color(self._status)
        bullet = _status_bullet(self._status)

        if self._status == "running":
            self.update(f"[{color}]{bullet} {icon} {verb}[/] {summary}")
        elif self._status == "awaiting":
            self.update(f"[{color}]{bullet} {icon} {verb}[/] {summary} [yellow]· awaiting approval[/]")
        elif self._status == "done":
            self.update(f"[dim]{icon} {verb} {summary}{elapsed}[/]")
        elif self._status == "failed":
            err_preview = escape(self._result.splitlines()[0][:60]) if self._result else "error"
            self.update(f"[{color}]{bullet} {icon} {verb} {summary} — {err_preview}[/]")
        elif self._status == "denied":
            self.update(f"[dim strikethrough]{icon} {verb} {summary}[/]")
        else:
            self.update(f"[{color}]{bullet} {icon} {verb}[/] {summary}")


# ======================================================================
# BlockToolCell — panel with left border + expandable content
# ======================================================================


class BlockToolCell(Static):
    """Panel-style tool cell for mutation operations (edit, write, shell).

    Renders with a left border character and padded content area.
    Content is expandable/collapsible on click.
    """

    DEFAULT_CSS = """
    BlockToolCell {
        margin: 0;
        padding: 0 0 0 1;
        border-left: thick $accent;
    }
    """

    can_focus = True
    BINDINGS = [
        Binding("o", "open_pager", "Open in pager", show=False),
    ]

    def __init__(
        self,
        tool_name: str,
        tool_call_id: str,
        arguments: dict[str, object] | None = None,
        *,
        display: ToolDisplay | None = None,
    ) -> None:
        super().__init__("")
        self.tool_name = tool_name
        self.tool_call_id = tool_call_id
        self._arguments: dict[str, object] = dict(arguments) if arguments else {}
        self._display = display or classify_tool(tool_name, has_output=True)
        self._status: str = "running"
        self._result: str = ""
        self._started_at: float = time.monotonic()
        self._finished_at: float | None = None
        self._collapsed: bool = False
        self._refresh()

    @property
    def cell_type(self) -> str:
        return "block"

    def set_result(self, content: str, success: bool) -> None:
        self._status = "done" if success else "failed"
        self._result = content
        self._finished_at = time.monotonic()
        self._collapsed = True
        self._refresh()

    def set_awaiting_approval(self) -> None:
        self._status = "awaiting"
        self._refresh()

    def set_approved(self) -> None:
        if self._status == "awaiting":
            self._status = "running"
        self._refresh()

    def set_denied(self, reason: str = "") -> None:
        self._status = "denied"
        if reason:
            self._result = reason
        self._finished_at = time.monotonic()
        self._collapsed = True
        self._refresh()

    def on_click(self, event: events.Click) -> None:  # type: ignore[override]
        self._collapsed = not self._collapsed
        self._refresh()

    def action_open_pager(self) -> None:
        if not self._result:
            return
        lines = self._result.splitlines() or [self._result]
        title = f"{self.tool_name} · {self._status}"
        self.app.push_screen(PagerScreen(title=title, lines=lines))

    def _header_markup(self) -> str:
        icon = self._display.icon
        verb = self._display.verb
        summary = _summarize_args(self._arguments) or self.tool_name
        summary = escape(summary)
        color = _state_color(self._status)
        bullet = _status_bullet(self._status)
        elapsed = _elapsed_str(self._started_at, self._finished_at)

        # Delegate tools: show agent_id from result and use "delegate" verb
        if _is_compact_delegate_tool(self.tool_name) and self._result:
            agent_id = _extract_agent_id(self._result)
            if agent_id:
                short_id = agent_id[:13]
                summary = escape(f"{short_id} [{summary}]")
                verb = "delegate"

        # Fold caret
        has_body = bool(self._result)
        if has_body:
            caret = "▸" if self._collapsed else "▾"
            caret_part = f"[dim]{caret}[/] "
        else:
            caret_part = ""

        if self._status == "done":
            return (
                f"{caret_part}[dim]{bullet}[/] "
                f"[bold]{icon}[/] [bold]{verb}[/] "
                f"[white]{summary}[/] "
                f"[dim]· done{elapsed}[/]"
            )
        return (
            f"{caret_part}[{color}]{bullet}[/] "
            f"[bold]{icon}[/] [bold]{verb}[/] "
            f"[white]{summary}[/] "
            f"[{color}]· {self._status}{elapsed}[/]"
        )

    def _refresh(self) -> None:
        header = self._header_markup()

        if self._collapsed and self._result:
            line_count = len(self._result.splitlines()) or 1
            self.update(f"{header}  [dim italic]({line_count} lines)[/]")
            return

        if not self._result:
            self.update(header)
            return

        # Expanded: show content
        if _looks_like_diff(self._result):
            self.update(self._render_with_diff(header))
            return

        lines: list[str] = [header]
        preview_lines, omitted = _head_tail_preview(self._result)
        for line in preview_lines:
            if line == "…":
                lines.append(f"  [dim]…[/]")
            else:
                lines.append(f"  [dim]{escape(line)}[/]")
        if omitted > 0:
            lines.append(f"  [dim italic]… {omitted} more line(s)[/]")
        self.update("\n".join(lines))

    def _render_with_diff(self, header: str) -> RenderableType:
        header_text = Text.from_markup(header)
        files = parse_unified_diff(self._result)
        if not files:
            preview_lines, omitted = _head_tail_preview(self._result)
            body = "\n".join(
                f"  [dim]{escape(line) if line != '…' else '…'}[/]"
                for line in preview_lines
            )
            return Text.from_markup(header + "\n" + body)
        diff_body = render_diff_to_rich(files, line_numbers=True)
        return _Group(header_text, diff_body)


# ======================================================================
# Legacy ToolCell alias — preserves import compatibility
# ======================================================================

# The old ToolCell is now BlockToolCell. Existing code that imports
# ``from deepseek_tui.tui.tool_cell import ToolCell`` continues to work.
ToolCell = BlockToolCell


# ======================================================================
# From diff_viewer.py — Diff parsing and rendering
# ======================================================================

"""Diff viewer widget — renders unified diffs with color coding.

Mirrors Rust ``tui/diff_render.rs`` (~449 LOC).
Parses unified diff format and renders with Rich styling:
- Added lines: green
- Removed lines: red
- Hunk headers: cyan
- Context lines: dim
"""

from dataclasses import dataclass, field

from rich.style import Style
from textual.containers import VerticalScroll

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
