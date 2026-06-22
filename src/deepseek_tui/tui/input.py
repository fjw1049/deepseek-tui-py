"""Input widgets — composer, slash menu, command palette.
"""

from __future__ import annotations



# ======================================================================
# From composer.py
# ======================================================================

"""Input composer widget — mirrors Rust ``tui/user_input.rs``."""

import os
import subprocess
import tempfile
import time
from pathlib import Path

from rich.markup import escape
from textual import events
from textual.message import Message
from textual.widgets import Static, TextArea

PASTE_ENTER_SUPPRESS_WINDOW_SECS: float = 0.120


class ComposerHint(Static):
    """One-line hint strip above the composer.

    Shows the active mode + model + the high-traffic key chords
    (``↵ send · Ctrl+J newline · Tab mode``). Mirrors the bottom title
    of Rust's bordered ``ComposerWidget`` block in
    ``crates/tui/src/tui/widgets/mod.rs``.
    """

    DEFAULT_CSS = """
    ComposerHint {
        dock: bottom;
        height: 1;
        padding: 0 1;
        color: $text-muted;
    }
    """

    def __init__(self) -> None:
        super().__init__("")
        self._mode: str = "agent"
        self._model: str = ""
        self._current_step: str = ""
        self._next_step: str = ""
        self._refresh()

    def set_mode(self, mode: str) -> None:
        self._mode = mode
        self._refresh()

    def set_model(self, model: str) -> None:
        self._model = model
        self._refresh()

    def set_progress(self, current_step: str = "", next_step: str = "") -> None:
        self._current_step = current_step.strip()
        self._next_step = next_step.strip()
        self._refresh()

    def _refresh(self) -> None:
        chords = "[dim]↵ send · ⌃J newline · ⇧⇥ mode[/]"
        progress: list[str] = []
        if self._current_step:
            progress.append(f"[bright_cyan]→ {escape(self._current_step[:48])}[/]")
        if self._next_step:
            progress.append(f"[dim]next: {escape(self._next_step[:42])}[/]")
        self.update("  [dim]·[/]  ".join([*progress, chords]))


class Composer(TextArea):
    """Multi-line input widget for composing messages."""

    class Submitted(Message):
        def __init__(self, text: str) -> None:
            super().__init__()
            self.text = text

    class SlashInput(Message):
        def __init__(self, raw_input: str) -> None:
            super().__init__()
            self.raw_input = raw_input

    class TextChanged(Message):
        def __init__(self, text: str) -> None:
            super().__init__()
            self.text = text

    class PasteEnterSuppressed(Message):
        """Posted when Enter is temporarily treated as newline after paste."""

        pass

    def __init__(self) -> None:
        super().__init__(language=None)
        self.show_line_numbers = False
        self._paste_suppress_until: float = 0.0

    def on_mount(self) -> None:
        self.placeholder = (
            "Message DeepSeek…  ( ↵ send · ⌃J newline · / commands · @ files )"
        )

    def _paste_window_active(self) -> bool:
        return time.monotonic() < self._paste_suppress_until

    def on_paste(self, event: events.Paste) -> None:
        if not event.text:
            return
        event.prevent_default()
        event.stop()
        self.insert(event.text)
        if "\n" in event.text or "\r" in event.text:
            self._paste_suppress_until = (
                time.monotonic() + PASTE_ENTER_SUPPRESS_WINDOW_SECS
            )
            self.post_message(self.PasteEnterSuppressed())
        self.post_message(self.TextChanged(self.text))

    async def _on_key(self, event: events.Key) -> None:
        if event.key in ("enter", "return"):
            event.stop()
            event.prevent_default()
            if self._paste_window_active():
                self.insert("\n")
                self.post_message(self.TextChanged(self.text))
                return
            text = self.text.strip()
            if text:
                if text.startswith("/"):
                    self.post_message(self.SlashInput(text))
                else:
                    self.post_message(self.Submitted(text))
                self.clear()
            return

        if event.key in ("ctrl+j", "ctrl+enter"):
            event.stop()
            event.prevent_default()
            self.insert("\n")
            self.post_message(self.TextChanged(self.text))
            return

        if event.key == "ctrl+e":
            event.stop()
            event.prevent_default()
            edited = _open_external_editor(self.text)
            if edited is not None:
                self.clear()
                self.insert(edited)
                self.post_message(self.TextChanged(self.text))
            return

        if event.key == "escape":
            event.prevent_default()
            if self.text:
                self.clear()
                self.post_message(self.TextChanged(""))
            return

        # Shift+Tab cycles agent/plan/yolo/ask modes when the composer is
        # empty; otherwise defer to TextArea dedent in multi-line input.
        if event.key == "shift+tab":
            if self.text.strip():
                await super()._on_key(event)
                self.post_message(self.TextChanged(self.text))
                return
            event.stop()
            event.prevent_default()
            action = getattr(self.app, "action_cycle_mode", None)
            if callable(action):
                action()
            return

        await super()._on_key(event)
        self.post_message(self.TextChanged(self.text))


def _open_external_editor(initial_content: str) -> str | None:
    editor = os.environ.get("VISUAL") or os.environ.get("EDITOR")
    if not editor:
        return None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False, encoding="utf-8"
        ) as tmp:
            tmp.write(initial_content)
            tmp_path = Path(tmp.name)
        subprocess.run([*editor.split(), str(tmp_path)], check=False)  # noqa: S603,ASYNC221
        return tmp_path.read_text(encoding="utf-8")
    except OSError:
        return None
    finally:
        try:
            tmp_path.unlink()
        except (OSError, NameError):
            pass


# ======================================================================
# From slash_menu.py
# ======================================================================


from textual.app import ComposeResult
from textual.containers import Vertical
from textual.message import Message
from textual.widgets import OptionList, Static
from textual.widgets.option_list import Option

from deepseek_tui.tui.commands import get_completions


class SlashMenu(Vertical):
    """Popup menu for slash commands.

    Driven by the central :mod:`deepseek_tui.tui.commands` registry instead
    of a hardcoded list. The ``filter_text`` parameter on :meth:`show` is
    forwarded to :func:`get_completions` so the menu narrows as the user
    types.
    """

    class Selected(Message):
        def __init__(self, command: str) -> None:
            super().__init__()
            self.command = command

    DEFAULT_CSS = """
    SlashMenu {
        dock: bottom;
        height: auto;
        max-height: 12;
        border: tall $accent;
        background: $surface;
        display: none;
    }
    SlashMenu.visible {
        display: block;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static("[bold]Commands[/]")
        completions = get_completions("/")
        options = [
            Option(f"{cmd}  [dim]{desc}[/]", id=cmd)
            for cmd, desc in completions
        ]
        yield OptionList(*options)

    def show(self, filter_text: str = "") -> None:
        prefix = filter_text if filter_text.startswith("/") else "/"
        completions = get_completions(prefix)
        try:
            option_list = self.query_one(OptionList)
            option_list.clear_options()
            for cmd, desc in completions:
                option_list.add_option(Option(f"{cmd}  [dim]{desc}[/]", id=cmd))
        except Exception:
            pass
        self.add_class("visible")

    def hide(self) -> None:
        self.remove_class("visible")

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option.id:
            self.post_message(self.Selected(event.option.id))
        self.hide()


# ======================================================================
# From command_palette.py
# ======================================================================

"""Command palette widget — mirrors Rust ``tui/command_palette.rs``.

Stage 6.6: Ctrl+K style command palette for quick access to slash
commands, model switching, and other actions.
"""

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import Input, OptionList
from textual.widgets.option_list import Option

from deepseek_tui.tui.commands import get_completions


class CommandPalette(ModalScreen[str | None]):
    """Modal command palette activated by Ctrl+K."""

    CSS = """
    CommandPalette {
        align: center top;
    }
    #palette-container {
        width: 70;
        max-height: 20;
        margin-top: 3;
        border: thick $accent;
        padding: 1 2;
        background: $surface;
    }
    #palette-input {
        margin-bottom: 1;
    }
    """

    class Selected(Message):
        def __init__(self, command: str) -> None:
            super().__init__()
            self.command = command

    def compose(self) -> ComposeResult:
        with Vertical(id="palette-container"):
            yield Input(placeholder="Type a command...", id="palette-input")
            completions = get_completions("/")
            options = [
                Option(f"{cmd}  [dim]{desc}[/]", id=cmd)
                for cmd, desc in completions
            ]
            yield OptionList(*options, id="palette-list")

    def on_mount(self) -> None:
        self.query_one("#palette-input", Input).focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        text = event.value.strip()
        prefix = text if text.startswith("/") else f"/{text}"
        completions = get_completions(prefix)
        try:
            option_list = self.query_one("#palette-list", OptionList)
            option_list.clear_options()
            for cmd, desc in completions:
                option_list.add_option(Option(f"{cmd}  [dim]{desc}[/]", id=cmd))
        except Exception:
            pass

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        if text:
            cmd = text if text.startswith("/") else f"/{text}"
            self.dismiss(cmd)
        else:
            self.dismiss(None)

    def on_option_list_option_selected(
        self, event: OptionList.OptionSelected
    ) -> None:
        if event.option.id:
            self.dismiss(event.option.id)

    def on_key(self, event: object) -> None:
        from textual.events import Key
        if isinstance(event, Key) and event.key == "escape":
            self.dismiss(None)
