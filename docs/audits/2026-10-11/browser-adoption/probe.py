"""Read-only adoption audit: real service/target methods, mocked browser/CDP.

Run from repository root with PYTHONDONTWRITEBYTECODE=1 .venv/bin/python
docs/audits/2026-10-11/browser-adoption/probe.py. No browser, model, website,
network, account, or persistent BrowserService storage is used.
"""
import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "src"))

from deepseek_tui.browser.service import BrowserAction, BrowserRun, BrowserService


def fixture(pause_at=None, evaluate_delay=0, observe_delay=0, condition=False):
    entered, released = asyncio.Event(), asyncio.Event()
    events = []
    run = BrowserRun("synthetic", Path(__file__).parent, url="https://fixture.invalid")
    run.latest_observation = {"observation_id": "obs_1", "control_generation": 0,
                              "tab_id": "frame_1", "document_id": "loader_1"}

    class CDP:
        async def send(self, method, params=None):
            if method == pause_at:
                entered.set()
                await released.wait()
            if method == "Page.getFrameTree":
                return {"frameTree": {"frame": {"id": "frame_1", "loaderId": "loader_1",
                                                  "url": run.url}}}
            if method == "Runtime.evaluate":
                if params.get("returnByValue") is False:
                    return {"result": {"objectId": "mock_object"}}
                if "window.__deepseekObservation" in params["expression"]:
                    value = {"nested": True} if pause_at == "DOM.getDocument" else {
                        "selector": '[data-deepseek-target="synthetic"]', "x": 10, "y": 10}
                else:
                    await asyncio.sleep(evaluate_delay)
                    value = condition
                return {"result": {"value": value}}
            if method == "DOM.requestNode":
                return {"nodeId": 10}
            return {}

    async def click(**kwargs):
        events.append({"event": "mock_browser_click", "owner_at_dispatch": run.owner,
                       "generation_at_dispatch": run.generation,
                       "transferring_at_dispatch": run.transferring})
        return SimpleNamespace(success=True, content="mock dispatched")

    async def observed(_run, **kwargs):
        await asyncio.sleep(observe_delay)
        observation = {"observation_id": "obs_after", "control_generation": run.generation}
        run.latest_observation = observation
        return observation

    run.session = SimpleNamespace(click=click, _internal=SimpleNamespace(
        client=CDP(), ref_cache=SimpleNamespace(store=lambda *args: None)))
    service = BrowserService.__new__(BrowserService)
    service.runs = {run.thread_id: run}
    service._persist = lambda _run: None
    service.state = lambda _tid: {"owner": run.owner, "generation": run.generation}
    return service, run, entered, released, events, observed


async def transfer_case(pause_at):
    service, run, entered, released, events, observed = fixture(pause_at=pause_at)
    with patch("deepseek_tui.browser.service.observe", observed):
        task = asyncio.create_task(service.action(run.thread_id, BrowserAction(
            action="click", ref="e0", observation_id="obs_1"), require_observation=True))
        await asyncio.wait_for(entered.wait(), 1)
        transfer = asyncio.create_task(service.control(run.thread_id, "user"))
        await asyncio.sleep(0)
        events.append({"event": "transfer_requested", "owner": run.owner,
                       "generation": run.generation, "transfer_completed": transfer.done()})
        released.set()
        response = await asyncio.wait_for(task, 1)
        await asyncio.wait_for(transfer, 1)
    assert events[0]["transfer_completed"] is False
    assert events[1]["owner_at_dispatch"] == "user"
    assert events[1]["transferring_at_dispatch"] is True
    assert response["receipt"]["execution"] == "executed"
    return {"case": pause_at, "verified": True, "events": events,
            "interpretation": "Current service lock defines an already-started atomic action; "
                              "transfer response waits for it. Not a click after completed transfer."}


async def wait_case(evaluate_delay=0, observe_delay=0, condition=False):
    service, run, _, _, _, observed = fixture(evaluate_delay=evaluate_delay,
                                             observe_delay=observe_delay, condition=condition)
    with patch("deepseek_tui.browser.service.observe", observed):
        started = asyncio.get_running_loop().time()
        response = await service.action(run.thread_id, BrowserAction(
            action="wait", text="synthetic condition", timeout_ms=1))
        elapsed_ms = round((asyncio.get_running_loop().time() - started) * 1000)
    assert elapsed_ms >= 60
    assert response["success"] == condition
    return {"condition_timeout_ms": 1, "mock_evaluate_delay_ms": int(evaluate_delay * 1000),
            "mock_post_observation_delay_ms": int(observe_delay * 1000),
            "elapsed_ms": elapsed_ms, "success": response["success"], "verified": True,
            "interpretation": "timeout_ms bounds condition polling softly; it is not "
                              "a per-CDP or whole-action hard deadline."}


async def main():
    results = {
        "boundary": "Real BrowserService.action/control/_action and observation.target; "
                    "mocked CDP responses, click, observation, persistence, state.",
        "production_browser_or_model_invoked": False,
        "transfers": [await transfer_case("Page.getFrameTree"),
                      await transfer_case("DOM.getDocument")],
        "waits": [await wait_case(evaluate_delay=0.08),
                  await wait_case(observe_delay=0.08, condition=True)],
    }
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
