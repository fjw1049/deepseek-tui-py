from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, Union

from deepseek_tui.mcp.client import (
    McpClient,
    McpError,
    parse_qualified_tool_name,
    qualify_tool_name,
)
from deepseek_tui.mcp.config import McpServerConfig, load_mcp_config
from deepseek_tui.mcp.preload import DEFAULT_PRELOAD_TIMEOUT_S, McpPreloadTracker
from deepseek_tui.mcp.startup import raise_if_required_mcp_failed
from deepseek_tui.mcp.store import hash_mcp_document, load_raw_document
from deepseek_tui.protocol.mcp_lifecycle import (
    McpStartupCompleteEvent,
    McpStartupFailure,
    McpStartupStatus,
    McpStartupUpdateEvent,
)

StartupUpdateCallback = Callable[
    [McpStartupUpdateEvent], Union[None, Awaitable[None]]
]

logger = logging.getLogger(__name__)


class McpManager:
    """Manages multiple MCP server connections and tool routing."""

    def __init__(
        self,
        configs: list[McpServerConfig] | None = None,
        *,
        config_path: Path | None = None,
    ) -> None:
        self._configs: dict[str, McpServerConfig] = {}
        self._clients: dict[str, McpClient] = {}
        self._tool_map: dict[str, tuple[str, str]] = {}
        self._config_path = config_path.expanduser() if config_path else None
        self._last_mtime: float | None = None
        self._config_hash: str | None = None
        self._discovered_tools_cache: list[dict[str, Any]] | None = None
        self._stale_cache: list[dict[str, Any]] | None = None
        self._background_refresh_task: asyncio.Task[None] | None = None
        self._discover_inflight: asyncio.Task[list[dict[str, Any]]] | None = None
        self._discover_lock = asyncio.Lock()
        self._discovered_tools_cache_path: Path | None = None
        self._preload = McpPreloadTracker()
        if self._config_path is not None:
            from deepseek_tui.mcp.store import validate_mcp_config_path

            validate_mcp_config_path(self._config_path)
        if configs:
            for cfg in configs:
                self._configs[cfg.name] = cfg
        if self._config_path is not None and self._config_path.exists():
            self._record_config_fingerprint(self._config_path)
            self._discovered_tools_cache_path = (
                self._config_path.parent / "mcp-tools-cache.json"
            )
            self._load_discovered_tools_cache_from_disk()
        if self._discovered_tools_cache is not None:
            self._preload.mark_ready_from_disk(
                tools_count=len(self._discovered_tools_cache),
                enabled_servers=len(self._enabled_server_names()),
            )

    def _enabled_server_names(self) -> list[str]:
        return [name for name, cfg in self._configs.items() if cfg.enabled]

    def _connected_server_count(self) -> int:
        count = 0
        for name in self._enabled_server_names():
            client = self._clients.get(name)
            if client is not None and client.is_running:
                count += 1
        return count

    def preload_status(self) -> dict[str, Any]:
        cached = self.cached_tools()
        tools_count = len(cached) if cached is not None else 0
        enabled = len(self._enabled_server_names())
        if enabled == 0:
            payload = self._preload.snapshot(
                enabled_servers=0,
                connected_servers=0,
                tools_count=tools_count,
            ).to_payload()
            payload["phase"] = "disabled"
            payload["ready"] = True
            payload["warming"] = False
            return payload
        return self._preload.snapshot(
            enabled_servers=enabled,
            connected_servers=self._connected_server_count(),
            tools_count=tools_count,
        ).to_payload()

    def schedule_startup_preload(
        self,
        *,
        timeout_s: float = DEFAULT_PRELOAD_TIMEOUT_S,
        force: bool = False,
    ) -> None:
        """Background MCP connect + tool discovery after runtime serve starts."""
        enabled = self._enabled_server_names()
        if not enabled:
            self._preload.phase = "disabled"
            return
        task = self._preload._task
        if task is not None and not task.done():
            return
        if force:
            self._discovered_tools_cache = None
            self._preload.phase = "idle"
            self._preload.from_disk_cache = False
            self._preload.completed_at_ms = None
            self._preload.error = None
        if self._discovered_tools_cache is not None and not force:
            self._preload.mark_ready_from_disk(
                tools_count=len(self._discovered_tools_cache),
                enabled_servers=len(enabled),
            )
            logger.info(
                "mcp_preload_skip tools=%d reason=disk_cache enabled_servers=%d",
                len(self._discovered_tools_cache),
                len(enabled),
            )
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._preload._task = loop.create_task(
            self._run_startup_preload(timeout_s),
            name="mcp-preload",
        )

    async def _run_startup_preload(self, timeout_s: float) -> None:
        import time

        enabled = self._enabled_server_names()
        self._preload.phase = "warming"
        self._preload.started_at_ms = int(time.time() * 1000)
        self._preload.error = None
        logger.info(
            "mcp_preload_start enabled_servers=%d timeout_s=%.0f",
            len(enabled),
            timeout_s,
        )
        tools: list[dict[str, Any]] = []
        try:
            tools = await asyncio.wait_for(self.discover_tools(), timeout=timeout_s)
        except asyncio.TimeoutError:
            self._preload.error = f"timeout after {timeout_s:.0f}s"
            logger.warning("mcp_preload_timeout seconds=%.0f", timeout_s)
            cached = self.cached_tools()
            if cached is not None:
                tools = cached
        except Exception as exc:  # noqa: BLE001
            self._preload.error = str(exc)
            logger.exception("mcp_preload_failed")
            cached = self.cached_tools()
            if cached is not None:
                tools = cached

        connected = self._connected_server_count()
        self._preload.completed_at_ms = int(time.time() * 1000)
        if tools:
            self._preload.phase = (
                "partial" if connected < len(enabled) else "ready"
            )
            logger.info(
                "mcp_preload_complete phase=%s tools=%d connected=%d/%d",
                self._preload.phase,
                len(tools),
                connected,
                len(enabled),
            )
        else:
            self._preload.phase = "failed"
            logger.warning(
                "mcp_preload_failed_no_tools connected=%d/%d",
                connected,
                len(enabled),
            )

    @property
    def server_names(self) -> list[str]:
        return list(self._configs.keys())

    async def start_all(
        self,
        on_update: StartupUpdateCallback | None = None,
        *,
        fail_on_required: bool = False,
    ) -> McpStartupCompleteEvent:
        """Connect every configured server and return a startup summary.

        Mirrors Rust ``McpManager::start_all`` (``crates/mcp/src/lib.rs``) +
        ``McpPool::connect_all`` required checks (``mcp.rs:1594-1607``).
        """
        ready: list[str] = []
        failed: list[McpStartupFailure] = []
        cancelled: list[str] = []

        async def _emit_async(name: str, status: McpStartupStatus) -> None:
            if on_update is None:
                return
            event = McpStartupUpdateEvent(server_name=name, status=status)
            result = on_update(event)
            if result is not None:
                await result

        async def _start_server(name: str) -> tuple[str, str | None]:
            cfg = self._configs[name]
            if not cfg.enabled:
                await _emit_async(name, McpStartupStatus.cancelled())
                return name, "cancelled"
            await _emit_async(name, McpStartupStatus.starting())
            try:
                await self._ensure_client(name)
            except Exception as exc:  # noqa: BLE001 — surface per-server failure
                err = str(exc)
                await _emit_async(name, McpStartupStatus.failed(err))
                return name, err
            await _emit_async(name, McpStartupStatus.ready())
            return name, None

        start_names = [name for name, cfg in self._configs.items() if cfg.enabled]
        for name, cfg in self._configs.items():
            if not cfg.enabled:
                await _emit_async(name, McpStartupStatus.cancelled())
                cancelled.append(name)

        if start_names:
            results = await asyncio.gather(
                *(_start_server(name) for name in start_names)
            )
            for name, err in results:
                if err == "cancelled":
                    continue
                if err is None:
                    ready.append(name)
                else:
                    failed.append(McpStartupFailure(server_name=name, error=err))

        summary = McpStartupCompleteEvent(
            ready=ready,
            failed=failed,
            cancelled=cancelled,
        )
        if fail_on_required:
            raise_if_required_mcp_failed(self._configs, summary)
        return summary

    async def stop_all(self) -> None:
        for client in self._clients.values():
            await client.stop()
        self._clients.clear()
        self._tool_map.clear()
        # Demote live cache to stale rather than discarding — discover_tools()
        # can serve it immediately while reconnecting in the background.
        if self._discovered_tools_cache is not None:
            self._stale_cache = self._discovered_tools_cache
        self._discovered_tools_cache = None

    def _load_discovered_tools_cache_from_disk(self) -> None:
        path = self._discovered_tools_cache_path
        if path is None or not path.exists() or self._config_hash is None:
            return
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, ValueError):
            return
        if not isinstance(raw, dict):
            return
        tools = raw.get("tools")
        if not isinstance(tools, list):
            return
        if raw.get("config_hash") == self._config_hash:
            # Fresh cache — use directly.
            self._discovered_tools_cache = list(tools)
        else:
            # Stale cache (config changed) — serve immediately, refresh later.
            self._stale_cache = list(tools)

    def _persist_discovered_tools_cache_to_disk(self) -> None:
        path = self._discovered_tools_cache_path
        if (
            path is None
            or self._config_hash is None
            or self._discovered_tools_cache is None
        ):
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "config_hash": self._config_hash,
                "tools": self._discovered_tools_cache,
            }
            path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except OSError:
            return

    async def reload_if_config_changed(self) -> bool:
        """Lazy reload when config file mtime/content changed (Rust #1267)."""
        if self._config_path is None or not self._config_path.exists():
            return False
        try:
            mtime = self._config_path.stat().st_mtime
        except OSError:
            return False
        if self._last_mtime is not None and mtime == self._last_mtime:
            return False
        try:
            doc = load_raw_document(self._config_path)
            configs = load_mcp_config(self._config_path)
        except (OSError, ValueError, json.JSONDecodeError):
            return False
        new_hash = hash_mcp_document(doc)
        self._last_mtime = mtime
        if new_hash == self._config_hash:
            return False
        await self.stop_all()
        self._configs = {cfg.name: cfg for cfg in configs}
        self._config_hash = new_hash
        return True

    async def reconnect_all(self) -> McpStartupCompleteEvent:
        """Drop connections and reconnect every enabled server."""
        await self.stop_all()
        if self._config_path is not None and self._config_path.exists():
            try:
                configs = load_mcp_config(self._config_path)
                self._configs = {cfg.name: cfg for cfg in configs}
                self._record_config_fingerprint(self._config_path)
            except (OSError, ValueError, json.JSONDecodeError):
                pass
        return await self.start_all()

    def cached_tools(self) -> list[dict[str, Any]] | None:
        """Return warm MCP tool descriptors without starting discovery."""
        if self._discovered_tools_cache is not None:
            return list(self._discovered_tools_cache)
        if self._stale_cache is not None:
            return list(self._stale_cache)
        return None

    def schedule_background_discover(self) -> None:
        """Kick off tool discovery without blocking the caller."""
        if self.cached_tools() is not None or self._discover_inflight is not None:
            return
        task = self._preload._task
        if task is not None and not task.done():
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(self.discover_tools(), name="mcp-discover-bg")

    async def discover_tools(self) -> list[dict[str, Any]]:
        """Discover tools from all enabled servers, returns API-format list.

        Connects lazily via :meth:`_ensure_client` so callers do not need a
        prior :meth:`start_all` — ``Engine._get_tools_with_mcp`` relies on
        this.

        All servers are discovered **in parallel** with per-server timeouts
        derived from each server's ``connect_timeout`` config (default 10s).
        A single slow or unreachable server will not block the others.

        Concurrent callers share one in-flight discovery task (singleflight).
        """
        if self._discovered_tools_cache is not None:
            self._rebuild_tool_map_from_cache()
            return list(self._discovered_tools_cache)

        # Stale-while-revalidate: if config changed but we have a prior cache,
        # return it immediately and refresh in the background.
        if self._stale_cache is not None:
            self._discovered_tools_cache = self._stale_cache
            self._stale_cache = None
            self._rebuild_tool_map_from_cache()
            self._background_refresh_task = asyncio.create_task(
                self._refresh_cache_in_background(), name="mcp-cache-refresh"
            )
            return list(self._discovered_tools_cache)

        async with self._discover_lock:
            if self._discovered_tools_cache is not None:
                self._rebuild_tool_map_from_cache()
                return list(self._discovered_tools_cache)
            if self._discover_inflight is not None:
                return await asyncio.shield(self._discover_inflight)
            self._discover_inflight = asyncio.create_task(
                self._discover_tools_fresh(), name="mcp-discover"
            )
            task = self._discover_inflight
        try:
            return await asyncio.shield(task)
        finally:
            async with self._discover_lock:
                if self._discover_inflight is task:
                    self._discover_inflight = None

    async def _discover_tools_fresh(self) -> list[dict[str, Any]]:
        timed_out_servers: list[tuple[str, McpServerConfig]] = []

        async def _discover_one(
            server_name: str, cfg: McpServerConfig
        ) -> list[tuple[str, str, str, dict[str, Any]]]:
            """Returns [(qualified, server_name, raw_name, api_dict), ...]."""
            timeout = cfg.connect_timeout or 10.0
            try:
                client = await asyncio.wait_for(
                    self._ensure_client(server_name), timeout=timeout
                )
                descriptors = await asyncio.wait_for(
                    client.list_tools(), timeout=timeout
                )
            except asyncio.TimeoutError:
                timed_out_servers.append((server_name, cfg))
                return []
            except (McpError, Exception):  # noqa: BLE001
                return []
            results: list[tuple[str, str, str, dict[str, Any]]] = []
            for desc in descriptors:
                if cfg.tool_filter and not cfg.tool_filter.accepts(desc.name):
                    continue
                qualified = qualify_tool_name(server_name, desc.name)
                results.append((
                    qualified,
                    server_name,
                    desc.name,
                    {
                        "type": "function",
                        "function": {
                            "name": qualified,
                            "description": desc.description,
                            "parameters": desc.input_schema,
                        },
                    },
                ))
            return results

        enabled = [
            (name, cfg) for name, cfg in self._configs.items() if cfg.enabled
        ]
        all_results = await asyncio.gather(
            *(_discover_one(name, cfg) for name, cfg in enabled)
        )

        api_tools: list[dict[str, Any]] = []
        self._tool_map.clear()
        for server_results in all_results:
            for qualified, server_name, raw_name, api_dict in server_results:
                self._tool_map[qualified] = (server_name, raw_name)
                api_tools.append(api_dict)

        self._discovered_tools_cache = sorted(
            api_tools, key=lambda t: t["function"]["name"]
        )
        self._persist_discovered_tools_cache_to_disk()

        # Schedule background retry for servers that timed out so their tools
        # become available on subsequent turns without blocking the user now.
        if timed_out_servers:
            self._background_refresh_task = asyncio.create_task(
                self._retry_timed_out_servers(timed_out_servers),
                name="mcp-retry-timed-out",
            )

        return list(self._discovered_tools_cache)

    async def _retry_timed_out_servers(
        self, servers: list[tuple[str, McpServerConfig]]
    ) -> None:
        """Retry connecting timed-out servers in background, merge tools into cache.

        Waits 5s for network/processes to settle, then retries with 3x the
        original timeout. If still unreachable, the server is abandoned for
        this session — it will be retried on next full discover (e.g. next
        app launch or config change).
        """
        await asyncio.sleep(5)
        new_tools: list[dict[str, Any]] = []
        for server_name, cfg in servers:
            timeout = (cfg.connect_timeout or 10.0) * 3
            try:
                client = await asyncio.wait_for(
                    self._ensure_client(server_name), timeout=timeout
                )
                descriptors = await asyncio.wait_for(
                    client.list_tools(), timeout=timeout
                )
            except (McpError, asyncio.TimeoutError, Exception):  # noqa: BLE001
                continue
            for desc in descriptors:
                if cfg.tool_filter and not cfg.tool_filter.accepts(desc.name):
                    continue
                qualified = qualify_tool_name(server_name, desc.name)
                self._tool_map[qualified] = (server_name, desc.name)
                new_tools.append({
                    "type": "function",
                    "function": {
                        "name": qualified,
                        "description": desc.description,
                        "parameters": desc.input_schema,
                    },
                })
        if new_tools and self._discovered_tools_cache is not None:
            self._discovered_tools_cache.extend(new_tools)
            self._discovered_tools_cache.sort(key=lambda t: t["function"]["name"])
            self._persist_discovered_tools_cache_to_disk()

    async def _refresh_cache_in_background(self) -> None:
        """Re-discover tools in background and replace the stale cache.

        The stale cache continues serving requests while this runs. On
        success the fresh result replaces it; on failure the stale cache
        remains valid until next app restart.
        """
        # Invalidate only the live cache so discover_tools() runs the
        # parallel discovery path. Keep _stale_cache untouched as fallback.
        self._discovered_tools_cache = None
        self._tool_map.clear()
        try:
            await self.discover_tools()
        except Exception:  # noqa: BLE001
            # Restore stale cache if refresh failed entirely.
            if self._discovered_tools_cache is None and self._stale_cache is not None:
                self._discovered_tools_cache = self._stale_cache
                self._stale_cache = None
                self._rebuild_tool_map_from_cache()

    def _rebuild_tool_map_from_cache(self) -> None:
        self._tool_map.clear()
        if self._discovered_tools_cache is None:
            return
        for entry in self._discovered_tools_cache:
            fn = entry.get("function", entry)
            qualified = fn.get("name")
            if not isinstance(qualified, str):
                continue
            parsed = parse_qualified_tool_name(qualified)
            if parsed is None:
                continue
            self._tool_map[qualified] = parsed

    async def call_tool(self, qualified_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        mapping = self._tool_map.get(qualified_name)
        if mapping is None:
            parsed = parse_qualified_tool_name(qualified_name)
            if parsed is None:
                raise McpError(f"Not an MCP tool: {qualified_name}")
            mapping = parsed
        server_name, tool_name = mapping
        client = await self._ensure_client(server_name)
        return await client.call_tool(tool_name, arguments)

    async def list_resources(self, server: str | None = None) -> dict[str, list[dict[str, Any]]]:
        return await self._collect(server, "list_resources")

    async def list_resource_templates(
        self,
        server: str | None = None,
    ) -> dict[str, list[dict[str, Any]]]:
        return await self._collect(server, "list_resource_templates")

    async def read_resource(self, server: str, uri: str) -> dict[str, Any]:
        client = await self._ensure_client(server)
        return await client.read_resource(uri)

    async def get_prompt(
        self,
        server: str,
        name: str,
        arguments: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        client = await self._ensure_client(server)
        return await client.get_prompt(name, arguments)

    def is_mcp_tool(self, name: str) -> bool:
        return name in self._tool_map or parse_qualified_tool_name(name) is not None

    async def _ensure_client(self, server_name: str) -> McpClient:
        await self.reload_if_config_changed()
        if server_name in self._clients:
            client = self._clients[server_name]
            if client.is_running:
                return client
        cfg = self._configs.get(server_name)
        if cfg is None:
            raise McpError(f"Unknown MCP server: {server_name}")
        client = McpClient(cfg)
        await client.start()
        self._clients[server_name] = client
        return client

    async def _collect(
        self,
        server: str | None,
        method_name: str,
    ) -> dict[str, list[dict[str, Any]]]:
        names = [server] if server is not None else list(self._configs)
        output: dict[str, list[dict[str, Any]]] = {}
        for name in names:
            client = await self._ensure_client(name)
            method = getattr(client, method_name)
            output[name] = await method()
        return output

    def _record_config_fingerprint(self, path: Path) -> None:
        try:
            doc = load_raw_document(path)
            self._config_hash = hash_mcp_document(doc)
            self._last_mtime = path.stat().st_mtime
        except OSError:
            self._config_hash = None
            self._last_mtime = None
