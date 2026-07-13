"""Adapt Pi sidecar tools into host ToolSpec instances."""

from __future__ import annotations

import json
from typing import Any

from deepseek_tui.plugins.pi_runtime import PiNodeRuntime, PiToolInfo
from deepseek_tui.tools.registry import (
    ApprovalRequirement,
    ToolCapability,
    ToolContext,
    ToolResult,
    ToolSpec,
)


class PiBridgeTool(ToolSpec):
    """One tool exposed by a session-scoped Pi Node sidecar."""

    def __init__(
        self,
        *,
        runtime: PiNodeRuntime,
        info: PiToolInfo,
        owner_plugin_id: str,
    ) -> None:
        self._runtime = runtime
        self._info = info
        self._owner = owner_plugin_id
        safe_owner = "".join(
            ch if ch.isalnum() or ch in "._-" else "_" for ch in owner_plugin_id
        )
        self._qualified = f"pi_{safe_owner}_{info.name}".lower()

    def name(self) -> str:
        return self._qualified

    def description(self) -> str:
        label = self._info.label or self._info.name
        return f"[pi:{self._owner}] {label}: {self._info.description}".strip()

    def input_schema(self) -> dict[str, Any]:
        return dict(self._info.input_schema)

    def capabilities(self) -> list[ToolCapability]:
        return [
            ToolCapability.EXECUTES_CODE,
            ToolCapability.REQUIRES_APPROVAL,
        ]

    def approval_requirement(self) -> ApprovalRequirement:
        return ApprovalRequirement.REQUIRED

    async def execute(
        self, input_data: dict[str, Any], context: ToolContext
    ) -> ToolResult:
        del context
        result = await self._runtime.call_tool(self._info.name, input_data)
        content_parts = result.get("content") if isinstance(result, dict) else None
        texts: list[str] = []
        if isinstance(content_parts, list):
            for part in content_parts:
                if isinstance(part, dict) and part.get("type") == "text":
                    texts.append(str(part.get("text") or ""))
                elif isinstance(part, dict) and part.get("type") == "image":
                    texts.append("[image]")
        body = "\n".join(t for t in texts if t) or json.dumps(
            result, ensure_ascii=False, default=str
        )
        return ToolResult(
            success=True,
            content=body,
            metadata={
                "pi_plugin": self._owner,
                "pi_tool": self._info.name,
                "details": (result or {}).get("details")
                if isinstance(result, dict)
                else {},
            },
        )
