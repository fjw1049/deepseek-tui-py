"""Right-side info sidebar — Plan / Todos / Tasks / Agents live state.

Mirrors Rust ``crates/tui/src/tui/sidebar.rs::render_sidebar_auto``.
Each panel reads its data from a pre-fetched snapshot the app pushes
in via :meth:`update_data`; the widget itself stays sync-only so it
can be called from anywhere in the event loop without await.

Layout (auto mode — empty panels collapse to zero height):

::

    ┌────────────────────────────────────────┐
    │ Plan                                   │  <- always visible
    │ ◆ Implement auth middleware            │
    │ cycles: 2 (active: 3)                  │
    │ [x] 1. Design API schema              │
    │ [~] 2. Write handlers                  │
    ├────────────────────────────────────────┤
    │ Todos                                  │  <- only if non-empty
    │ 50%  complete (2/4)                    │
    │ [x] #1 implement auth                 │
    │ [~] #2 unit tests                     │
    ├────────────────────────────────────────┤
    │ Tasks                                  │  <- only if non-empty
    │ 1 running                              │
    │ task_3563ea15  running 4.1s            │
    ├────────────────────────────────────────┤
    │ Agents                                 │  <- only if non-empty
    │ 2 agents (1 running)                   │
    │ agent_a1b2  explore  done              │
    └────────────────────────────────────────┘
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from rich.console import Group, RenderableType
from rich.markup import escape
from rich.panel import Panel
from rich.text import Text
from textual.containers import VerticalScroll
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static


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
