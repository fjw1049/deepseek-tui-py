"""Input composer widget — mirrors Rust ``tui/user_input.rs``.

Stage 6.5: Detects ``/`` prefix for slash commands, posts ``SlashInput``
message when the input starts with ``/``, and ``Submitted`` for normal
messages. Also fires ``TextChanged`` on every keystroke so the app can
show/hide the SlashMenu.

P2 enhancements (2026-05-10):
- Ctrl+Enter inserts a newline instead of submitting (multi-line input).
- Ctrl+E opens $EDITOR for long-form editing (mirrors Rust external_editor.rs).
"""
from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

from textual.events import Key
from textual.message import Message
from textual.widgets import TextArea


class Composer(TextArea):
    """Multi-line input widget for composing messages."""

    class Submitted(Message):
        def __init__(self, text: str) -> None:
            super().__init__()
            self.text = text

    class SlashInput(Message):
        """Posted when user submits a ``/command``."""

        def __init__(self, raw_input: str) -> None:
            super().__init__()
            self.raw_input = raw_input

    class TextChanged(Message):
        """Posted on every keystroke so the app can update slash menu."""

        def __init__(self, text: str) -> None:
            super().__init__()
            self.text = text

    def __init__(self) -> None:
        super().__init__(language=None)
        self.show_line_numbers = False

    async def _on_key(self, event: Key) -> None:
        if event.key in ("ctrl+j", "ctrl+enter"):
            event.prevent_default()
            self.insert("\n")
            self.post_message(self.TextChanged(self.text))
            return
        if event.key == "ctrl+e":
            event.prevent_default()
            edited = _open_external_editor(self.text)
            if edited is not None:
                self.clear()
                self.insert(edited)
                self.post_message(self.TextChanged(self.text))
            return
        if event.key == "enter":
            event.prevent_default()
            text = self.text.strip()
            if text:
                if text.startswith("/"):
                    self.post_message(self.SlashInput(text))
                else:
                    self.post_message(self.Submitted(text))
                self.clear()
            return
        if event.key == "escape":
            event.prevent_default()
            self.post_message(self.TextChanged(""))
            return
        await super()._on_key(event)
        self.post_message(self.TextChanged(self.text))


def _open_external_editor(initial_content: str) -> str | None:
    """Open $EDITOR with *initial_content* and return the saved buffer.

    Mirrors Rust ``external_editor.rs``. Returns None on failure or if
    no $EDITOR / $VISUAL is configured.
    """
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
