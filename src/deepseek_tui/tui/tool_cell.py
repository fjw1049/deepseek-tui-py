"""Tool cell and diff viewer widgets.
"""

from __future__ import annotations



# ======================================================================
# From tool_cell.py
# ======================================================================

"""Tool call cell — Rust-style structured tool card.

Renders a single tool execution with:

- header line: status bullet + family glyph + verb + state ± elapsed
- args summary on a ``▏ `` dim gutter (first non-empty value, 56 chars max)
- head/tail output preview (click to expand to full)
- unified diff content routed through diff_viewer's renderer

Mirrors the Rust ``ToolCell`` rendering in
``crates/tui/src/tui/history.rs`` (functions ``render_tool_header`` and
``render_card_detail_line``). External content (tool_name / args /
result) always passes through ``rich.markup.escape`` to keep the
2026-05-11 markup-injection regression closed
(``tests/parity/phase_e/test_markup_escape.py``).
"""

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

_DETAIL_RAIL = "▏"
_TOOL_HEADER_SUMMARY_LIMIT = 56
_PREVIEW_LINE_LIMIT = 12

# Family glyph + verb per tool name. Glyphs follow the Rust catalog in
# ``crates/tui/src/tui/widgets/tool_card.rs`` (▷ read, ◆ patch, ▶ run,
# ⌕ search, ☰ list, ◈ git, ◇ generic). Verb is a short lowercase label.
_TOOL_GLYPHS: dict[str, tuple[str, str]] = {
    "read_file": ("▷", "read"),
    "write_file": ("◆", "write"),
    "edit_file": ("◆", "patch"),
    "apply_patch": ("◆", "patch"),
    "multi_edit": ("◆", "patch"),
    "exec_shell": ("▶", "run"),
    "exec_shell_cancel": ("⊘", "stop"),
    "exec_shell_wait": ("◷", "wait"),
    "exec_shell_interact": ("▶", "run"),
    "grep_files": ("⌕", "search"),
    "file_search": ("⌕", "search"),
    "list_dir": ("☰", "ls"),
    "project_map": ("☰", "map"),
    "web_search": ("⌕", "web"),
    "fetch_url": ("⇣", "fetch"),
}


def _classify(tool_name: str) -> tuple[str, str]:
    """Pick (glyph, verb) for ``tool_name``."""
    if tool_name in _TOOL_GLYPHS:
        return _TOOL_GLYPHS[tool_name]
    if tool_name.startswith("git_"):
        return ("◈", "git")
    if tool_name.startswith("task_"):
        return ("◇", "task")
    if tool_name.startswith("agent_"):
        return ("◇", "agent")
    if tool_name.startswith("github_"):
        return ("◇", "github")
    return ("◇", tool_name)


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
    """Sample head + tail. Returns (visible_lines, omitted_count).

    When omission applies, the literal ``"…"`` marker line is inserted
    between head and tail so the renderer can style it specially.
    """
    lines = text.splitlines()
    if len(lines) <= max_lines:
        return lines, 0
    half = max_lines // 2
    head = lines[:half]
    tail = lines[-half:]
    omitted = len(lines) - len(head) - len(tail)
    return [*head, "…", *tail], omitted


class ToolCell(Static):
    """One tool call as a structured card."""

    DEFAULT_CSS = "ToolCell { margin: 0 0 1 0; }"
    # ``o`` opens the full tool output in a PagerScreen modal so long
    # tool results (head/tail-truncated by ``_head_tail_preview``) can be
    # read in full with vim-style scrolling + search. Mirrors Rust
    # ``pager.rs`` keymap. The cell must be focusable for the binding to
    # fire; clicking the cell focuses it (Textual default) and the user
    # then presses ``o``.
    can_focus = True
    BINDINGS = [
        Binding("o", "open_pager", "Open in pager", show=False),
    ]

    def __init__(
        self,
        tool_name: str,
        tool_call_id: str,
        arguments: dict[str, object] | None = None,
    ) -> None:
        super().__init__("")
        self.tool_name = tool_name
        self.tool_call_id = tool_call_id
        self._arguments: dict[str, object] = dict(arguments) if arguments else {}
        # Status: ``running`` | ``awaiting`` | ``done`` | ``failed`` |
        # ``denied``. Each maps to a distinct bullet + colour below.
        self._status: str = "running"
        self._result: str = ""
        self._started_at: float = time.monotonic()
        self._finished_at: float | None = None
        # Folding state: collapsed → header only (no args, no body);
        # expanded → full layout. Default is expanded so the user sees
        # what the tool returned without an extra click, and they can
        # click the header to hide noisy results from history.
        self._collapsed: bool = False
        self._refresh()

    def set_result(self, content: str, success: bool) -> None:
        self._status = "done" if success else "failed"
        self._result = content
        self._finished_at = time.monotonic()
        # Auto-collapse on completion so the final assistant message
        # stays the visual focus. The user can click the header to
        # re-expand and inspect args + output.
        self._collapsed = True
        self._refresh()

    def set_awaiting_approval(self) -> None:
        """Mark the cell as paused waiting on user approval."""
        self._status = "awaiting"
        self._refresh()

    def set_approved(self) -> None:
        """User approved; resume running state (cell will stay
        ``running`` until the engine emits a result)."""
        if self._status == "awaiting":
            self._status = "running"
        self._refresh()

    def set_denied(self, reason: str = "") -> None:
        """User (or sandbox policy) denied the call. Terminal state."""
        self._status = "denied"
        if reason:
            self._result = reason
        self._finished_at = time.monotonic()
        self._collapsed = True
        self._refresh()

    def on_click(self, event: events.Click) -> None:  # type: ignore[override]
        """Toggle collapsed / expanded for the *entire* tool block.

        Replaces the older "expand the truncated tail" affordance: that
        action was easy to miss and gave a third hidden state. Now a
        click always toggles between "header only" and "full preview"
        — the user has one consistent gesture for hiding noisy tool
        output from the transcript history.
        """
        self._collapsed = not self._collapsed
        self._refresh()

    def action_open_pager(self) -> None:
        """Push a ``PagerScreen`` modal with the full tool output.

        Bound to the ``o`` key (Rust pager parity). No-op when the tool
        hasn't produced output yet, so an empty modal doesn't pop over
        a still-running call.
        """
        if not self._result:
            return
        lines = self._result.splitlines() or [self._result]
        title = f"{self.tool_name} · {self._status}"
        self.app.push_screen(PagerScreen(title=title, lines=lines))

    def _elapsed_str(self) -> str:
        if self._finished_at is None:
            return ""
        secs = max(0.0, self._finished_at - self._started_at)
        if secs < 0.1:
            return ""
        return f" · {secs:.1f}s"

    def _status_bullet(self) -> str:
        return {
            "running": "·",
            "awaiting": "?",
            "done": "•",
            "failed": "✗",
            "denied": "⊘",
        }.get(self._status, "·")

    def _state_color(self) -> str:
        return {
            "running": "yellow",
            "awaiting": "yellow",
            "done": "green",
            "failed": "red",
            "denied": "red",
        }.get(self._status, "yellow")

    def _state_label(self) -> str:
        return {
            "awaiting": "awaiting approval",
        }.get(self._status, self._status)

    def _header_markup(self, *, compact_detail: str | None = None) -> str:
        glyph, verb = _classify(self.tool_name)
        if _is_compact_delegate_tool(self.tool_name):
            glyph, verb = "◐", "delegate"
        bullet = self._status_bullet()
        color = self._state_color()
        elapsed = self._elapsed_str()
        label = self._state_label()
        detail = compact_detail or escape(self.tool_name)
        # Tiny ▸/▾ caret hints folding state — only shown when there's
        # actually a body to hide / reveal, otherwise it's noise.
        if self._has_body() and not _is_compact_delegate_tool(self.tool_name):
            caret = "▸" if self._collapsed else "▾"
            caret_part = f"[dim]{caret}[/] "
        else:
            caret_part = ""
        return (
            f"{caret_part}"
            f"[{color}]{bullet}[/] "
            f"[bold]{escape(glyph)}[/] "
            f"[bold]{escape(verb)}[/] "
            f"[white]{detail}[/] "
            f"[{color}]· {label}{elapsed}[/]"
        )

    def _compact_delegate_header(self) -> str | None:
        """Single-line spawn/result header; DelegateCard owns the live tree (#409)."""
        if not _is_compact_delegate_tool(self.tool_name):
            return None
        agent_id = _extract_agent_id(self._result)
        if agent_id is None and self._arguments:
            for key in ("agent_id", "id"):
                value = self._arguments.get(key)
                if isinstance(value, str) and value.strip():
                    agent_id = value.strip()
                    break
        detail = agent_id or "…"
        if len(detail) > 12:
            detail = detail[:12]
        return self._header_markup(compact_detail=detail)

    def _has_body(self) -> bool:
        return bool(self._arguments) or bool(self._result)

    def _refresh(self) -> None:
        compact = self._compact_delegate_header()
        if compact is not None:
            self.update(compact)
            return

        header = self._header_markup()
        # Collapsed state: header line only, optionally a hint about
        # how much is hidden so the user doesn't lose the fact that
        # there was output.
        if self._collapsed and self._has_body():
            hint_parts: list[str] = []
            if self._arguments:
                hint_parts.append("args")
            if self._result:
                line_count = len(self._result.splitlines()) or 1
                hint_parts.append(f"{line_count} line(s) output")
            hint = " · ".join(hint_parts)
            self.update(f"{header}  [dim italic](hidden: {hint})[/]")
            return

        lines: list[str] = [header]
        summary = _summarize_args(self._arguments)
        if summary:
            lines.append(f"[dim]{_DETAIL_RAIL} {escape(summary)}[/]")

        if self._result and _looks_like_diff(self._result):
            self.update(self._render_with_diff(lines, self._result))
            return

        if self._result:
            preview_lines, omitted = _head_tail_preview(self._result)
            for line in preview_lines:
                if line == "…":
                    lines.append(f"[dim]{_DETAIL_RAIL} …[/]")
                else:
                    lines.append(f"[dim]{_DETAIL_RAIL} {escape(line)}[/]")
            if omitted > 0:
                lines.append(
                    f"[dim italic]{_DETAIL_RAIL} … {omitted} line(s) "
                    f"truncated[/]"
                )

        self.update("\n".join(lines))

    def _render_with_diff(
        self, header_lines: list[str], diff_text: str
    ) -> RenderableType:
        """Compose header markup + parsed unified diff renderable."""
        header = Text.from_markup("\n".join(header_lines))
        files = parse_unified_diff(diff_text)
        if not files:
            preview_lines, omitted = _head_tail_preview(diff_text)
            body_markup = "\n".join(
                f"[dim]{_DETAIL_RAIL} {escape(line) if line != '…' else '…'}[/]"
                for line in preview_lines
            )
            if omitted > 0:
                body_markup += (
                    f"\n[dim italic]{_DETAIL_RAIL} … {omitted} more line(s); "
                    f"click to expand[/]"
                )
            return Text.from_markup("\n".join(header_lines) + "\n" + body_markup)
        diff_body = render_diff_to_rich(files, line_numbers=True)
        return _Group(header, diff_body)


# ======================================================================
# From diff_viewer.py
# ======================================================================

"""Diff viewer widget — renders unified diffs with color coding.

Mirrors Rust ``tui/diff_render.rs`` (~449 LOC).
Parses unified diff format and renders with Rich styling:
- Added lines: green
- Removed lines: red
- Hunk headers: cyan
- Context lines: dim
"""


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
