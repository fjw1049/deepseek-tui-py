"""First-run onboarding screen.

Mirrors ``crates/tui/src/tui/onboarding/`` (167 LOC for ``mod.rs`` plus
``welcome.rs``, ``api_key.rs``, ``trust_directory.rs``).

Three-step flow:

1. Welcome — short intro + "Press Enter to continue".
2. API key — input field + masked display + Enter to save (writes to
   ``config.toml`` ``api_key = "..."``).
3. Tips — the post-setup blurb.

The marker file ``~/.deepseek/.onboarded`` records that the user has
finished the flow so we don't show it again.
"""

from __future__ import annotations

import enum
from pathlib import Path

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Label, Static


class OnboardingStep(str, enum.Enum):
    """Mirror Rust ``OnboardingState`` (onboarding/mod.rs:33)."""

    WELCOME = "welcome"
    API_KEY = "api_key"
    TIPS = "tips"


def default_marker_path() -> Path:
    """Mirror Rust ``default_marker_path`` (onboarding/mod.rs:134).

    Project-local since 2026-05-11 — each checkout decides whether the
    user has finished its own onboarding.
    """
    from deepseek_tui.config.paths import dot_deepseek_dir

    return dot_deepseek_dir() / ".onboarded"


def is_onboarded() -> bool:
    """Mirror Rust ``is_onboarded`` (onboarding/mod.rs:138)."""
    return default_marker_path().exists()


def mark_onboarded() -> Path:
    """Mirror Rust ``mark_onboarded`` (onboarding/mod.rs:142)."""
    path = default_marker_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("")
    return path


def mask_key(key: str) -> str:
    """Mirror Rust ``mask_key`` (onboarding/api_key.rs:71)."""
    trimmed = key.strip()
    n = len(trimmed)
    if n == 0:
        return ""
    if n <= 4:
        return "*" * n
    return "*" * (n - 4) + trimmed[-4:]


class OnboardingScreen(ModalScreen[str | None]):
    """Three-step onboarding flow.

    On dismiss returns either:
    - ``None`` if the user cancelled, or
    - the API key string if they completed the API key step (the caller
      writes it to ``config.toml`` and re-builds the engine).
    """

    BINDINGS = [
        Binding("enter", "next_step", show=False),
        Binding("escape", "cancel", show=False),
    ]

    DEFAULT_CSS = """
    OnboardingScreen {
        align: center middle;
    }
    #onboarding-modal {
        width: 78;
        height: 22;
        border: round $accent;
        background: $surface;
        padding: 1 2;
    }
    #onboarding-input {
        margin-top: 1;
    }
    #onboarding-status {
        color: $warning;
        margin-top: 1;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self.step = OnboardingStep.WELCOME
        self.api_key: str = ""
        self.status: str = ""

    def compose(self) -> ComposeResult:
        with Vertical(id="onboarding-modal"):
            yield Static("", id="onboarding-body")
            yield Input(
                placeholder="paste DEEPSEEK_API_KEY here",
                password=True,
                id="onboarding-input",
            )
            yield Label("", id="onboarding-status")

    def on_mount(self) -> None:
        self._refresh()

    def _refresh(self) -> None:
        body = self.query_one("#onboarding-body", Static)
        input_widget = self.query_one("#onboarding-input", Input)
        status = self.query_one("#onboarding-status", Label)

        if self.step == OnboardingStep.WELCOME:
            body.update(
                "[bold cyan]Welcome to DeepSeek TUI[/]\n\n"
                "A terminal-native AI agent for code, data, and ops.\n\n"
                "[dim]Press Enter to continue, Esc to cancel.[/]"
            )
            input_widget.display = False
        elif self.step == OnboardingStep.API_KEY:
            body.update(
                "[bold cyan]API Key Setup[/]\n\n"
                "Enter your [bold]DEEPSEEK_API_KEY[/] to continue.\n"
                f"Get your key at [link]https://platform.deepseek.com[/].\n\n"
                f"Current: [bold]{mask_key(self.api_key) or '(paste key here)'}[/]\n"
                "[dim]Paste the full key exactly as issued.[/]\n\n"
                "[dim]Press Enter to save, Esc to skip.[/]"
            )
            input_widget.display = True
            input_widget.focus()
        else:
            body.update(
                "[bold cyan]You're all set[/]\n\n"
                "Tips:\n"
                "  - Write tasks in plain language. Use /help or Ctrl+K.\n"
                "  - Composer is multi-line: Enter sends; Ctrl+J / Ctrl+Enter inserts a newline.\n"
                "  - Modes: [bold]/agent[/] / [bold]/plan[/] / [bold]/yolo[/].\n"
                "  - Esc backs out of overlays. Press it twice to backtrack a turn.\n\n"
                "[dim]Press Enter to start.[/]"
            )
            input_widget.display = False
        status.update(self.status)

    def action_next_step(self) -> None:
        if self.step == OnboardingStep.WELCOME:
            self.step = OnboardingStep.API_KEY
            self.status = ""
        elif self.step == OnboardingStep.API_KEY:
            try:
                value = self.query_one("#onboarding-input", Input).value
            except LookupError:
                value = ""
            self.api_key = value.strip()
            if not self.api_key:
                self.status = "API key cannot be empty"
                self._refresh()
                return
            if len(self.api_key) < 10:
                self.status = "Key looks too short — please double-check"
                self._refresh()
                return
            self.status = ""
            self.step = OnboardingStep.TIPS
        else:
            self.dismiss(self.api_key or None)
            return
        self._refresh()

    def action_cancel(self) -> None:
        self.dismiss(None)
