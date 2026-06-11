from __future__ import annotations

from types import SimpleNamespace

import pytest

from deepseek_tui.capabilities.mcp import (
    attach_mcp_bindings,
    build_mcp_augmented_tool_catalog,
    create_mcp_manager,
    execute_mcp_tool,
    is_external_mcp_tool_call,
    mcp_manager_from_runtime_or_context,
    mcp_preload_status_response,
    mcp_preload_status_runtime_response,
    mcp_servers_runtime_response,
    mcp_startup_response,
    mcp_startup_runtime_response,
    mcp_tools_runtime_response,
    shutdown_mcp_manager,
)
from deepseek_tui.config.models import Config, FeatureConfig
from deepseek_tui.host.services import ServiceRegistry
from deepseek_tui.mcp.manager import McpManager
from deepseek_tui.tools.context import ToolContext
from deepseek_tui.tools.mcp_tools import MCP_MANAGER_KEY


@pytest.mark.asyncio
async def test_mcp_capability_skips_when_disabled() -> None:
    services = ServiceRegistry()
    cfg = Config(features=FeatureConfig(mcp=False))

    manager, owns = await create_mcp_manager(
        cfg,
        services,
        provided_manager=None,
        start_mcp=False,
    )

    assert manager is None
    assert owns is True
    assert services.optional(McpManager) is None


@pytest.mark.asyncio
async def test_mcp_capability_uses_provided_manager_without_ownership() -> None:
    services = ServiceRegistry()
    provided = McpManager([])
    cfg = Config(features=FeatureConfig(mcp=True))

    manager, owns = await create_mcp_manager(
        cfg,
        services,
        provided_manager=provided,
        start_mcp=False,
    )

    assert manager is provided
    assert owns is False
    assert services.require(McpManager) is provided


def test_mcp_capability_registers_service_bindings() -> None:
    services = ServiceRegistry()
    manager = McpManager([])

    attach_mcp_bindings(manager, services=services)

    assert services.require_named(MCP_MANAGER_KEY) is manager


class _Runtime:
    def __init__(self, manager: McpManager | None) -> None:
        self.mcp_manager = manager


def test_mcp_capability_resolves_manager_from_runtime_or_context(tmp_path) -> None:
    context = ToolContext(working_directory=tmp_path)
    manager = McpManager([])
    assert (
        mcp_manager_from_runtime_or_context(
            tool_runtime=_Runtime(manager),
            context=context,
        )
        is manager
    )

    context.services.add(McpManager, manager, owner="test", scope="engine")
    assert (
        mcp_manager_from_runtime_or_context(
            tool_runtime=None,
            context=context,
        )
        is manager
    )


class _McpCatalogManager(McpManager):
    def __init__(self, cached: list[dict] | None) -> None:
        super().__init__([])
        self._cached = cached
        self.discover_scheduled = 0

    def cached_tools(self) -> list[dict] | None:
        return self._cached

    def schedule_background_discover(self) -> None:
        self.discover_scheduled += 1


def _tool(name: str) -> dict:
    return {"type": "function", "function": {"name": name, "parameters": {}}}


def test_mcp_capability_catalog_defers_cold_discovery() -> None:
    manager = _McpCatalogManager(None)

    result, cache = build_mcp_augmented_tool_catalog(
        native_tools=[_tool("read_file")],
        mcp_manager=manager,
        cached_tools=None,
        mode="agent",
        profile="full",
    )

    assert [tool["function"]["name"] for tool in result] == ["read_file"]
    assert cache is None
    assert manager.discover_scheduled == 1


def test_mcp_capability_catalog_merges_warm_tools() -> None:
    result, cache = build_mcp_augmented_tool_catalog(
        native_tools=[_tool("read_file")],
        mcp_manager=_McpCatalogManager([_tool("mcp__demo")]),
        cached_tools=None,
        mode="agent",
        profile="full",
    )

    assert [tool["function"]["name"] for tool in result] == ["read_file", "mcp__demo"]
    assert cache is not None
    assert [tool["function"]["name"] for tool in cache] == ["mcp__demo"]


def test_mcp_capability_identifies_external_mcp_tool_calls() -> None:
    assert is_external_mcp_tool_call("mcp__server__tool", registry_contains=False)
    assert not is_external_mcp_tool_call("mcp__server__tool", registry_contains=True)
    assert not is_external_mcp_tool_call("read_file", registry_contains=False)


class _McpExecuteManager(McpManager):
    def __init__(self) -> None:
        super().__init__([])
        self.calls: list[tuple[str, dict]] = []

    async def call_tool(self, tool_name: str, arguments: dict) -> dict:
        self.calls.append((tool_name, arguments))
        return {"content": [{"type": "text", "text": "ok"}]}


@pytest.mark.asyncio
async def test_mcp_capability_executes_external_mcp_tool() -> None:
    manager = _McpExecuteManager()

    result = await execute_mcp_tool(manager, "mcp__server__tool", {"x": 1})

    assert result.success is True
    assert result.content == "ok"
    assert manager.calls == [("mcp__server__tool", {"x": 1})]


class _RouteRuntime:
    def __init__(self) -> None:
        self.startup_calls = 0

    async def mcp_startup(self) -> dict:
        self.startup_calls += 1
        return {"ok": True}

    def mcp_preload_status(self) -> dict:
        return {"ready": True}

    async def list_mcp_servers(self) -> dict:
        return {"servers": []}

    async def list_mcp_tools(self) -> dict:
        return {"tools": []}


@pytest.mark.asyncio
async def test_mcp_capability_route_helpers_delegate_to_runtime() -> None:
    runtime = _RouteRuntime()
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(runtime=runtime)))

    assert await mcp_startup_response(request) == {"ok": True}
    assert runtime.startup_calls == 1
    assert mcp_preload_status_response(request) == {"ready": True}


@pytest.mark.asyncio
async def test_mcp_capability_runtime_response_helpers() -> None:
    runtime = _RouteRuntime()

    assert await mcp_startup_runtime_response(runtime) == {"ok": True}
    assert runtime.startup_calls == 1
    assert mcp_preload_status_runtime_response(runtime) == {"ready": True}
    assert await mcp_servers_runtime_response(runtime) == {"servers": []}
    assert await mcp_tools_runtime_response(runtime) == {"tools": []}


class _McpShutdownRecorder:
    def __init__(self) -> None:
        self.stop_calls = 0

    async def stop_all(self) -> None:
        self.stop_calls += 1


@pytest.mark.asyncio
async def test_mcp_capability_shutdown_respects_ownership() -> None:
    manager = _McpShutdownRecorder()

    await shutdown_mcp_manager(manager, owns_manager=False)  # type: ignore[arg-type]
    assert manager.stop_calls == 0

    await shutdown_mcp_manager(manager, owns_manager=True)  # type: ignore[arg-type]
    assert manager.stop_calls == 1
