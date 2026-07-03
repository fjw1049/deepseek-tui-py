"""Sidebar widgets — navigation, info, context inspector.
"""

from __future__ import annotations



# Sidebar widget — session/thread list panel.
#
# Provides a toggleable left-side panel listing recent sessions/threads
# with keyboard navigation, filtering, and session actions.
#
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from textual import on
from textual.binding import Binding
from textual.containers import Vertical
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Input, ListItem, ListView, Static
import re
from dataclasses import field
from rich.console import Group, RenderableType
from rich.markup import escape
from rich.panel import Panel
from rich.text import Text
from textual.containers import VerticalScroll
from pathlib import Path


@dataclass(slots=True)
class SidebarEntry:
    """A single session entry in the sidebar."""

    id: str
    name: str
    preview: str
    updated_at: int
    model: str = ""
    archived: bool = False

    @property
    def display_time(self) -> str:
        if self.updated_at == 0:
            return ""
        dt = datetime.fromtimestamp(self.updated_at, tz=timezone.utc)
        now = datetime.now(timezone.utc)
        delta = now - dt
        if delta.days == 0:
            return dt.strftime("%H:%M")
        if delta.days < 7:
            return f"{delta.days}d ago"
        return dt.strftime("%m/%d")


class _SessionItem(ListItem):
    """Single session list item."""

    DEFAULT_CSS = """
    _SessionItem {
        height: 3;
        padding: 0 1;
    }
    _SessionItem:hover {
        background: $boost;
    }
    _SessionItem.-selected {
        background: $accent 30%;
    }
    """

    def __init__(self, entry: SidebarEntry) -> None:
        super().__init__()
        self.entry = entry

    def compose(self):  # type: ignore[override]
        name = self.entry.name or self.entry.preview[:40] or self.entry.id[:8]
        time_str = self.entry.display_time
        yield Static(f"[bold]{name}[/] [dim]{time_str}[/]")
        if self.entry.model:
            yield Static(f"  [dim]{self.entry.model}[/]")


class Sidebar(Widget):
    """Toggleable session list sidebar."""

    DEFAULT_CSS = """
    Sidebar {
        width: 32;
        dock: left;
        background: $surface;
        border-right: solid $primary-background;
        display: none;
    }
    Sidebar.-visible {
        display: block;
    }
    Sidebar #sidebar-filter {
        height: 1;
        margin: 0 0 1 0;
    }
    Sidebar #sidebar-list {
        height: 1fr;
    }
    Sidebar #sidebar-header {
        height: 1;
        text-align: center;
        text-style: bold;
        color: $text;
        background: $primary-background;
    }
    Sidebar #sidebar-empty {
        height: 1fr;
        content-align: center middle;
        color: $text-muted;
    }
    """

    BINDINGS = [
        Binding("escape", "close_sidebar", "Close", show=False),
        Binding("d", "delete_session", "Delete", show=False),
        Binding("a", "archive_session", "Archive", show=False),
        Binding("r", "rename_session", "Rename", show=False),
    ]

    visible: reactive[bool] = reactive(False)
    filter_text: reactive[str] = reactive("")

    class SessionSelected(Message):
        """Emitted when a session is chosen."""

        def __init__(self, session_id: str) -> None:
            super().__init__()
            self.session_id = session_id

    class SessionDeleted(Message):
        """Emitted when a session is deleted."""

        def __init__(self, session_id: str) -> None:
            super().__init__()
            self.session_id = session_id

    class SessionArchived(Message):
        """Emitted when a session is archived/unarchived."""

        def __init__(self, session_id: str, archived: bool) -> None:
            super().__init__()
            self.session_id = session_id
            self.archived = archived

    def __init__(self) -> None:
        super().__init__()
        self._entries: list[SidebarEntry] = []
        self._filtered: list[SidebarEntry] = []

    def compose(self):  # type: ignore[override]
        with Vertical():
            yield Static("Sessions", id="sidebar-header")
            yield Input(placeholder="Filter...", id="sidebar-filter")
            yield ListView(id="sidebar-list")

    def toggle(self) -> None:
        self.visible = not self.visible

    def show_sidebar(self) -> None:
        self.visible = True

    def hide_sidebar(self) -> None:
        self.visible = False

    def watch_visible(self, value: bool) -> None:
        self.set_class(value, "-visible")

    def set_entries(self, entries: list[SidebarEntry]) -> None:
        self._entries = sorted(entries, key=lambda e: e.updated_at, reverse=True)
        self._apply_filter()

    def _apply_filter(self) -> None:
        query = self.filter_text.lower()
        if query:
            self._filtered = [
                e
                for e in self._entries
                if query in (e.name or "").lower()
                or query in e.preview.lower()
                or query in e.id.lower()
            ]
        else:
            self._filtered = list(self._entries)
        self._rebuild_list()

    def _rebuild_list(self) -> None:
        try:
            lv = self.query_one("#sidebar-list", ListView)
        except Exception:
            return
        lv.clear()
        for entry in self._filtered:
            lv.append(_SessionItem(entry))

    @on(Input.Changed, "#sidebar-filter")
    def _on_filter_changed(self, event: Input.Changed) -> None:
        self.filter_text = event.value
        self._apply_filter()

    @on(ListView.Selected, "#sidebar-list")
    def _on_session_selected(self, event: ListView.Selected) -> None:
        item = event.item
        if isinstance(item, _SessionItem):
            self.post_message(self.SessionSelected(item.entry.id))

    def action_close_sidebar(self) -> None:
        self.hide_sidebar()

    def action_delete_session(self) -> None:
        entry = self._get_highlighted_entry()
        if entry:
            self.post_message(self.SessionDeleted(entry.id))

    def action_archive_session(self) -> None:
        entry = self._get_highlighted_entry()
        if entry:
            self.post_message(self.SessionArchived(entry.id, not entry.archived))

    def action_rename_session(self) -> None:
        pass

    def _get_highlighted_entry(self) -> SidebarEntry | None:
        try:
            lv = self.query_one("#sidebar-list", ListView)
            idx = lv.index
            if idx is not None and 0 <= idx < len(self._filtered):
                return self._filtered[idx]
        except Exception:
            pass
        return None

    @staticmethod
    def from_thread_metadata(metadata_list: list[dict[str, Any]]) -> list[SidebarEntry]:
        """Convert raw thread metadata dicts to SidebarEntry list."""
        entries = []
        for m in metadata_list:
            entries.append(
                SidebarEntry(
                    id=m.get("id", ""),
                    name=m.get("name", "") or "",
                    preview=m.get("preview", "") or "",
                    updated_at=m.get("updated_at", 0),
                    model=m.get("model_provider", "") or "",
                    archived=m.get("archived_at") is not None
                    and m.get("archived_at") != 0,
                )
            )
        return entries


# Right-side info sidebar — Plan / Todos / Tasks / Agents live state.
#
# Each panel reads its data from a pre-fetched snapshot the app pushes
# in via :meth:`update_data`; the widget itself stays sync-only so it
# can be called from anywhere in the event loop without await.
#
# Layout (auto mode — empty panels collapse to zero height):
#
# ::
#
#     ┌────────────────────────────────────────┐
#     │ Plan                                   │  <- always visible
#     │ ◆ Implement auth middleware            │
#     │ cycles: 2 (active: 3)                  │
#     │ [x] 1. Design API schema              │
#     │ [~] 2. Write handlers                  │
#     ├────────────────────────────────────────┤
#     │ Todos                                  │  <- only if non-empty
#     │ 50%  complete (2/4)                    │
#     │ [x] #1 implement auth                 │
#     │ [~] #2 unit tests                     │
#     ├────────────────────────────────────────┤
#     │ Tasks                                  │  <- only if non-empty
#     │ 1 running                              │
#     │ task_3563ea15  running 4.1s            │
#     ├────────────────────────────────────────┤
#     │ Agents                                 │  <- only if non-empty
#     │ 2 agents (1 running)                   │
#     │ agent_a1b2  explore  done              │
#     └────────────────────────────────────────┘
#



@dataclass(slots=True)
class InfoSidebarData:
    """Snapshot pushed in by the app every time engine state changes.

    Each field is plain data (no async refs) so the widget can render
    without awaiting and without holding references to manager objects.
    """

    plan_steps: list[dict[str, Any]] = field(default_factory=list)
    plan_goal: str | None = None
    cycle_count: int = 0
    todos: list[dict[str, Any]] = field(default_factory=list)
    todos_completion_pct: int = 0
    todos_in_progress_id: int | None = None
    tasks: list[dict[str, Any]] = field(default_factory=list)
    agents: list[dict[str, Any]] = field(default_factory=list)


_ACTIVE_TASK_STATUSES = frozenset({"running", "queued"})
_ACTIVE_TODO_STATUSES = frozenset({"pending", "in_progress"})
_PLAN_STORE_KEY = "plan"


def reset_turn_sidebar_sources(metadata: dict[str, Any]) -> None:
    """Clear plan/todos when a new user turn starts."""
    store = metadata.get("todos")
    if isinstance(store, dict):
        store["items"] = []
        store["next_id"] = 1
    metadata[_PLAN_STORE_KEY] = {
        "goal": None,
        "explanation": None,
        "steps": [],
    }


def plan_snapshot_from_metadata(metadata: dict[str, Any]) -> tuple[str | None, list[dict[str, Any]]]:
    raw = metadata.get(_PLAN_STORE_KEY)
    if not isinstance(raw, dict):
        return None, []
    goal = raw.get("goal") or raw.get("explanation")
    steps = raw.get("steps")
    if not isinstance(steps, list):
        return (str(goal) if goal else None), []
    normalised: list[dict[str, Any]] = []
    for idx, step in enumerate(steps, start=1):
        if not isinstance(step, dict):
            continue
        title = step.get("title") or step.get("step") or ""
        if not str(title).strip():
            continue
        normalised.append(
            {
                "index": step.get("index", idx),
                "title": str(title),
                "status": step.get("status", "pending"),
            }
        )
    return (str(goal) if goal else None), normalised


def filter_sidebar_tasks(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Hide completed/canceled tasks — sidebar tracks live work only."""
    return [t for t in tasks if t.get("status") in _ACTIVE_TASK_STATUSES]


def filter_sidebar_todos(todos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Hide completed checklist items — sidebar tracks active work only."""
    return [t for t in todos if t.get("status") in _ACTIVE_TODO_STATUSES]


def filter_sidebar_agents(
    agents: list[dict[str, Any]], *, turn_agent_ids: set[str]
) -> list[dict[str, Any]]:
    """Show running agents plus agents spawned in the current user turn."""
    visible: list[dict[str, Any]] = []
    for agent in agents:
        aid = str(agent.get("agent_id", ""))
        status = str(agent.get("status", ""))
        if status == "running" or aid in turn_agent_ids:
            visible.append(agent)
    return visible[:5]


def _first_markdown_heading(text: str) -> str | None:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip() or None
    return None


def parse_plan_markdown(text: str) -> list[dict[str, Any]]:
    """Best-effort checklist parser for ``update_plan`` markdown bodies."""
    steps: list[dict[str, Any]] = []
    for line in text.splitlines():
        stripped = line.strip()
        match = re.match(r"^- \[( |x|X|~)\] (.+)$", stripped)
        if not match:
            continue
        mark, title = match.group(1), match.group(2).strip()
        if mark.lower() == "x":
            status = "completed"
        elif mark == "~":
            status = "in_progress"
        else:
            status = "pending"
        steps.append(
            {"index": len(steps) + 1, "title": title, "status": status}
        )
    return steps


def parse_structured_plan_steps(raw_steps: list[Any]) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    for idx, item in enumerate(raw_steps, start=1):
        if not isinstance(item, dict):
            continue
        title = item.get("step") or item.get("title") or ""
        if not str(title).strip():
            continue
        status = item.get("status", "pending")
        steps.append(
            {
                "index": idx,
                "title": str(title),
                "status": str(status),
            }
        )
    return steps


def sync_plan_store(
    metadata: dict[str, Any],
    *,
    explanation: str | None,
    plan_text: str | None = None,
    structured_steps: list[dict[str, Any]] | None = None,
) -> None:
    steps = structured_steps or (
        parse_plan_markdown(plan_text or "") if plan_text else []
    )
    goal = explanation or (_first_markdown_heading(plan_text or "") if plan_text else None)
    metadata[_PLAN_STORE_KEY] = {
        "goal": goal,
        "explanation": explanation,
        "steps": steps,
    }


class InfoSidebar(Widget):
    """Right-docked sidebar with Plan / Todos / Tasks / Agents panels."""

    DEFAULT_CSS = """
    InfoSidebar {
        width: 44;
        dock: right;
        background: $surface;
        padding: 0;
    }
    InfoSidebar.-hidden {
        display: none;
    }
    InfoSidebar .info-scroll {
        height: 1fr;
    }
    InfoSidebar .info-section {
        height: auto;
        padding: 0 1;
        margin: 0 0 1 0;
    }
    """

    visible: reactive[bool] = reactive(True)

    def __init__(self) -> None:
        super().__init__()
        self._data = InfoSidebarData()
        self._plan = Static("", classes="info-section")
        self._todos = Static("", classes="info-section")
        self._tasks = Static("", classes="info-section")
        self._agents = Static("", classes="info-section")

    def compose(self):  # type: ignore[override]
        with VerticalScroll(classes="info-scroll"):
            yield self._plan
            yield self._todos
            yield self._tasks
            yield self._agents

    def on_mount(self) -> None:
        self._refresh()

    def watch_visible(self, value: bool) -> None:
        self.set_class(not value, "-hidden")

    def toggle(self) -> None:
        self.visible = not self.visible

    def update_data(self, data: InfoSidebarData) -> None:
        self._data = data
        self._refresh()

    # --- rendering ---------------------------------------------------

    def _section(self, title: str, body: RenderableType, active: bool) -> Panel:
        return Panel(
            body,
            title=f"[bold bright_white]{title}[/]",
            title_align="left",
            border_style="bright_cyan" if active else "dim bright_black",
            padding=(1, 1),
            expand=True,
        )

    def _refresh(self) -> None:
        try:
            plan_body, plan_active = self._render_plan()
            self._plan.update(self._section("Plan", plan_body, plan_active))

            todos_body, todos_active = self._render_todos()
            self._todos.update(self._section("Todos", todos_body, todos_active))

            tasks_body, tasks_active = self._render_tasks()
            self._tasks.update(self._section("Tasks", tasks_body, tasks_active))

            agents_body, agents_active = self._render_agents()
            self._agents.update(self._section("Agents", agents_body, agents_active))
        except Exception:
            pass

    def _render_plan(self) -> tuple[Group, bool]:
        lines: list[Text] = []
        has_content = False

        if self._data.plan_goal:
            has_content = True
            goal = Text()
            goal.append("◆ ", style="bold bright_yellow")
            goal.append(self._data.plan_goal[:60], style="bold bright_yellow")
            lines.append(goal)

        if self._data.cycle_count > 0:
            has_content = True
            cyc = Text()
            cyc.append(
                f"cycles: {self._data.cycle_count} "
                f"(active: {self._data.cycle_count + 1})",
                style="dim bright_white",
            )
            lines.append(cyc)

        steps = self._data.plan_steps
        if steps:
            has_content = True
            if lines:
                lines.append(Text("─" * 24, style="dim bright_black"))
            for step in steps[:8]:
                status = step.get("status", "pending")
                glyph, colour = {
                    "completed": ("✓", "bright_green"),
                    "in_progress": ("→", "bright_yellow"),
                }.get(status, ("○", "dim bright_white"))
                idx = step.get("index", "")
                title = str(step.get("title", ""))
                row = Text()
                row.append(f" {glyph} ", style=colour)
                if idx:
                    row.append(f"{idx}. ", style="dim bright_white")
                row.append(escape(title[:40]), style=colour)
                lines.append(row)
            remaining = max(0, len(steps) - 8)
            if remaining:
                lines.append(Text(f"  +{remaining} more steps", style="dim italic bright_black"))

        if not has_content:
            lines.append(Text("💡 The model can use update_plan", style="dim italic bright_cyan"))
            lines.append(Text("   to show its strategy here", style="dim italic"))

        return Group(*lines), has_content

    def _render_todos(self) -> tuple[Group, bool]:
        items = self._data.todos
        if not items:
            return Group(Text("📝 No todos yet", style="dim italic bright_yellow")), False
        lines: list[Text] = []
        total = len(items)
        completed = sum(1 for i in items if i.get("status") == "completed")
        header = Text()
        header.append(f"{self._data.todos_completion_pct}%", style="bold bright_green")
        header.append(f"  complete ({completed}/{total})", style="dim bright_white")
        lines.append(header)
        for item in items[:6]:
            status = item.get("status", "pending")
            glyph, colour = {
                "completed": ("[✓]", "bright_green"),
                "in_progress": ("[→]", "bright_yellow"),
            }.get(status, ("[ ]", "bright_white"))
            content = str(item.get("content", ""))
            label = Text()
            label.append(glyph, style=colour)
            label.append(f" #{item.get('id', '?')} ", style="dim")
            label.append(escape(content), style=colour)
            lines.append(label)
        remaining = max(0, total - 6)
        if remaining:
            lines.append(Text(f"  +{remaining} more todos", style="dim italic bright_black"))
        return Group(*lines), True

    def _render_tasks(self) -> tuple[Group, bool]:
        tasks = self._data.tasks
        if not tasks:
            return Group(Text("⚙️  No tasks running", style="dim italic bright_magenta")), False
        running = sum(1 for t in tasks if t.get("status") == "running")
        queued = sum(1 for t in tasks if t.get("status") == "queued")
        header = Text()
        header.append(f"{len(tasks)} task(s)", style="bold bright_white")
        bits: list[str] = []
        if running:
            bits.append(f"{running} running")
        if queued:
            bits.append(f"{queued} queued")
        if bits:
            header.append(f"  ({', '.join(bits)})", style="dim bright_white")
        lines: list[Text] = [header]
        for task in tasks[:4]:
            status = task.get("status", "?")
            colour = {
                "queued": "bright_white",
                "running": "bright_yellow",
                "completed": "bright_green",
                "failed": "bright_red",
                "canceled": "dim",
            }.get(status, "bright_white")
            duration_ms = task.get("duration_ms")
            duration = (
                f"{duration_ms / 1000:.1f}s" if isinstance(duration_ms, int) else "-"
            )
            tid = str(task.get("id", "?"))[:12]
            row = Text()
            row.append(tid, style=colour)
            row.append("  ", style="dim")
            row.append(status, style=colour)
            row.append(f"  {duration}", style="dim bright_white")
            lines.append(row)
            preview = str(task.get("prompt_summary", "")).strip()
            if preview:
                lines.append(Text(f"  {escape(preview)[:36]}", style="dim italic"))
        return Group(*lines), True

    def _render_agents(self) -> tuple[Group, bool]:
        agents = self._data.agents
        if not agents:
            return Group(Text("🤖 No agents spawned", style="dim italic bright_blue")), False
        running = sum(1 for a in agents if a.get("status") == "running")
        header = Text()
        header.append(f"{len(agents)} agent(s)", style="bold bright_white")
        if running:
            header.append(f"  ({running} running)", style="dim bright_white")
        lines: list[Text] = [header]
        for agent in agents[:4]:
            aid = str(agent.get("agent_id", "?"))[:12]
            atype = str(agent.get("agent_type", "?"))
            status = str(agent.get("status", "?"))
            colour = {
                "running": "bright_yellow",
                "completed": "bright_green",
                "failed": "bright_red",
                "canceled": "dim",
            }.get(status, "bright_white")
            row = Text()
            row.append(aid, style=colour)
            row.append("  ", style="dim")
            row.append(atype, style="bright_cyan")
            row.append(f"  {status}", style=colour)
            lines.append(row)
        return Group(*lines), True


# Compact session-context inspector text renderer.
#
# Builds the textual snapshot rendered by the ``/context`` slash command.
# Rather than reaching deep into ``App`` state, this takes a small
# :class:`InspectorSnapshot` dataclass so unit tests don't need to spin up
# a Textual app and the engine layer can build the snapshot from whatever
# live state it has at the time.
#

from deepseek_tui.config.providers import context_window_for_model
from deepseek_tui.engine.context import (
    estimate_input_tokens_conservative,
    estimate_tokens,
)
from deepseek_tui.protocol.messages import Message

WORKING_SET_MARKER: str = "## Repo Working Set"
CONTEXT_WARNING_THRESHOLD_PERCENT: float = 85.0
CONTEXT_CRITICAL_THRESHOLD_PERCENT: float = 95.0
MAX_REFERENCE_ROWS: int = 12
MAX_TOOL_ROWS: int = 8


@dataclass(slots=True)
class ContextReferenceView:
    """A session context reference projected onto the inspector."""

    badge: str
    label: str
    target: str
    source: str = "at_mention"  # "at_mention" or "attachment"
    included: bool = True
    expanded: bool = False
    detail: str | None = None


@dataclass(slots=True)
class ToolDetailView:
    """A tool detail record projected onto the inspector."""

    tool_name: str
    tool_id: str
    output: str | None = None


@dataclass(slots=True)
class InspectorSnapshot:
    """Snapshot of the bits of app state the inspector renders."""

    model: str
    workspace: Path
    session_id: str | None = None
    history_cells: int = 0
    api_messages: list[Message] = field(default_factory=list)
    system_prompt: str | None = None
    system_prompt_blocks: list[str] | None = None
    workspace_context: str | None = None
    references: list[ContextReferenceView] = field(default_factory=list)
    active_tool_details: list[ToolDetailView] = field(default_factory=list)
    cell_tool_details: list[tuple[int, ToolDetailView]] = field(default_factory=list)


def build_context_inspector_text(snapshot: InspectorSnapshot) -> str:
    """Build the inspector text."""
    used, max_window, percent = _context_usage(snapshot)
    status = _context_status(percent)

    lines: list[str] = [
        "Session Context",
        "---------------",
        f"Model: {snapshot.model}",
        f"Workspace: {snapshot.workspace}",
    ]
    if snapshot.session_id:
        lines.append(f"Session: {snapshot.session_id}")
    lines.append(
        f"Context: {status} - ~{used}/{max_window} tokens ({percent:.1f}%)"
    )
    lines.append(
        f"Transcript: {snapshot.history_cells} cells, "
        f"{len(snapshot.api_messages)} API messages"
    )
    workspace_status = snapshot.workspace_context or "not sampled yet"
    lines.append(f"Workspace status: {workspace_status}")

    lines.append("")
    lines.extend(_system_prompt_structure(snapshot))
    lines.append("")
    lines.extend(_render_references(snapshot.references))
    lines.append("")
    lines.extend(_render_tools(snapshot))

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _context_usage(snapshot: InspectorSnapshot) -> tuple[int, int, float]:
    max_window = context_window_for_model(snapshot.model)
    estimated = estimate_input_tokens_conservative(
        snapshot.api_messages, snapshot.system_prompt
    )
    text_blob = "".join(
        getattr(block, "text", "") or ""
        for msg in snapshot.api_messages
        for block in msg.content
    )
    used = max(estimated, estimate_tokens(text_blob))
    percent = min(100.0, max(0.0, (used / max_window) * 100.0)) if max_window else 0.0
    return used, max_window, percent


def _context_status(percent: float) -> str:
    """Classify context usage percentage as ok/high/critical."""
    if percent >= CONTEXT_CRITICAL_THRESHOLD_PERCENT:
        return "critical"
    if percent >= CONTEXT_WARNING_THRESHOLD_PERCENT:
        return "high"
    return "ok"


def _text_tokens(text: str) -> int:
    return -(-len(text) // 3)  # ceil(len / 3)


def _system_prompt_structure(snapshot: InspectorSnapshot) -> list[str]:
    """Render the system prompt structure section."""
    out: list[str] = ["System Prompt Structure", "-----------------------"]

    blocks = snapshot.system_prompt_blocks
    text = snapshot.system_prompt

    if blocks:
        total_tokens = sum(_text_tokens(b) for b in blocks)
        working_idx = next(
            (i for i, b in enumerate(blocks) if WORKING_SET_MARKER in b),
            None,
        )
        stable_count = working_idx if working_idx is not None else len(blocks)
        stable_tokens = sum(_text_tokens(b) for b in blocks[:stable_count])
        out.append(
            f"  Stable prefix: {stable_count} block(s), ~{stable_tokens} tokens "
            "[cache-friendly]"
        )
        if working_idx is not None:
            block = blocks[working_idx]
            working_tokens = _text_tokens(block)
            out.append(
                f"  Volatile working set: 1 block, ~{working_tokens} tokens "
                "[changes every turn]"
            )
            first = block.splitlines()[0] if block.splitlines() else "(empty)"
            out.append(f"    First line: {first}")
        else:
            out.append("  Volatile working set: none")
        out.append(f"  Total: {len(blocks)} block(s), ~{total_tokens} tokens")
    elif text:
        total_tokens = _text_tokens(text)
        if WORKING_SET_MARKER in text:
            out.append(
                f"  Single text blob (~{total_tokens} tokens) "
                "[contains working-set marker — structure unclear]"
            )
        else:
            out.append(
                f"  Single text blob (~{total_tokens} tokens) "
                "[stable prefix only]"
            )
    else:
        out.append("  No system prompt set.")

    out.append(
        "  Tip: Stable prefix blocks are DeepSeek V4 prefix-cache eligible. "
        "Volatile working-set changes break the cache only for the tail."
    )
    return out


def _render_references(references: list[ContextReferenceView]) -> list[str]:
    """Render the references section."""
    out: list[str] = ["References", "----------"]
    seen: set[str] = set()
    rendered = 0
    total = len(references)
    for ref in references:
        key = f"{ref.source}:{ref.label}:{ref.target}"
        if key in seen:
            continue
        seen.add(key)
        if rendered >= MAX_REFERENCE_ROWS:
            remaining = total - rendered
            if remaining > 0:
                out.append(f"- ... {remaining} more reference(s)")
            break
        prefix = "@" if ref.source == "at_mention" else "/attach "
        if ref.included:
            state = "included" if ref.expanded else "attached"
        else:
            state = "not included"
        detail = ref.detail.strip() if ref.detail else ""
        suffix = f" - {detail}" if detail else ""
        out.append(
            f"- [{ref.badge}] {prefix}{ref.label} -> {ref.target} ({state}{suffix})"
        )
        rendered += 1
    if rendered == 0:
        out.append("- No file, directory, or media references recorded yet.")
    return out


def _render_tools(snapshot: InspectorSnapshot) -> list[str]:
    """Render the recent tools section."""
    out: list[str] = ["Recent Tools", "------------"]
    rendered = 0
    for detail in snapshot.active_tool_details:
        out.append(_tool_row("active", detail))
        rendered += 1
        if rendered >= MAX_TOOL_ROWS:
            return out
    rows = sorted(snapshot.cell_tool_details, key=lambda x: x[0], reverse=True)
    for cell_idx, detail in rows[: MAX_TOOL_ROWS - rendered]:
        out.append(_tool_row(f"cell {cell_idx}", detail))
        rendered += 1
    if rendered == 0:
        out.append("- No tool activity recorded yet.")
    else:
        out.append("- Open the matching card and press Alt+V for full details.")
    return out


def _tool_row(location: str, detail: ToolDetailView) -> str:
    output_state = "output captured" if detail.output else "no output yet"
    short = detail.tool_id if len(detail.tool_id) <= 8 else detail.tool_id[:8] + "..."
    return f"- [{location}] {detail.tool_name} {short} ({output_state})"
