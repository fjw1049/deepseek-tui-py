"""Status bar — mirrors Rust ``tui/widgets/footer.rs``.

Layout: a 1-row :class:`Horizontal` split into a left chip cluster
(``mode · model · status``) and a right chip cluster
(``worked Ns · {tokens} ctx``). The right cluster uses Rich's
``justify="right"`` so it sticks to the right edge regardless of left
content length.

Legacy parity (tests in ``tests/parity/phase_e/test_tui_stage6_extras.py``):
the ``_status``, ``_model``, ``_mode``, ``_tokens`` attributes plus the
``set_status`` / ``set_model`` / ``set_mode`` / ``set_tokens`` setters
remain backwards compatible.
"""
from __future__ import annotations

import time

from rich.text import Text
from textual.containers import Horizontal
from textual.widgets import Static


class StatusBar(Horizontal):
    """Bottom status bar with left/right chip clusters."""

    DEFAULT_CSS = """
    StatusBar {
        height: 1;
        dock: bottom;
        background: $panel;
    }
    StatusBar > #status-left {
        width: auto;
        padding: 0 1 0 1;
    }
    StatusBar > #status-right {
        width: 1fr;
        padding: 0 1 0 0;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self._status: str = "ready"
        self._model: str = ""
        self._mode: str = ""
        self._tokens: int = 0
        self._started_at: float | None = None
        self._finished_at: float | None = None
        self._left = Static("", id="status-left")
        self._right = Static("", id="status-right")

    def compose(self):  # type: ignore[override]
        yield self._left
        yield self._right

    def on_mount(self) -> None:
        self._refresh()

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

    def set_started(self, ts: float | None = None) -> None:
        """Mark the start of a long-running turn so the right cluster
        can show ``worked Ns``. ``None`` uses ``time.monotonic()``."""
        self._started_at = ts if ts is not None else time.monotonic()
        self._finished_at = None
        self._refresh()

    def set_finished(self) -> None:
        """Freeze the ``worked Ns`` chip at the current elapsed value."""
        if self._started_at is not None and self._finished_at is None:
            self._finished_at = time.monotonic()
        self._refresh()

    def _left_markup(self) -> str:
        parts: list[str] = []
        if self._mode:
            parts.append(f"[cyan]{self._mode}[/]")
        if self._model:
            parts.append(f"[bold]{self._model}[/]")
        parts.append(f"[dim]{self._status}[/]")
        return "  [dim]·[/]  ".join(parts)

    def _right_text(self) -> Text:
        parts: list[Text] = []
        if self._started_at is not None:
            end = (
                self._finished_at
                if self._finished_at is not None
                else time.monotonic()
            )
            secs = max(0.0, end - self._started_at)
            if secs >= 1.0:
                parts.append(Text(f"worked {secs:.0f}s", style="dim"))
        if self._tokens > 0:
            parts.append(Text(f"{self._tokens} ctx", style="dim"))
        if not parts:
            return Text("", justify="right")
        out = Text(justify="right")
        for i, p in enumerate(parts):
            if i > 0:
                out.append("  ·  ", style="dim")
            out.append_text(p)
        return out

    def _refresh(self) -> None:
        try:
            self._left.update(self._left_markup())
            self._right.update(self._right_text())
        except Exception:
            pass
