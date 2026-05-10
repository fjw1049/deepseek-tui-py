"""Input composer widget — mirrors Rust ``tui/user_input.rs``.

Stage 6.5: Detects ``/`` prefix for slash commands, posts ``SlashInput``
message when the input starts with ``/``, and ``Submitted`` for normal
messages. Also fires ``TextChanged`` on every keystroke so the app can
show/hide the SlashMenu.

P2 enhancements (2026-05-10):
- Ctrl+Enter inserts a newline instead of submitting (multi-line input).
- Ctrl+E opens $EDITOR for long-form editing (mirrors Rust external_editor.rs).

Stage 6 paste-burst integration (2026-05-10): rather than port Rust's
``paste_burst.rs`` char-timing fallback (necessary because crossterm in
some terminals delivers paste as a stream of fast keystrokes), we lean
on Textual's native bracketed-paste support — ``events.Paste`` fires
once with the full payload. We additionally suppress the next ``Enter``
submission for a short window after a multi-line paste, mirroring Rust
``newline_should_insert_instead_of_submit``: if a paste contained
newlines, the user almost certainly didn't intend the trailing Enter as
a "submit now" signal.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
import time
from pathlib import Path

from textual import events
from textual.message import Message
from textual.widgets import TextArea

PASTE_ENTER_SUPPRESS_WINDOW_SECS: float = 0.120


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
        self._paste_suppress_until: float = 0.0

    def _paste_window_active(self) -> bool:
        return time.monotonic() < self._paste_suppress_until

    def on_paste(self, event: events.Paste) -> None:
        """Insert pasted text at the cursor and suppress next Enter.

        Mirror Rust ``PasteBurst::newline_should_insert_instead_of_submit``
        (paste_burst.rs:157): when a paste contains a newline, the
        following Enter should insert a newline rather than submit, so
        the user can edit the pasted block before sending.
        """
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
