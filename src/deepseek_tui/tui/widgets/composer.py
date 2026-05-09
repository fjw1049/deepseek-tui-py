"""Input composer widget — mirrors Rust ``tui/user_input.rs``.

Stage 6.5: Detects ``/`` prefix for slash commands, posts ``SlashInput``
message when the input starts with ``/``, and ``Submitted`` for normal
messages. Also fires ``TextChanged`` on every keystroke so the app can
show/hide the SlashMenu.
"""
from __future__ import annotations

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
        if event.key == "enter":
            event.prevent_default()
            text = self.text.strip()
            if text:
                if text.startswith("/"):
                    self.post_message(self.SlashInput(text))
                else:
                    self.post_message(self.Submitted(text))
                self.clear()
        elif event.key == "escape":
            event.prevent_default()
            self.post_message(self.TextChanged(""))
        else:
            await super()._on_key(event)
            self.post_message(self.TextChanged(self.text))
