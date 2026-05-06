"""Tool registry, mirroring `crates/tui/src/tools/registry.rs`.

Two important Rust invariants the Python port preserves:

1. **Alphabetical sort in `to_api_tools()`** (Rust L144-149, GitHub
   issue #263). DeepSeek's KV prefix cache only stays warm if the tool
   array is byte-stable across launches. Python's ``dict`` preserves
   insertion order, but cross-process registration order varies (env,
   config, MCP discovery), so we sort by name on serialisation.
2. **Memoised serialised catalog** (Rust L151-156). Each tool's
   ``description()`` and ``input_schema()`` is sampled exactly once per
   registration. Some tools — notably MCP adapters whose upstream
   description string drifts on reconnect — would otherwise rewrite
   the catalog mid-session and bust the prefix cache.

The wire format we emit is the standard OpenAI ``{type, function}``
envelope, with two non-OpenAI Rust extension fields (``allowed_callers``
and ``defer_loading``) tucked into the ``function`` object. Both fields
are silently ignored by providers that don't recognise them.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from deepseek_tui.tools.base import (
    ApprovalRequirement,
    ToolCapability,
    ToolError,
    ToolResult,
    ToolSpec,
)
from deepseek_tui.tools.context import ToolContext

__all__ = ["ToolRegistry"]

_LOG = logging.getLogger(__name__)


class ToolRegistry:
    def __init__(self, context: ToolContext | None = None) -> None:
        self._tools: dict[str, ToolSpec] = {}
        self._context: ToolContext | None = context
        self._api_cache: list[dict[str, Any]] | None = None

    # ------------------------------------------------------------------
    # registration
    # ------------------------------------------------------------------

    def register(self, tool: ToolSpec) -> None:
        """Register a tool. Logs a warning if it overwrites an existing one.

        Mirrors Rust ``ToolRegistry::register`` (registry.rs:46-52).
        """
        name = tool.name()
        if name in self._tools:
            _LOG.warning("Overwriting existing tool: %s", name)
        self._tools[name] = tool
        self._invalidate_api_cache()

    def register_all(self, tools: list[ToolSpec]) -> None:
        """Register every tool in ``tools`` (Rust L55-59)."""
        for tool in tools:
            self.register(tool)

    def remove(self, name: str) -> ToolSpec | None:
        """Remove a tool by name; return the removed spec or ``None``.

        Mirrors Rust L264-271. Cache is only invalidated if a removal
        actually happened, matching the Rust early-return.
        """
        removed = self._tools.pop(name, None)
        if removed is not None:
            self._invalidate_api_cache()
        return removed

    def clear(self) -> None:
        """Remove every registered tool (Rust L274-278)."""
        self._tools.clear()
        self._invalidate_api_cache()

    # ------------------------------------------------------------------
    # introspection
    # ------------------------------------------------------------------

    def get(self, name: str) -> ToolSpec:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise ToolError(f"Tool not found: {name}") from exc

    def contains(self, name: str) -> bool:
        return name in self._tools

    def names(self) -> list[str]:
        """Return all registered tool names (insertion order, NOT sorted).

        Rust ``names()`` returns insertion-order; only ``to_api_tools``
        sorts. Keeping this asymmetric matches the Rust contract.
        """
        return list(self._tools)

    def all(self) -> list[ToolSpec]:
        return list(self._tools.values())

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and name in self._tools

    def is_empty(self) -> bool:
        return not self._tools

    # ------------------------------------------------------------------
    # capability / approval filtering
    # ------------------------------------------------------------------

    def filter_by_capability(self, capability: ToolCapability) -> list[ToolSpec]:
        """Mirrors Rust L203-208."""
        return [t for t in self._tools.values() if capability in t.capabilities()]

    def read_only_tools(self) -> list[ToolSpec]:
        """Mirrors Rust L214-219."""
        return [t for t in self._tools.values() if t.is_read_only()]

    def approval_required_tools(self) -> list[ToolSpec]:
        """Tools whose ``approval_requirement()`` is ``REQUIRED``.

        Mirrors Rust L225-231.
        """
        return [
            t
            for t in self._tools.values()
            if t.approval_requirement() == ApprovalRequirement.REQUIRED
        ]

    def approval_suggested_tools(self) -> list[ToolSpec]:
        """Tools whose approval is at least *suggested*.

        Includes both ``Suggest`` and ``Required``, matching Rust L236-247.
        """
        wanted = (ApprovalRequirement.SUGGEST, ApprovalRequirement.REQUIRED)
        return [t for t in self._tools.values() if t.approval_requirement() in wanted]

    # ------------------------------------------------------------------
    # context
    # ------------------------------------------------------------------

    @property
    def context(self) -> ToolContext | None:
        return self._context

    def set_context(self, context: ToolContext) -> None:
        """Replace the registry's tool execution context (Rust L251)."""
        self._context = context

    # ------------------------------------------------------------------
    # execution
    # ------------------------------------------------------------------

    async def execute(
        self,
        name: str,
        input_data: dict[str, Any],
        context: ToolContext,
    ) -> ToolResult:
        """Run a tool by name with ``context``. Returns the full result.

        Honours ``context.timeout_ms`` if set. Wraps lookup / timeout /
        ``ValueError`` into :class:`ToolError`.
        """
        tool = self.get(name)
        timeout_seconds = (
            context.timeout_ms / 1000 if context.timeout_ms is not None else None
        )
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

    async def execute_full(
        self,
        name: str,
        input_data: dict[str, Any],
        context: ToolContext | None = None,
        context_override: ToolContext | None = None,
    ) -> ToolResult:
        """Rust-named alias for :meth:`execute`, with context override.

        Mirrors Rust ``execute_full_with_context`` (registry.rs:122-134).

        Resolution order for the actual context passed to the tool:

        1. ``context_override`` if provided (used when the engine retries
           with an elevated sandbox policy)
        2. ``context`` if provided
        3. ``self.context`` (the registry-level default)

        Raises :class:`ToolError` if no context is resolvable.
        """
        ctx = context_override or context or self._context
        if ctx is None:
            raise ToolError(
                "ToolRegistry.execute_full: no context available "
                "(pass context= or call set_context() first)"
            )
        return await self.execute(name, input_data, ctx)

    # ------------------------------------------------------------------
    # API serialisation
    # ------------------------------------------------------------------

    def to_api_tools(self) -> list[dict[str, Any]]:
        """Return the tool catalog in the OpenAI Chat Completions schema.

        The catalog is **sorted alphabetically by name** for DeepSeek
        prefix-cache stability (issue #263) and **memoised** so each
        tool's metadata is sampled exactly once per registration.

        Wire format::

            {
              "type": "function",
              "function": {
                "name": ...,
                "description": ...,
                "parameters": ...,
                "allowed_callers": ["direct"],   # Rust extension
                "defer_loading": false           # Rust extension
              }
            }

        ``allowed_callers`` and ``defer_loading`` are Rust extension
        fields preserved for behaviour parity; OpenAI / DeepSeek silently
        ignore unknown keys inside ``function``.
        """
        if self._api_cache is None:
            self._api_cache = [
                self._serialise_tool(tool)
                for _, tool in sorted(self._tools.items())
            ]
        return self._api_cache

    def to_api_tools_with_cache(self, enable_cache: bool) -> list[dict[str, Any]]:
        """Return :meth:`to_api_tools` with a cache marker on the last tool.

        Mirrors Rust L190-198. When ``enable_cache`` is true, the last
        entry gets ``cache_control = {"type": "ephemeral"}``, which lets
        prompt-cache-aware providers (Anthropic, some OpenAI proxies)
        anchor the prefix at the end of the tool list.
        """
        # Copy the list so callers don't mutate the memoised payload.
        tools = [dict(t) for t in self.to_api_tools()]
        if enable_cache and tools:
            last = tools[-1]
            # Avoid mutating the cached `function` dict in place.
            last["function"] = dict(last["function"])
            last["cache_control"] = {"type": "ephemeral"}
        return tools

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    def _invalidate_api_cache(self) -> None:
        self._api_cache = None

    @staticmethod
    def _serialise_tool(tool: ToolSpec) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": tool.name(),
                "description": tool.description(),
                "parameters": tool.input_schema(),
                "allowed_callers": ["direct"],
                "defer_loading": tool.defer_loading(),
            },
        }
