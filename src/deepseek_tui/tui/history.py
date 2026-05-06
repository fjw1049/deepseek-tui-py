from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class HistoryCell:
    """A single cell in the conversation history."""

    role: str
    content: str
    tool_calls: list[dict[str, str]] = field(default_factory=list)


class TranscriptCache:
    """Caches rendered conversation history for efficient scrolling."""

    def __init__(self) -> None:
        self._cells: list[HistoryCell] = []

    def append(self, cell: HistoryCell) -> None:
        self._cells.append(cell)

    def clear(self) -> None:
        self._cells.clear()

    @property
    def cells(self) -> list[HistoryCell]:
        return self._cells

    def __len__(self) -> int:
        return len(self._cells)
