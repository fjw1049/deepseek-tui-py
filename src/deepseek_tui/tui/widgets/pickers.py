"""Picker widgets — model, mode, and file selection.

Mirrors Rust ``tui/model_picker.rs`` + ``tui/mode_picker.rs``
+ file picker functionality (~800 LOC combined).
Implemented as Textual ModalScreen overlays with filterable lists.
"""

from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, ListItem, ListView, Static

# ===========================================================================
# Base FilterablePicker
# ===========================================================================


class _FilterablePickerScreen(ModalScreen[str | None]):
    """Base class for picker modals with filtering."""

    DEFAULT_CSS = """
    _FilterablePickerScreen {
        align: center middle;
    }
    _FilterablePickerScreen > Vertical {
        width: 60;
        max-width: 80%;
        height: 60%;
        max-height: 20;
        background: $surface;
        border: thick $primary;
        padding: 1 2;
    }
    _FilterablePickerScreen .picker-title {
        text-style: bold;
        text-align: center;
        margin-bottom: 1;
    }
    _FilterablePickerScreen #picker-filter {
        height: 1;
        margin-bottom: 1;
    }
    _FilterablePickerScreen #picker-list {
        height: 1fr;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel_picker", "Cancel"),
    ]

    def __init__(self, title: str, items: list[tuple[str, str]]) -> None:
        """items: list of (value, display_label)"""
        super().__init__()
        self._title = title
        self._items = items
        self._filtered = list(items)

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(f"[bold]{self._title}[/]", classes="picker-title")
            yield Input(placeholder="Type to filter...", id="picker-filter")
            yield ListView(id="picker-list")

    def on_mount(self) -> None:
        self._rebuild()
        self.query_one("#picker-filter", Input).focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "picker-filter":
            query = event.value.lower()
            if query:
                self._filtered = [
                    (v, label)
                    for v, label in self._items
                    if query in label.lower() or query in v.lower()
                ]
            else:
                self._filtered = list(self._items)
            self._rebuild()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        item = event.item
        if hasattr(item, "value"):
            self.dismiss(item.value)  # type: ignore[attr-defined]

    def action_cancel_picker(self) -> None:
        self.dismiss(None)

    def _rebuild(self) -> None:
        try:
            lv = self.query_one("#picker-list", ListView)
        except Exception:
            return
        lv.clear()
        for value, label in self._filtered:
            item = _PickerItem(value, label)
            lv.append(item)


class _PickerItem(ListItem):
    """A single selectable item in a picker."""

    def __init__(self, value: str, label: str) -> None:
        super().__init__()
        self.value = value
        self._label = label

    def compose(self):  # type: ignore[override]
        yield Static(self._label)


# ===========================================================================
# ModelPicker
# ===========================================================================

AVAILABLE_MODELS: list[tuple[str, str]] = [
    ("deepseek-chat", "DeepSeek V3 (default)"),
    ("deepseek-reasoner", "DeepSeek R1 (reasoning)"),
    ("deepseek-coder", "DeepSeek Coder V2"),
]


class ModelPicker(_FilterablePickerScreen):
    """Pick an LLM model."""

    def __init__(self, models: list[tuple[str, str]] | None = None) -> None:
        items = models or AVAILABLE_MODELS
        super().__init__("Select Model", items)


# ===========================================================================
# ModePicker
# ===========================================================================

AVAILABLE_MODES: list[tuple[str, str]] = [
    ("agent", "Agent — autonomous tool use (default)"),
    ("plan", "Plan — read-only analysis, no edits"),
    ("yolo", "YOLO — auto-approve everything"),
    ("ask", "Ask — answer questions only"),
    ("goal", "Goal — objective-driven with progress tracking"),
    ("workflow", "Workflow — multi-phase structured execution"),
]


class ModePicker(_FilterablePickerScreen):
    """Pick an interaction mode."""

    def __init__(self, modes: list[tuple[str, str]] | None = None) -> None:
        items = modes or AVAILABLE_MODES
        super().__init__("Select Mode", items)


# ===========================================================================
# FilePicker
# ===========================================================================


class FilePicker(_FilterablePickerScreen):
    """Pick a file from the workspace."""

    def __init__(
        self,
        workspace: Path | None = None,
        *,
        max_files: int = 500,
        glob_pattern: str = "**/*",
        exclude_dirs: set[str] | None = None,
    ) -> None:
        ws = workspace or Path.cwd()
        excludes = exclude_dirs or {
            ".git",
            "__pycache__",
            "node_modules",
            ".venv",
            "venv",
            ".tox",
            ".mypy_cache",
            ".ruff_cache",
            "dist",
            "build",
            ".egg-info",
        }
        items = _collect_files(ws, max_files, glob_pattern, excludes)
        super().__init__("Select File", items)


def _collect_files(
    workspace: Path,
    max_files: int,
    glob_pattern: str,
    excludes: set[str],
) -> list[tuple[str, str]]:
    """Collect files for the picker, respecting exclusions."""
    items: list[tuple[str, str]] = []
    try:
        for path in sorted(workspace.rglob("*")):
            if len(items) >= max_files:
                break
            if not path.is_file():
                continue
            parts = path.relative_to(workspace).parts
            if any(p in excludes for p in parts):
                continue
            rel = str(path.relative_to(workspace))
            items.append((rel, rel))
    except (OSError, ValueError):
        pass
    return items


# ===========================================================================
# ProviderPicker — select API provider
# ===========================================================================

AVAILABLE_PROVIDERS: list[tuple[str, str]] = [
    ("deepseek", "DeepSeek (api.deepseek.com)"),
    ("openai", "OpenAI-compatible endpoint"),
    ("anthropic", "Anthropic Claude"),
    ("local", "Local / Ollama"),
]


class ProviderPicker(_FilterablePickerScreen):
    """Pick an API provider."""

    def __init__(self, providers: list[tuple[str, str]] | None = None) -> None:
        items = providers or AVAILABLE_PROVIDERS
        super().__init__("Select Provider", items)


# ===========================================================================
# SessionPicker — for switching sessions (Rust session_picker.rs, 671 LOC)
# ===========================================================================


class SessionPicker(_FilterablePickerScreen):
    """Pick from a list of sessions."""

    def __init__(self, sessions: list[tuple[str, str]]) -> None:
        super().__init__("Select Session", sessions)
