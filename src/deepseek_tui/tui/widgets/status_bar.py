"""Status bar widget — mirrors Rust ``tui/widgets/footer.rs``.

Stage 6.6: Shows current model, mode, status, and token usage.
"""
from __future__ import annotations

from textual.widgets import Static


class StatusBar(Static):
    """Bottom status bar showing current state."""

    def __init__(self) -> None:
        super().__init__("[dim]ready[/]")
        self._status: str = "ready"
        self._model: str = ""
        self._mode: str = ""
        self._tokens: int = 0

    def set_status(self, text: str) -> None:
        self._status = text
        self._refresh()

    def set_model(self, model: str) -> None:
        self._model = model
        self._refresh()

    def set_mode(self, mode: str) -> None:
        self._mode = mode
        self._refresh()

    def set_tokens(self, tokens: int) -> None:
        self._tokens = tokens
        self._refresh()

    def _refresh(self) -> None:
        parts: list[str] = []
        if self._model:
            parts.append(f"[bold]{self._model}[/]")
        if self._mode:
            parts.append(f"[cyan]{self._mode}[/]")
        parts.append(f"[dim]{self._status}[/]")
        if self._tokens > 0:
            parts.append(f"[dim]{self._tokens} tokens[/]")
        self.update(" | ".join(parts))
