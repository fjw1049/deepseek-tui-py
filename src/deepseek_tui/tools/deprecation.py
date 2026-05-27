"""Deprecated tool alias notices — mirrors Rust ``wrap_with_deprecation_notice``."""

from __future__ import annotations

from dataclasses import replace

from deepseek_tui.tools.base import (
    ApprovalRequirement,
    ToolCapability,
    ToolResult,
    ToolSpec,
)
from deepseek_tui.tools.context import ToolContext


def deprecation_notice(alias: str, canonical: str) -> dict[str, str]:
    return {
        "this_tool": alias,
        "use_instead": canonical,
        "removed_in": "0.8.0",
        "message": (
            f"Tool '{alias}' is deprecated; switch to '{canonical}' before v0.8.0."
        ),
    }


def attach_deprecation(result: ToolResult, alias: str, canonical: str) -> ToolResult:
    metadata = dict(result.metadata)
    metadata["_deprecation"] = deprecation_notice(alias, canonical)
    return replace(result, metadata=metadata)


class DeprecatingAliasTool(ToolSpec):
    """Delegate to *inner* but expose *alias_name* and stamp deprecation metadata."""

    def __init__(
        self,
        inner: ToolSpec,
        alias_name: str,
        canonical_name: str,
    ) -> None:
        self._inner = inner
        self._alias = alias_name
        self._canonical = canonical_name

    def name(self) -> str:
        return self._alias

    def description(self) -> str:
        return (
            f"Compatibility alias for {self._canonical}. "
            f"Use {self._canonical} instead."
        )

    def input_schema(self) -> dict[str, object]:
        return self._inner.input_schema()

    def capabilities(self) -> list[ToolCapability]:
        return self._inner.capabilities()

    def approval_requirement(self) -> ApprovalRequirement:
        return self._inner.approval_requirement()

    async def execute(
        self, input_data: dict[str, object], context: ToolContext
    ) -> ToolResult:
        result = await self._inner.execute(input_data, context)
        return attach_deprecation(result, self._alias, self._canonical)
