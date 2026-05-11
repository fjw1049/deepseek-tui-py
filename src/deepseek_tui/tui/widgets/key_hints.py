"""Bottom key-hint strip — custom replacement for Textual's default Footer.

The stock :class:`textual.widgets.Footer` had two problems for our UX:

1. It used ``^x`` notation for Ctrl chords (technical / cramped) and the
   bright-orange key highlight clashed with the rest of the chrome.
2. It auto-surfaced focused-widget bindings on the **right** side, which
   collided with the app-level Ctrl+P binding and produced a visible
   ``^p Files`` duplicate next to the left cluster.

``KeyHints`` renders a single muted chip row at the bottom of the screen
using macOS-native ``⌃`` glyphs, bold-on-dim styling, and `·` separators
to give each chord visual breathing room. The actual key bindings live
on :class:`deepseek_tui.tui.app.DeepSeekTUI` — this widget is display
only.
"""
from __future__ import annotations

from textual.widgets import Static


class KeyHints(Static):
    """One-line, chip-style key-hint strip docked at the bottom."""

    DEFAULT_CSS = """
    KeyHints {
        dock: bottom;
        height: 1;
        padding: 0 1;
        background: $panel;
        color: $text-muted;
    }
    """

    # Curated subset of app-level chords. ``↵ send`` / ``Ctrl+J newline``
    # / ``Tab mode`` are already shown by ``ComposerHint`` above the
    # composer, so we deliberately leave them off here to avoid the
    # noise the default Textual Footer used to produce.
    _CHORDS: tuple[tuple[str, str], ...] = (
        ("⌃K", "palette"),
        ("⌃P", "files"),
        ("⌃R", "sessions"),
        ("⌃O", "models"),
        ("⌃B", "sidebar"),
        ("⌃N", "new"),
        ("F1", "help"),
    )

    def __init__(self) -> None:
        super().__init__(self._build_markup())

    def _build_markup(self) -> str:
        chips = [f"[b]{key}[/] [dim]{label}[/]" for key, label in self._CHORDS]
        return "[dim]  ·  [/]".join(chips)
