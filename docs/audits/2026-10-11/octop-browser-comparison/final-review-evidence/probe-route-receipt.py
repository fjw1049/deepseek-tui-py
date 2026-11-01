"""Characterize the current API/tool contract with an injected uncertain outcome."""
import asyncio
import json
from types import SimpleNamespace

from fastapi import HTTPException
from deepseek_tui.browser.service import BrowserAction, BrowserActionError
from deepseek_tui.server.browser_routes import action
from deepseek_tui.tools.browser import BrowserUseTool

receipt = {
    "success": False,
    "content": "Transport disconnected; outcome unknown. Observe before retrying.",
    "artifact": None,
    "receipt": {"action_id": "synthetic_action", "action": "reload", "execution": "unknown", "effect": "unchecked"},
}
class Browser:
    runs = {"one": object()}
    async def action(self, *args, **kwargs):
        raise BrowserActionError(receipt)

async def main():
    browser = Browser()
    manager = SimpleNamespace(browser_service=browser, store=SimpleNamespace(load_thread=lambda _: None))
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(thread_manager=manager)))
    api = None
    try:
        await action(request, "one", BrowserAction(action="reload", generation=2))
    except HTTPException as exc:
        api = {"status": exc.status_code, "detail": exc.detail}
    tool = await BrowserUseTool().execute({"action": "reload"}, SimpleNamespace(metadata={"browser_service": browser, "runtime_thread_id": "one"}))
    assert isinstance(api["detail"], str)
    assert tool.metadata["browser"]["receipt"]["execution"] == "unknown"
    print(json.dumps({"scope": "synthetic injected BrowserActionError; not an actual transport fault", "http": api, "tool_metadata": tool.metadata}, ensure_ascii=False, indent=2))

asyncio.run(main())
