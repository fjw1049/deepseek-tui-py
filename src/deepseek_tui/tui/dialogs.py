"""Dialog widgets — approval, pickers, help, file mention.
"""

from __future__ import annotations

from dataclasses import dataclass, field



# Approval modal — surfaces impacts and command preview before approval.
from rich.markup import escape
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Label, Static
from pathlib import Path
from textual.widgets import Input, ListItem, ListView
from textual.containers import VerticalScroll
import os
from textual.message import Message
from textual.widgets import OptionList
from textual.widgets.option_list import Option


class ApprovalDialog(ModalScreen[bool]):
    """Modal dialog for tool execution approval."""

    CSS = """
    ApprovalDialog {
        align: center middle;
    }
    ApprovalDialog #approval-box {
        width: 80;
        max-width: 90%;
        height: auto;
        border: thick $accent;
        padding: 1 2;
        background: $surface;
    }
    ApprovalDialog #approval-cmd {
        margin: 1 0;
        padding: 0 1;
        background: $boost;
        color: $text;
        border: round $primary;
        height: auto;
        max-height: 12;
    }
    ApprovalDialog #approval-confirm {
        margin: 1 0;
        color: $warning;
    }
    ApprovalDialog #approval-buttons {
        margin-top: 1;
        align: center middle;
        height: 3;
    }
    ApprovalDialog #approval-buttons > Button {
        margin: 0 1;
    }
    """

    BINDINGS = [
        Binding("enter", "approve", "Approve", show=False),
        Binding("escape", "deny", "Deny", show=False),
        Binding("y", "approve", "Approve", show=False),
        Binding("n", "deny", "Deny", show=False),
    ]

    def __init__(
        self,
        tool_name: str,
        reason: str,
        input_summary: str = "",
        risk_level: str = "",
        *,
        title: str = "",
        impacts: list[str] | None = None,
        presentation_risk: str = "",
        primary_preview: str = "",
    ) -> None:
        super().__init__()
        self.tool_name = tool_name
        self.reason = reason
        self.title = title or reason
        self.impacts = impacts or []
        self.presentation_risk = presentation_risk
        preview = (primary_preview or input_summary or "").strip()
        self.input_summary = preview
        self.risk_level = risk_level
        self._pending_confirm = False

    def _is_destructive(self) -> bool:
        return self.presentation_risk == "destructive"

    def compose(self) -> ComposeResult:
        with Vertical(id="approval-box"):
            header = "[bold]Approve tool call?[/]"
            if self._is_destructive():
                header = "[bold yellow]Review required[/]"
            yield Label(header)
            if self.title and self.title != self.reason:
                yield Label(f"[dim]Summary:[/] {escape(self.title)}")
            yield Label(f"[dim]Tool:[/]    [bold]{escape(self.tool_name)}[/]")
            if self.risk_level:
                yield Label(f"[dim]Risk:[/]    [yellow]{escape(self.risk_level)}[/]")
            for line in self.impacts[:8]:
                yield Label(f"  • {escape(line)}")
            if self.reason and not self.reason.startswith("tool has "):
                yield Label(f"[dim]Note:[/]    {escape(self.reason)}")
            if self.input_summary:
                yield Label("[dim]Preview:[/]")
                yield Static(escape(self.input_summary), id="approval-cmd")
            yield Label("", id="approval-confirm")
            with Horizontal(id="approval-buttons"):
                yield Button(
                    "Approve  (Enter / y)", variant="success", id="approve"
                )
                yield Button("Deny  (Esc / n)", variant="error", id="deny")

    def on_mount(self) -> None:
        self._sync_confirm_banner()

    def _sync_confirm_banner(self) -> None:
        try:
            banner = self.query_one("#approval-confirm", Label)
        except Exception:  # noqa: BLE001
            return
        if self._pending_confirm and self._is_destructive():
            banner.update(
                "[bold yellow]Confirm destructive action — press Approve again[/]"
            )
        else:
            banner.update("")

    def _try_approve(self) -> None:
        if self._is_destructive() and not self._pending_confirm:
            self._pending_confirm = True
            self._sync_confirm_banner()
            return
        self.dismiss(True)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "approve":
            self._try_approve()
        else:
            self._pending_confirm = False
            self.dismiss(False)

    def action_approve(self) -> None:
        self._try_approve()

    def action_deny(self) -> None:
        self._pending_confirm = False
        self.dismiss(False)


# Picker widgets — model, mode, and file selection.
#
# Implemented as Textual ModalScreen overlays with filterable lists.
#


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


def _build_model_list_from_config(config: object | None) -> list[tuple[str, str]]:
    """Build a dynamic model list from config.providers + PROVIDER_DEFAULTS.

    Any provider with a configured model appears in the picker.
    Falls back to AVAILABLE_MODELS if config is unavailable.
    """
    from deepseek_tui.config.providers import PROVIDER_DEFAULTS

    seen: set[str] = set()
    items: list[tuple[str, str]] = []

    # 1. User-configured providers (highest priority)
    if config is not None and hasattr(config, "providers"):
        for name, pc in config.providers.items():
            model = getattr(pc, "model", None)
            if model and model not in seen:
                seen.add(model)
                items.append((model, f"{model} ({name})"))

    # 2. PROVIDER_DEFAULTS (known providers not yet in user config)
    for name, defaults in PROVIDER_DEFAULTS.items():
        if defaults.model and defaults.model not in seen:
            seen.add(defaults.model)
            items.append((defaults.model, f"{defaults.model} ({name})"))
        if defaults.flash_model and defaults.flash_model not in seen:
            seen.add(defaults.flash_model)
            items.append((defaults.flash_model, f"{defaults.flash_model} ({name} flash)"))

    # 3. Fallback
    if not items:
        return AVAILABLE_MODELS

    return items


class ModelPicker(_FilterablePickerScreen):
    """Pick an LLM model."""

    def __init__(self, models: list[tuple[str, str]] | None = None) -> None:
        items = models or AVAILABLE_MODELS
        super().__init__("Select Model", items)


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


def _build_provider_list_from_config(config: object | None) -> list[tuple[str, str]]:
    """Build a dynamic provider list from config.providers + PROVIDER_DEFAULTS."""
    from deepseek_tui.config.providers import PROVIDER_DEFAULTS

    seen: set[str] = set()
    items: list[tuple[str, str]] = []

    # 1. User-configured providers
    if config is not None and hasattr(config, "providers"):
        for name, pc in config.providers.items():
            if name not in seen:
                seen.add(name)
                url = getattr(pc, "base_url", None) or ""
                label = f"{name} ({url})" if url else name
                items.append((name, label))

    # 2. Known defaults not already in user config
    for name, defaults in PROVIDER_DEFAULTS.items():
        if name not in seen:
            seen.add(name)
            items.append((name, f"{name} ({defaults.base_url})"))

    if not items:
        return AVAILABLE_PROVIDERS
    return items


class ProviderPicker(_FilterablePickerScreen):
    """Pick an API provider."""

    def __init__(self, providers: list[tuple[str, str]] | None = None) -> None:
        items = providers or AVAILABLE_PROVIDERS
        super().__init__("Select Provider", items)


# ===========================================================================
# SessionPicker — for switching sessions
# ===========================================================================


class SessionPicker(_FilterablePickerScreen):
    """Pick from a list of sessions."""

    def __init__(self, sessions: list[tuple[str, str]]) -> None:
        super().__init__("Select Session", sessions)


# Help / keybinds panel.
#
# Provides a modal overlay showing all keybindings and available commands,
# with section grouping and scrollable content.
#

KEYBIND_SECTIONS: list[tuple[str, list[tuple[str, str]]]] = [
    (
        "General",
        [
            ("Ctrl+C", "Quit application"),
            ("Ctrl+N", "New session"),
            ("Ctrl+K", "Command palette"),
            ("Ctrl+B", "Toggle sidebar"),
            ("?", "Show this help"),
            ("Escape", "Close panel / cancel"),
        ],
    ),
    (
        "Navigation",
        [
            ("↑ / ↓", "Scroll transcript"),
            ("Page Up / Page Down", "Scroll page"),
            ("Home / End", "Jump to top / bottom"),
            ("Tab", "Next focusable widget"),
            ("Shift+Tab", "Previous focusable widget"),
        ],
    ),
    (
        "Composer",
        [
            ("Enter", "Send message"),
            ("Ctrl+Enter", "New line"),
            ("↑", "Previous history entry"),
            ("↓", "Next history entry"),
            ("/", "Slash command (when empty)"),
            ("@", "File mention"),
        ],
    ),
    (
        "Sidebar",
        [
            ("Enter", "Open session"),
            ("d", "Delete session"),
            ("a", "Archive / unarchive"),
            ("r", "Rename session"),
            ("Escape", "Close sidebar"),
        ],
    ),
    (
        "During Response",
        [
            ("Ctrl+C", "Cancel current turn"),
            ("Ctrl+Z", "Interrupt and undo"),
        ],
    ),
    (
        "Pickers",
        [
            ("↑ / ↓", "Navigate options"),
            ("Enter", "Select"),
            ("Escape", "Cancel"),
            ("Type", "Filter options"),
        ],
    ),
]


class HelpPanel(ModalScreen[None]):
    """Full-screen modal showing keybindings and help."""

    DEFAULT_CSS = """
    HelpPanel {
        align: center middle;
    }
    HelpPanel > VerticalScroll {
        width: 70;
        max-width: 90%;
        height: 80%;
        background: $surface;
        border: thick $primary;
        padding: 1 2;
    }
    HelpPanel .help-title {
        text-align: center;
        text-style: bold;
        color: $text;
        margin-bottom: 1;
    }
    HelpPanel .help-section {
        text-style: bold;
        color: $accent;
        margin-top: 1;
    }
    HelpPanel .help-binding {
        margin-left: 2;
    }
    HelpPanel .help-footer {
        text-align: center;
        color: $text-muted;
        margin-top: 1;
    }
    """

    BINDINGS = [
        Binding("escape", "dismiss_help", "Close"),
        Binding("q", "dismiss_help", "Close"),
        Binding("question_mark", "dismiss_help", "Close"),
    ]

    def compose(self) -> ComposeResult:
        with VerticalScroll():
            yield Static("[bold]Keybindings & Help[/]", classes="help-title")
            for section_name, bindings in KEYBIND_SECTIONS:
                yield Static(f"[bold]{section_name}[/]", classes="help-section")
                for key, desc in bindings:
                    yield Static(
                        f"  [cyan]{key:<20}[/] {desc}",
                        classes="help-binding",
                    )
            yield Static("")
            yield _SlashCommandHelp()
            yield Static(
                "[dim]Press Escape or ? to close[/]", classes="help-footer"
            )

    def action_dismiss_help(self) -> None:
        self.dismiss(None)


class _SlashCommandHelp(Static):
    """Shows available slash commands in the help panel."""

    def __init__(self) -> None:
        super().__init__("")

    def on_mount(self) -> None:
        try:
            from deepseek_tui.tui.commands import REGISTRY

            lines = ["[bold]Slash Commands[/]\n"]
            for entry in REGISTRY:
                lines.append(f"  [green]{entry.name:<16}[/] {entry.description}")
            self.update("\n".join(lines))
        except Exception:
            self.update("[dim]Slash commands unavailable[/]")


# @file mention autocomplete.
#
# Stage 6.6: Detects ``@`` in the composer input and shows a file
# completion popup. Files are listed from the working directory.
#



class FileMention(Vertical):
    """Popup for @file autocomplete suggestions."""

    class Selected(Message):
        def __init__(self, path: str) -> None:
            super().__init__()
            self.path = path

    DEFAULT_CSS = """
    FileMention {
        dock: bottom;
        height: auto;
        max-height: 10;
        border: tall $accent;
        background: $surface;
        display: none;
    }
    FileMention.visible {
        display: block;
    }
    """

    def __init__(self, working_directory: Path | None = None) -> None:
        super().__init__()
        self._cwd = working_directory or Path.cwd()

    def compose(self) -> ComposeResult:
        yield Static("[bold]Files[/]")
        yield OptionList(id="file-list")

    def show(self, prefix: str = "") -> None:
        """Show file suggestions matching the prefix after ``@``."""
        query = prefix.lstrip("@")
        try:
            option_list = self.query_one("#file-list", OptionList)
            option_list.clear_options()
            matches = self._find_files(query)
            for path in matches[:20]:
                option_list.add_option(Option(path, id=path))
        except Exception:
            pass
        self.add_class("visible")

    def hide(self) -> None:
        self.remove_class("visible")

    def _find_files(self, query: str) -> list[str]:
        """List files in working directory matching the query prefix."""
        results: list[str] = []
        query_lower = query.lower()
        try:
            for entry in os.scandir(self._cwd):
                if entry.name.startswith("."):
                    continue
                name = entry.name
                if query_lower and not name.lower().startswith(query_lower):
                    continue
                if entry.is_dir():
                    results.append(f"{name}/")
                else:
                    results.append(name)
        except OSError:
            pass
        results.sort()
        return results

    def on_option_list_option_selected(
        self, event: OptionList.OptionSelected
    ) -> None:
        if event.option.id:
            self.post_message(self.Selected(event.option.id))
        self.hide()


# ======================================================================
# User input request
# ======================================================================

@dataclass(slots=True)
class UserInputDialogState:
    """Pure multi-question state used by :class:`UserInputDialog`."""

    questions: list[dict[str, object]]
    index: int = 0
    answers: list[dict[str, str]] = field(default_factory=list)

    @property
    def current(self) -> dict[str, object] | None:
        if 0 <= self.index < len(self.questions):
            return self.questions[self.index]
        return None

    def answer(self, value: str) -> bool:
        question = self.current
        cleaned = value.strip()
        if question is None or not cleaned:
            return False
        question_id = str(question.get("id") or f"question_{self.index + 1}")
        self.answers.append({"question_id": question_id, "value": cleaned})
        self.index += 1
        return self.current is None

    def response(self) -> dict[str, object]:
        return {"answers": list(self.answers)}


class UserInputDialog(ModalScreen[dict[str, object] | None]):
    """Interactive option/free-text dialog for model-requested user input."""

    CSS = """
    UserInputDialog { align: center middle; }
    UserInputDialog #user-input-box {
        width: 80;
        max-width: 90%;
        height: auto;
        max-height: 28;
        border: thick $accent;
        padding: 1 2;
        background: $surface;
    }
    UserInputDialog #user-input-options { height: auto; max-height: 12; }
    UserInputDialog #user-input-custom { margin-top: 1; }
    """

    BINDINGS = [Binding("escape", "cancel", "Cancel", show=False)]

    def __init__(self, questions: list[dict[str, object]]) -> None:
        super().__init__()
        self.state = UserInputDialogState(list(questions))
        self._option_values: list[str] = []

    def compose(self) -> ComposeResult:
        with Vertical(id="user-input-box"):
            yield Static("[bold bright_cyan]Input required[/]", id="user-input-title")
            yield Static("", id="user-input-question")
            yield OptionList(id="user-input-options")
            yield Input(
                placeholder="Type a custom answer and press Enter",
                id="user-input-custom",
            )
            yield Static(
                "[dim]Select an option, or enter a custom answer · Esc cancels[/]"
            )

    def on_mount(self) -> None:
        if self.state.current is None:
            self.dismiss(self.state.response())
            return
        self._refresh_question()

    def _refresh_question(self) -> None:
        question = self.state.current
        if question is None:
            self.dismiss(self.state.response())
            return
        number = self.state.index + 1
        total = len(self.state.questions)
        prompt = escape(str(question.get("question") or "Please choose"))
        self.query_one("#user-input-question", Static).update(
            f"[bold]{number}/{total}[/]  {prompt}"
        )
        options = question.get("options")
        option_list = self.query_one("#user-input-options", OptionList)
        option_list.clear_options()
        self._option_values = []
        if isinstance(options, list):
            for option in options:
                if isinstance(option, dict):
                    label = str(option.get("label") or "").strip()
                    description = str(option.get("description") or "").strip()
                else:
                    label = str(option).strip()
                    description = ""
                if not label:
                    continue
                self._option_values.append(label)
                display = escape(label)
                if description:
                    display += f"  [dim]{escape(description)}[/]"
                option_list.add_option(
                    Option(display, id=str(len(self._option_values) - 1))
                )
        custom = self.query_one("#user-input-custom", Input)
        custom.value = ""
        if self._option_values:
            option_list.focus()
        else:
            custom.focus()

    def on_option_list_option_selected(
        self, event: OptionList.OptionSelected
    ) -> None:
        try:
            index = int(str(event.option.id))
            value = self._option_values[index]
        except (TypeError, ValueError, IndexError):
            return
        self._accept(value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._accept(event.value)

    def _accept(self, value: str) -> None:
        if not value.strip():
            return
        if self.state.answer(value):
            self.dismiss(self.state.response())
        else:
            self._refresh_question()

    def action_cancel(self) -> None:
        self.dismiss(None)
