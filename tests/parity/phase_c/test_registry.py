"""Parity tests for ToolRegistry.

Mirrors the behavioural contract of
``crates/tui/src/tools/registry.rs``. Focus areas:

* Alphabetical-sort invariant for ``to_api_tools()`` (DeepSeek issue
  #263 — the comment lives at registry.rs:144-149).
* api_cache memoisation + invalidation on register/remove/clear.
* Capability and approval-requirement filters (registry.rs:200-247).
* execute_full's context-override resolution (registry.rs:122-134).
* to_api_tools_with_cache marker on the last tool (registry.rs:188-198).
"""

from __future__ import annotations

import logging
from typing import Any

import pytest

from deepseek_tui.tools.base import (
    ApprovalRequirement,
    ToolCapability,
    ToolResult,
    ToolSpec,
)
from deepseek_tui.tools.context import ToolContext
from deepseek_tui.tools.registry import ToolRegistry

# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class _SpyTool(ToolSpec):
    """Counts how many times metadata accessors get sampled.

    Used to prove the api_cache is memoised and only re-built on
    register / remove / clear.
    """

    def __init__(
        self,
        name: str,
        *,
        capabilities: tuple[ToolCapability, ...] = (),
        approval: ApprovalRequirement = ApprovalRequirement.AUTO,
        defer: bool = False,
        description: str = "",
        return_value: str = "ok",
    ) -> None:
        self._name = name
        self._caps = list(capabilities)
        self._approval = approval
        self._defer = defer
        self._description = description or f"spy tool {name}"
        self._return_value = return_value
        self.description_calls = 0
        self.input_schema_calls = 0
        self.execute_calls = 0
        self.last_context: ToolContext | None = None

    def name(self) -> str:
        return self._name

    def description(self) -> str:
        self.description_calls += 1
        return self._description

    def input_schema(self) -> dict[str, Any]:
        self.input_schema_calls += 1
        return {"type": "object", "properties": {}}

    def capabilities(self) -> list[ToolCapability]:
        return list(self._caps)

    def approval_requirement(self) -> ApprovalRequirement:
        return self._approval

    def defer_loading(self) -> bool:
        return self._defer

    async def execute(
        self, input_data: dict[str, Any], context: ToolContext
    ) -> ToolResult:
        self.execute_calls += 1
        self.last_context = context
        return ToolResult(success=True, content=self._return_value)


def _ctx(workspace: str = "/tmp") -> ToolContext:
    from pathlib import Path

    return ToolContext(working_directory=Path(workspace))


# ---------------------------------------------------------------------------
# 1. Alphabetical sort (Rust L144-149, issue #263)
# ---------------------------------------------------------------------------


def test_to_api_tools_alphabetical_order() -> None:
    """Registration order is randomised; output must be sorted by name."""
    registry = ToolRegistry()
    for name in ["zeta", "alpha", "mike", "bravo"]:
        registry.register(_SpyTool(name))

    api = registry.to_api_tools()
    names = [entry["function"]["name"] for entry in api]
    assert names == ["alpha", "bravo", "mike", "zeta"]


def test_to_api_tools_serialisation_shape() -> None:
    """OpenAI ``{type, function}`` envelope plus Rust extension fields."""
    registry = ToolRegistry()
    registry.register(_SpyTool("alpha"))
    api = registry.to_api_tools()
    assert api == [
        {
            "type": "function",
            "function": {
                "name": "alpha",
                "description": "spy tool alpha",
                "parameters": {"type": "object", "properties": {}},
                "allowed_callers": ["direct"],
                "defer_loading": False,
            },
        }
    ]


# ---------------------------------------------------------------------------
# 2. api_cache memoisation (Rust L151-156)
# ---------------------------------------------------------------------------


def test_to_api_tools_caches_first_call() -> None:
    spy = _SpyTool("alpha")
    registry = ToolRegistry()
    registry.register(spy)

    # description() / input_schema() should only be sampled once even
    # across multiple to_api_tools() calls.
    for _ in range(5):
        registry.to_api_tools()
    assert spy.description_calls == 1
    assert spy.input_schema_calls == 1


def test_register_invalidates_cache() -> None:
    spy = _SpyTool("alpha")
    registry = ToolRegistry()
    registry.register(spy)
    registry.to_api_tools()  # warm

    registry.register(_SpyTool("bravo"))
    registry.to_api_tools()
    # The pre-existing tool's metadata should be re-sampled because the
    # cache was invalidated.
    assert spy.description_calls == 2


def test_remove_invalidates_cache_only_when_present() -> None:
    spy = _SpyTool("alpha")
    registry = ToolRegistry()
    registry.register(spy)
    registry.to_api_tools()

    # Removing a tool that doesn't exist must NOT invalidate the cache.
    registry.remove("nonexistent")
    registry.to_api_tools()
    assert spy.description_calls == 1

    # Removing the actual tool invalidates and rebuilds.
    registry.remove("alpha")
    registry.to_api_tools()
    # No tools left → no further description sampling.
    assert registry.to_api_tools() == []


def test_clear_invalidates_cache() -> None:
    registry = ToolRegistry()
    registry.register(_SpyTool("alpha"))
    registry.to_api_tools()  # warm

    registry.clear()
    assert registry.to_api_tools() == []
    assert registry.is_empty()


# ---------------------------------------------------------------------------
# 3. Overwrite warning (Rust L48-50)
# ---------------------------------------------------------------------------


def test_register_overwrite_logs_warning(caplog: pytest.LogCaptureFixture) -> None:
    registry = ToolRegistry()
    registry.register(_SpyTool("alpha"))
    with caplog.at_level(logging.WARNING, logger="deepseek_tui.tools.registry"):
        registry.register(_SpyTool("alpha"))
    assert any(
        "Overwriting existing tool" in record.message and "alpha" in record.message
        for record in caplog.records
    )


def test_register_first_time_does_not_warn(
    caplog: pytest.LogCaptureFixture,
) -> None:
    registry = ToolRegistry()
    with caplog.at_level(logging.WARNING, logger="deepseek_tui.tools.registry"):
        registry.register(_SpyTool("alpha"))
    assert not any("Overwriting" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# 4. register_all (Rust L55-59)
# ---------------------------------------------------------------------------


def test_register_all_registers_each() -> None:
    registry = ToolRegistry()
    registry.register_all([_SpyTool("a"), _SpyTool("b"), _SpyTool("c")])
    assert sorted(registry.names()) == ["a", "b", "c"]


# ---------------------------------------------------------------------------
# 5. Capability / approval filters (Rust L200-247)
# ---------------------------------------------------------------------------


def test_filter_by_capability() -> None:
    registry = ToolRegistry()
    registry.register(
        _SpyTool("reader", capabilities=(ToolCapability.READ_ONLY,))
    )
    registry.register(
        _SpyTool("writer", capabilities=(ToolCapability.WRITES_FILES,))
    )
    registry.register(
        _SpyTool(
            "shell",
            capabilities=(ToolCapability.EXECUTES_CODE, ToolCapability.SANDBOXABLE),
        )
    )

    sandboxable = {
        t.name() for t in registry.filter_by_capability(ToolCapability.SANDBOXABLE)
    }
    assert sandboxable == {"shell"}

    read_only = {t.name() for t in registry.read_only_tools()}
    assert read_only == {"reader"}


def test_approval_required_only_includes_required() -> None:
    registry = ToolRegistry()
    registry.register(_SpyTool("auto"))  # default = AUTO
    registry.register(_SpyTool("hint", approval=ApprovalRequirement.SUGGEST))
    registry.register(_SpyTool("hard", approval=ApprovalRequirement.REQUIRED))

    names = {t.name() for t in registry.approval_required_tools()}
    assert names == {"hard"}


def test_approval_suggested_includes_required() -> None:
    """Rust L240-243: Suggest set includes Required."""
    registry = ToolRegistry()
    registry.register(_SpyTool("auto"))
    registry.register(_SpyTool("hint", approval=ApprovalRequirement.SUGGEST))
    registry.register(_SpyTool("hard", approval=ApprovalRequirement.REQUIRED))

    names = {t.name() for t in registry.approval_suggested_tools()}
    assert names == {"hint", "hard"}


# ---------------------------------------------------------------------------
# 6. to_api_tools_with_cache (Rust L188-198)
# ---------------------------------------------------------------------------


def test_to_api_tools_with_cache_marks_last_only() -> None:
    registry = ToolRegistry()
    registry.register(_SpyTool("alpha"))
    registry.register(_SpyTool("zeta"))

    out = registry.to_api_tools_with_cache(enable_cache=True)
    assert out[0].get("cache_control") is None
    assert out[-1]["cache_control"] == {"type": "ephemeral"}


def test_to_api_tools_with_cache_disabled_is_noop() -> None:
    registry = ToolRegistry()
    registry.register(_SpyTool("alpha"))
    out = registry.to_api_tools_with_cache(enable_cache=False)
    assert "cache_control" not in out[0]


def test_to_api_tools_with_cache_does_not_mutate_memoised_payload() -> None:
    """Calling with_cache must NOT pollute the canonical to_api_tools result."""
    registry = ToolRegistry()
    registry.register(_SpyTool("alpha"))
    canonical_before = registry.to_api_tools()
    registry.to_api_tools_with_cache(enable_cache=True)
    canonical_after = registry.to_api_tools()
    assert canonical_before == canonical_after
    assert "cache_control" not in canonical_after[0]


# ---------------------------------------------------------------------------
# 7. execute_full + context override (Rust L122-134)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_full_uses_registry_context_by_default() -> None:
    spy = _SpyTool("alpha")
    base_ctx = _ctx("/base")
    registry = ToolRegistry(base_ctx)
    registry.register(spy)

    await registry.execute_full("alpha", {})
    assert spy.last_context is base_ctx


@pytest.mark.asyncio
async def test_execute_full_uses_explicit_context_when_provided() -> None:
    spy = _SpyTool("alpha")
    registry = ToolRegistry()
    registry.register(spy)

    ctx = _ctx("/explicit")
    await registry.execute_full("alpha", {}, context=ctx)
    assert spy.last_context is ctx


@pytest.mark.asyncio
async def test_execute_full_context_override_wins() -> None:
    """Sandbox-elevation retry path: override beats both explicit and default."""
    spy = _SpyTool("alpha")
    registry = ToolRegistry(_ctx("/registry"))
    registry.register(spy)

    explicit = _ctx("/explicit")
    override = _ctx("/override")
    await registry.execute_full("alpha", {}, context=explicit, context_override=override)
    assert spy.last_context is override


@pytest.mark.asyncio
async def test_execute_full_raises_when_no_context_anywhere() -> None:
    from deepseek_tui.tools.base import ToolError

    registry = ToolRegistry()  # no default ctx
    registry.register(_SpyTool("alpha"))
    with pytest.raises(ToolError, match="no context available"):
        await registry.execute_full("alpha", {})


# ---------------------------------------------------------------------------
# 8. Introspection (Rust L63-98)
# ---------------------------------------------------------------------------


def test_contains_and_len_and_membership_operator() -> None:
    registry = ToolRegistry()
    assert "alpha" not in registry
    assert len(registry) == 0
    assert registry.is_empty()

    registry.register(_SpyTool("alpha"))
    assert "alpha" in registry
    assert registry.contains("alpha")
    assert len(registry) == 1
    assert not registry.is_empty()


def test_names_preserves_insertion_order_not_sort() -> None:
    """names() is insertion-order; only to_api_tools sorts (Rust contract)."""
    registry = ToolRegistry()
    registry.register(_SpyTool("zeta"))
    registry.register(_SpyTool("alpha"))
    registry.register(_SpyTool("mike"))
    assert registry.names() == ["zeta", "alpha", "mike"]


def test_get_unknown_raises_tool_error() -> None:
    from deepseek_tui.tools.base import ToolError

    with pytest.raises(ToolError, match="Tool not found: missing"):
        ToolRegistry().get("missing")
