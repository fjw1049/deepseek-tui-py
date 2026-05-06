from __future__ import annotations

import asyncio
from typing import Any

from deepseek_tui.tools.base import ToolError, ToolResult, ToolSpec
from deepseek_tui.tools.context import ToolContext


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}
        self._api_cache: list[dict[str, Any]] | None = None

    def register(self, tool: ToolSpec) -> None:
        self._tools[tool.name()] = tool
        self._api_cache = None

    def get(self, name: str) -> ToolSpec:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise ToolError(f"Tool not found: {name}") from exc

    async def execute(
        self,
        name: str,
        input_data: dict[str, Any],
        context: ToolContext,
    ) -> ToolResult:
        tool = self.get(name)
        timeout_seconds = context.timeout_ms / 1000 if context.timeout_ms is not None else None
        try:
            if timeout_seconds is None:
                return await tool.execute(input_data, context)
            return await asyncio.wait_for(
                tool.execute(input_data, context),
                timeout=timeout_seconds,
            )
        except asyncio.TimeoutError as exc:
            raise ToolError(f"Tool {name} timed out after {timeout_seconds}s") from exc
        except ValueError as exc:
            raise ToolError(str(exc)) from exc

    def to_api_tools(self) -> list[dict[str, Any]]:
        if self._api_cache is None:
            self._api_cache = [
                {
                    "type": "function",
                    "function": {
                        "name": name,
                        "description": tool.description(),
                        "parameters": tool.input_schema(),
                    },
                }
                for name, tool in sorted(self._tools.items())
            ]
        return self._api_cache
