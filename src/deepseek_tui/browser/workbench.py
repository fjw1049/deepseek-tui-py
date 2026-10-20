"""Workbench-hosted pages: the app's native browser tabs, driven through its CDP bridge.

When Workbench runs, agents and users share the tabs it shows. The bridge only accepts
loopback connections carrying its token; tab lifecycle belongs to Workbench, so tab
operations become ``Workbench.*`` requests instead of browser-level CDP targets.
"""

from __future__ import annotations

import asyncio
import json
import time
from contextlib import suppress
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
    browser_id: str
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
        session.bridge, session.browser_id, session.tab_id = bridge, browser_id, tab["tab_id"]
        return session, cfg, profiles

    async def _workbench(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        # Tab lifecycle must survive the page socket being destroyed by the user.
        return await control(self.bridge, "Workbench." + method,
                             {**(params or {}), "browserId": self.browser_id})

    @property
    def connected(self) -> bool:
        from websockets.protocol import State

        ws = self._internal.client._ws
        return ws is not None and ws.state == State.OPEN

    async def bind_tab(self, tab_id: str = "") -> bool:
        """Bind an explicit human request, or the shown tab, without changing the UI."""
        tabs = await open_session(self.bridge, self.browser_id)
        tab = next((item for item in tabs if item["tab_id"] == tab_id), None) if tab_id else next(
            (item for item in tabs if item.get("active")), tabs[0])
        if tab is None:
            raise ValueError("Requested browser tab no longer exists")
        if tab["tab_id"] == self.tab_id and self.connected:
            return False
        await self._reconnect(tab["tab_id"])
        return True

    async def _reconnect(self, tab_id: str) -> None:
        internal = self._internal
        client = CDPClient(timeout=internal._cfg.cdp_timeout,
                           activity_tracker=internal._idle_controller)
        try:
            await client.connect(tab_url(self.bridge, tab_id))
            for domain in ("Page", "DOM", "Runtime"):
                await client.enable_domain(domain)
        except BaseException:
            with suppress(Exception):
                await client.close()
            raise
        previous, internal._client = internal._client, client
        internal._ref_cache.invalidate()
        internal._cfg.cdp_ws_url = tab_url(self.bridge, tab_id)
        self.tab_id = tab_id
        await previous.close()

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
