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

from deepseek_tui.tui.widgets.diff_viewer import (
    parse_unified_diff,
    render_diff_to_rich,
)
from deepseek_tui.tui.widgets.pager import PagerScreen

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
