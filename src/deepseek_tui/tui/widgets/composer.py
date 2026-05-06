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

    def __init__(self) -> None:
        super().__init__(language=None)
        self.show_line_numbers = False

    async def _on_key(self, event: Key) -> None:
        if event.key == "enter":
            event.prevent_default()
            text = self.text.strip()
            if text:
                self.post_message(self.Submitted(text))
                self.clear()
        else:
            await super()._on_key(event)
