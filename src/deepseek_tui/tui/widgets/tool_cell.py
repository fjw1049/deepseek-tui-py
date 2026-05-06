from __future__ import annotations

from textual.widgets import Static


class ToolCell(Static):
    """Displays a single tool execution with status and result."""

    def __init__(self, tool_name: str, tool_call_id: str) -> None:
        super().__init__("")
        self.tool_name = tool_name
        self.tool_call_id = tool_call_id
        self._status = "running"
        self._result: str = ""
        self._refresh()

    def set_result(self, content: str, success: bool) -> None:
        self._status = "done" if success else "failed"
        self._result = content
        self._refresh()

    def _refresh(self) -> None:
        icon = {"running": "⏳", "done": "✓", "failed": "✗"}.get(self._status, "?")
        header = f"[bold]{icon} {self.tool_name}[/]"
        if self._result:
            preview = self._result[:200]
            if len(self._result) > 200:
                preview += "..."
            self.update(f"{header}\n[dim]{preview}[/]")
        else:
            self.update(header)
