"""Workbench-hosted pages: the app's native browser tabs, driven through its CDP bridge.

When Workbench runs, agents and users share the tabs it shows. The bridge only accepts
loopback connections carrying its token; tab lifecycle belongs to Workbench, so tab
operations become ``Workbench.*`` requests instead of browser-level CDP targets.
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

from octop_browser import BrowserSession, OctopSettings
from octop_browser.cdp.client import CDPClient
from octop_browser.models import ActionMetrics, ToolResult
from octop_browser.profile import ProfileManager
from octop_browser.session import _InternalCDPSession

OPEN_TIMEOUT = 15


def tab_url(bridge: dict[str, Any], tab_id: str) -> str:
    return f"ws://127.0.0.1:{bridge['port']}/tab/{quote(tab_id, safe='')}?token={bridge['token']}"


async def control(bridge: dict[str, Any], method: str, params: dict[str, Any]) -> dict[str, Any]:
    """One request to Workbench itself rather than to a tab."""
    import websockets

    url = f"ws://127.0.0.1:{bridge['port']}/control?token={bridge['token']}"
    async with websockets.connect(url, open_timeout=3) as ws:
        await ws.send(json.dumps({"id": 1, "method": method, "params": params}))
        reply = json.loads(await asyncio.wait_for(ws.recv(), OPEN_TIMEOUT))
    if "error" in reply:
        raise RuntimeError(reply["error"].get("message") or "Workbench browser is unavailable")
    return reply["result"]


async def open_session(bridge: dict[str, Any], browser_id: str) -> list[dict[str, Any]]:
    """Ask Workbench to show this browser and return its tabs."""
    tabs = (await control(bridge, "Workbench.openSession", {"browserId": browser_id}))["tabs"]
    if not tabs:
        raise RuntimeError("Workbench browser has no tabs")
    return tabs


class _NativeInternal(_InternalCDPSession):
    async def _apply_viewport(self) -> None:
        """The page keeps the size of the panel the user sees."""


class WorkbenchBrowserSession(BrowserSession):
    bridge: dict[str, Any]
    tab_id: str

    @classmethod
    async def attach(cls, bridge: dict[str, Any], browser_id: str, directory: Path):
        tabs = await open_session(bridge, browser_id)
        tab = next((item for item in tabs if item.get("active")), tabs[0])
        cfg = OctopSettings(profiles_dir=directory, cdp_ws_url=tab_url(bridge, tab["tab_id"]))
        profiles = ProfileManager(base_dir=directory, settings=cfg)
        internal = _NativeInternal(profiles.get_or_create("workbench"), cfg)
        await internal.connect()
        session = cls(internal, "workbench")
        session.bridge, session.tab_id = bridge, tab["tab_id"]
        return session, cfg, profiles

    async def _workbench(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        return await self._internal.client.send("Workbench." + method, params or {})

    async def _reconnect(self, tab_id: str) -> None:
        internal = self._internal
        await internal._client.close()
        internal._client = CDPClient(timeout=internal._cfg.cdp_timeout,
                                     activity_tracker=internal._idle_controller)
        internal._ref_cache.invalidate()
        await internal._client.connect(tab_url(self.bridge, tab_id))
        for domain in ("Page", "DOM", "Runtime"):
            await internal._client.enable_domain(domain)
        self.tab_id = tab_id

    @staticmethod
    def _result(action: str, started: float, content: str = "", *, error: str | None = None,
                metadata: dict[str, object] | None = None) -> ToolResult:
        return ToolResult(success=error is None, content=error or content, error=error,
                          metadata=metadata, metrics=ActionMetrics(
                              action=action, duration_ms=int((time.monotonic() - started) * 1000),
                              dom_nodes_scanned=0, estimated_tokens=len(content) // 4))

    async def list_tabs(self) -> ToolResult:
        started = time.monotonic()
        try:
            # "active" is the tab this session drives; "shown" the one the user sees.
            tabs = [{**tab, "shown": tab["active"], "active": tab["tab_id"] == self.tab_id}
                    for tab in (await self._workbench("listTabs"))["tabs"]]
        except Exception as exc:  # noqa: BLE001 - reported like octop's own tab errors
            return self._result("list_tabs", started, error=str(exc))
        content = "\n".join(f"[{t['tab_id']}] {t['title'] or '(no title)'} — {t['url']}"
                            for t in tabs) or "(no open tabs)"
        return self._result("list_tabs", started, content, metadata={"tabs": tabs})

    async def new_tab(self, url: str | None = None, force_new: bool = False) -> ToolResult:
        started = time.monotonic()
        try:
            tab_id = (await self._workbench("createTab", {"url": url or "about:blank"}))["tabId"]
            await self._reconnect(tab_id)
        except Exception as exc:  # noqa: BLE001
            return self._result("new_tab", started, error=str(exc))
        return self._result("new_tab", started, tab_id)

    async def switch_tab(self, tab_id: str) -> ToolResult:
        started = time.monotonic()
        try:
            await self._workbench("activateTab", {"tabId": tab_id})
            if tab_id != self.tab_id:
                await self._reconnect(tab_id)
        except Exception as exc:  # noqa: BLE001
            return self._result("switch_tab", started, error=str(exc))
        return self._result("switch_tab", started, tab_id)

    async def close_tab(self, tab_id: str) -> ToolResult:
        started = time.monotonic()
        try:
            await self._workbench("closeTab", {"tabId": tab_id})
        except Exception as exc:  # noqa: BLE001
            return self._result("close_tab", started, error=str(exc))
        return self._result("close_tab", started, tab_id)
