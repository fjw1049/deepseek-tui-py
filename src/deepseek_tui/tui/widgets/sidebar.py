"""Sidebar widget — session/thread list panel.

Mirrors Rust ``tui/sidebar.rs`` (~770 LOC).
Provides a toggleable left-side panel listing recent sessions/threads
with keyboard navigation, filtering, and session actions.
"""

from __future__ import annotations

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
