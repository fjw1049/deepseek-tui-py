"""Input composer widget — mirrors Rust ``tui/user_input.rs``."""
from __future__ import annotations

import os
import subprocess
import tempfile
import time
from pathlib import Path

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
        self._refresh()

    def set_mode(self, mode: str) -> None:
        self._mode = mode
        self._refresh()

    def set_model(self, model: str) -> None:
        self._model = model
        self._refresh()

    def _refresh(self) -> None:
        chords = "[dim]↵ send · ⌃J newline · ⇧⇥ mode[/]"
        self.update(chords)


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

    def __init__(self) -> None:
        super().__init__(language=None)
        self.show_line_numbers = False
        self._paste_suppress_until: float = 0.0

    def on_mount(self) -> None:
        self.placeholder = (
            "Message DeepSeek…  "
            "( ↵ send · Ctrl+J newline · / for commands · @ for files )"
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
            self.post_message(self.TextChanged(""))
            return

        # Shift+Tab cycles agent/plan/yolo/ask modes. ``Tab`` itself is
        # consumed by the underlying TextArea for indentation, so we
        # route mode-switching through Shift+Tab — Codex / Claude Code
        # use the same chord for the same reason.
        if event.key == "shift+tab":
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
