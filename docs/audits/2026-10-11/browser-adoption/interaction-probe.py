"""Exercise the real service's observation-token contract with mocked CDP/input.

This is a boundary probe, not a real browser or language-model task. Both fill
requests are prepared before the first result, as in a single model tool batch.
No existing source file is changed.
"""
from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

sys.dont_write_bytecode = True
repo = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(repo / "src"))
from deepseek_tui.browser.service import BrowserAction, BrowserRun, BrowserService


async def main() -> None:
    frame = {"id": "tab", "loaderId": "doc", "url": "https://fixture.test"}
    page = {"url": frame["url"], "title": "Fixture", "text": "Form",
            "elements": [{"ref": "e0", "role": "input", "name": "Name"},
                         {"ref": "e1", "role": "input", "name": "City"}]}
    input_commands = []

    async def send(method, params=None):
        if method == "Page.getFrameTree":
            return {"frameTree": {"frame": frame}}
        if method == "Runtime.evaluate":
            # JavaScript target validation is the mocked boundary. The service's
            # Python observation ID and document checks still execute unchanged.
            value = {"selector": "#fixture-field", "x": 20, "y": 20} if (
                params["expression"].startswith("(a=>{")) else page
            return {"result": {"value": value}}
        if method.startswith("Input."):
            input_commands.append(method)
            return {}
        raise AssertionError(method)

    click = AsyncMock(return_value=SimpleNamespace(success=True, content="clicked"))
    session = SimpleNamespace(click=click, _internal=SimpleNamespace(
        client=SimpleNamespace(send=AsyncMock(side_effect=send))))
    with tempfile.TemporaryDirectory(prefix="browser-adoption-") as directory:
        root = Path(directory)
        service = BrowserService(root)
        service.runs["t"] = BrowserRun("t", root / "t", session=session)
        initial = await service.action("t", BrowserAction(action="observe"))
        observation_id = initial["observation"]["observation_id"]
        requests = [BrowserAction(action="fill", ref=ref, text=value,
                                  observation_id=observation_id)
                    for ref, value in [("e0", "Demo"), ("e1", "City")]]
        results = [await service.action("t", request, require_observation=True)
                   for request in requests]
        assert results[0]["receipt"]["execution"] == "executed"
        assert results[1]["receipt"]["execution"] == "not_executed"
        assert results[1]["receipt"]["reason"] == "stale_observation"
        assert click.await_count == 1
        result = {
            "boundary": "real BrowserService / observe / target Python logic; mocked CDP and click",
            "interpretation": "Expected safety contract: prebuilt second call is rejected after the first refreshes observation. Not a real model task failure.",
            "first_execution": results[0]["receipt"]["execution"],
            "second_execution": results[1]["receipt"]["execution"],
            "second_reason": results[1]["receipt"]["reason"],
            "first_action_changed_observation_id": results[0]["observation"]["observation_id"] != observation_id,
            "actual_click_dispatch_count": click.await_count,
            "input_commands": input_commands,
        }
        output = Path(__file__).with_name("interaction-probe-result.json")
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
