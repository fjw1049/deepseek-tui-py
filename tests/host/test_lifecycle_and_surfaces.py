from __future__ import annotations

from pathlib import Path

import pytest

from deepseek_tui.host.lifecycle import (
    AfterToolContext,
    BeforeUserTurnContext,
    FunctionLifecycleObserver,
    LifecycleRegistry,
    LifecycleRegistryError,
    TurnCompletionContext,
    TurnFailureContext,
)
from deepseek_tui.host.surfaces import (
    RuntimeSurfaceRegistry,
    RuntimeSurfaceRegistryError,
)


def _before_turn_context(tmp_path: Path) -> BeforeUserTurnContext:
    return BeforeUserTurnContext(
        thread_id="thread-1",
        turn_id="turn-1",
        user_text="hello",
        workspace=tmp_path,
        metadata={},
        services=object(),
    )


@pytest.mark.asyncio
async def test_lifecycle_registry_dispatches_in_order(tmp_path: Path) -> None:
    events: list[str] = []

    async def _record(name: str) -> None:
        events.append(name)

    registry = LifecycleRegistry()
    registry.add(
        id="second",
        owner="test",
        order=200,
        observer=FunctionLifecycleObserver(
            on_before_user_turn=lambda _ctx: _record("second")
        ),
    )
    registry.add(
        id="first",
        owner="test",
        order=100,
        observer=FunctionLifecycleObserver(
            on_before_user_turn=lambda _ctx: _record("first")
        ),
    )

    await registry.before_user_turn(_before_turn_context(tmp_path))

    assert events == ["first", "second"]


@pytest.mark.asyncio
async def test_lifecycle_registry_dispatches_all_supported_phases(
    tmp_path: Path,
) -> None:
    events: list[str] = []

    async def _record(name: str) -> None:
        events.append(name)

    registry = LifecycleRegistry()
    registry.add(
        id="all",
        owner="test",
        observer=FunctionLifecycleObserver(
            on_before_user_turn=lambda _ctx: _record("before-turn"),
            on_turn_completed_cb=lambda _ctx: _record("completed"),
            on_turn_failed_cb=lambda _ctx: _record("failed"),
            after_tool_cb=lambda _ctx: _record("after-tool"),
        ),
    )
    metadata: dict[str, object] = {}
    services = object()

    await registry.before_user_turn(_before_turn_context(tmp_path))
    await registry.on_turn_completed(
        TurnCompletionContext(
            thread_id="thread-1",
            turn_id="turn-1",
            success=True,
            usage=None,
            metadata=metadata,
            services=services,
        )
    )
    await registry.on_turn_failed(
        TurnFailureContext(
            thread_id="thread-1",
            turn_id="turn-2",
            reason="failed",
            usage=None,
            metadata=metadata,
            services=services,
        )
    )
    await registry.after_tool(
        AfterToolContext(
            tool_call_id="call-1",
            tool_name="read_file",
            arguments={},
            success=True,
            result=None,
            metadata=metadata,
            services=services,
        )
    )

    assert events == [
        "before-turn",
        "completed",
        "failed",
        "after-tool",
    ]


def test_lifecycle_registry_rejects_duplicate_ids() -> None:
    registry = LifecycleRegistry()
    observer = object()
    registry.add(id="observer", owner="first", observer=observer)

    with pytest.raises(LifecycleRegistryError, match="already registered"):
        registry.add(id="observer", owner="second", observer=observer)


def test_runtime_surface_registry_routes() -> None:
    registry = RuntimeSurfaceRegistry()

    async def _handler() -> dict[str, bool]:
        return {"ok": True}

    registry.add_route(
        id="mcp-startup",
        owner="mcp",
        method="POST",
        path="/v1/mcp/startup",
        handler=_handler,
    )
    route = registry.routes()[0]
    assert route.id == "mcp-startup"
    assert route.method == "POST"
    assert route.path == "/v1/mcp/startup"


def test_runtime_surface_registry_rejects_conflicts() -> None:
    registry = RuntimeSurfaceRegistry()
    registry.add_route(
        id="first",
        owner="first",
        method="GET",
        path="/v1/demo",
        handler=lambda: {"ok": True},
    )
    with pytest.raises(RuntimeSurfaceRegistryError, match="already registered"):
        registry.add_route(
            id="second",
            owner="second",
            method="GET",
            path="/v1/demo",
            handler=lambda: {"ok": True},
        )
