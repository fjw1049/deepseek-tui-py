"""Status footer — mirrors Rust ``crates/tui/src/tui/widgets/footer.rs``.

Single 1-row bar docked to the bottom of the app, rendered as a
3-column Rich ``Table.grid`` inside one ``Static``. The earlier
``Horizontal`` + three-child approach proved brittle under Textual's
dock layout (the row vanished when stacked with ``ComposerHint`` and
``Composer`` on the same edge); collapsing to one Static + one
internal grid sidesteps the layout fight entirely while keeping the
``mode·model·cost  /  chord chips  /  cache·worked·ctx`` layout the
user designed off the Rust footer.

Legacy parity (phase-E tests): the ``_status``, ``_model``, ``_mode``,
``_tokens`` attributes plus the legacy setters
(``set_status`` / ``set_model`` / ``set_mode`` / ``set_tokens``)
remain. ``set_cost`` / ``set_cache`` / ``set_currency`` are the new
hooks the engine drives off ``TurnCompleteEvent``.
"""
from __future__ import annotations

import time

from rich.table import Table
from rich.text import Text
from textual.widgets import Static

from deepseek_tui.client.pricing import CostCurrency, format_cost_amount


class StatusBar(Static):
    """Single-row bottom status footer with three clusters."""

    DEFAULT_CSS = """
    StatusBar {
        height: 1;
        dock: bottom;
        background: $panel;
        color: $text;
        padding: 0 1;
    }
    """

    _MIDDLE_CHORDS: tuple[tuple[str, str], ...] = (
        ("⇧⇥", "mode"),
        ("⌃P", "files"),
        ("⌃R", "sessions"),
        ("⌃O", "models"),
    )

    def __init__(self) -> None:
        super().__init__("")
        self._status: str = "ready"
        self._model: str = ""
        self._mode: str = ""
        self._tokens: int = 0
        self._started_at: float | None = None
        self._finished_at: float | None = None
        self._cost_usd: float = 0.0
        self._cost_cny: float = 0.0
        self._currency: CostCurrency = CostCurrency.USD
        self._cache_hit_tokens: int = 0
        self._cache_miss_tokens: int = 0

    def on_mount(self) -> None:
        self._refresh()

    # --- legacy setters (phase-E parity) -----------------------------

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
        self._started_at = ts if ts is not None else time.monotonic()
        self._finished_at = None
        self._refresh()

    def set_finished(self) -> None:
        if self._started_at is not None and self._finished_at is None:
            self._finished_at = time.monotonic()
        self._refresh()

    # --- new setters -------------------------------------------------

    def set_cost(self, usd: float, cny: float = 0.0) -> None:
        self._cost_usd = max(0.0, usd)
        self._cost_cny = max(0.0, cny)
        self._refresh()

    def set_cache(self, hit_tokens: int, miss_tokens: int) -> None:
        self._cache_hit_tokens = max(0, hit_tokens)
        self._cache_miss_tokens = max(0, miss_tokens)
        self._refresh()

    def set_currency(self, currency: CostCurrency) -> None:
        self._currency = currency
        self._refresh()

    # --- cluster builders --------------------------------------------

    def _left_markup(self) -> Text:
        parts: list[str] = []
        if self._mode:
            parts.append(f"[cyan]{self._mode}[/]")
        if self._model:
            parts.append(f"[bold]{self._model}[/]")
        cost_chip = self._cost_chip()
        if cost_chip:
            parts.append(cost_chip)
        if self._status and self._status != "ready":
            parts.append(f"[dim]{self._status}[/]")
        if not parts:
            return Text("")
        return Text.from_markup("  [dim]·[/]  ".join(parts))

    def _cost_chip(self) -> str:
        amount = self._cost_usd if self._currency is CostCurrency.USD else self._cost_cny
        if amount <= 0.0:
            return ""
        return f"[dim]{format_cost_amount(amount, self._currency)}[/]"

    def _mid_markup(self) -> Text:
        chips = [f"[b]{key}[/] [dim]{label}[/]" for key, label in self._MIDDLE_CHORDS]
        return Text.from_markup("[dim]  ·  [/]".join(chips))

    def _right_markup(self) -> Text:
        parts: list[Text] = []
        cache_chip = self._cache_chip()
        if cache_chip is not None:
            parts.append(cache_chip)
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
            label = (
                f"{self._tokens / 1000:.1f}k ctx"
                if self._tokens >= 1000
                else f"{self._tokens} ctx"
            )
            parts.append(Text(label, style="dim"))
        if not parts:
            return Text("")
        out = Text()
        for i, p in enumerate(parts):
            if i > 0:
                out.append("  ·  ", style="dim")
            out.append_text(p)
        return out

    def _cache_chip(self) -> Text | None:
        total = self._cache_hit_tokens + self._cache_miss_tokens
        if total == 0:
            return None
        pct = min(100.0, max(0.0, 100.0 * self._cache_hit_tokens / total))
        if pct > 80.0:
            style = "green"
        elif pct >= 40.0:
            style = "yellow"
        else:
            style = "red"
        return Text(f"cache {pct:.0f}%", style=f"dim {style}")

    def _refresh(self) -> None:
        # Three columns: left auto-wide, middle expanding (chord chips
        # centered), right auto-wide. Rich's Table.grid handles widths
        # internally — no Textual dock fights, no missing rows.
        grid = Table.grid(expand=True, padding=(0, 2))
        grid.add_column(justify="left", no_wrap=True)
        grid.add_column(justify="center", ratio=1, no_wrap=True)
        grid.add_column(justify="right", no_wrap=True)
        grid.add_row(self._left_markup(), self._mid_markup(), self._right_markup())
        try:
            self.update(grid)
        except Exception:
            pass
