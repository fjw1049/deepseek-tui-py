"""Local-only browser harness audit probes; no model API or external website."""

from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from deepseek_tui.browser.observation import evaluate
from deepseek_tui.browser.service import BrowserAction, BrowserActionError, BrowserService
from deepseek_tui.browser.workflows import _step
from deepseek_tui.engine.context import compact_tool_result_for_context
from deepseek_tui.config.providers import configured_context_window
from deepseek_tui.tools.browser import BrowserUseTool


async def main() -> None:
    results: dict = {}

    async def serve(reader, writer):
        try:
            await reader.readuntil(b"\r\n\r\n")
            page = b"<!doctype html><meta charset=utf-8><title>Audit fixture</title><body>Fixture</body>"
            writer.write(
                b"HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\nContent-Length: "
                + str(len(page)).encode()
                + b"\r\nConnection: close\r\n\r\n"
                + page
            )
            await writer.drain()
        except asyncio.IncompleteReadError:
            pass
        finally:
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_server(serve, "127.0.0.1", 0)
    second = await asyncio.start_server(serve, "127.0.0.1", 0)
    url = f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}"
    other = f"http://127.0.0.1:{second.sockets[0].getsockname()[1]}"
    with tempfile.TemporaryDirectory(prefix="octop-harness-probe-") as directory:
        service = BrowserService(Path(directory))
        try:
            await service.action("audit", BrowserAction(action="open", url=url))
            run = service.runs["audit"]
            client = run.session._internal.client

            async def js(expression):
                return await evaluate(client, expression)

            async def page(html):
                await js("document.body.innerHTML=" + json.dumps(html))
                return (
                    await service.action("audit", BrowserAction(action="observe", level="full"))
                )["observation"]

            async def act(action, observation, **kwargs):
                return await service.action(
                    "audit",
                    BrowserAction(
                        action=action, observation_id=observation["observation_id"], **kwargs
                    ),
                    require_observation=True,
                )

            context = SimpleNamespace(
                metadata={"browser_service": service, "runtime_thread_id": "audit"}
            )
            await page(
                "<p>" + "Reading material. " * 400 + "</p>"
                + "".join(
                    f"<button>Control {i:03d} " + "name " * 10 + "</button>"
                    for i in range(100)
                )
            )
            output = await BrowserUseTool().execute({"action": "observe"}, context)
            raw = json.loads(output.content)
            compacted = compact_tool_result_for_context(
                "gpt-4o", "browser_use", output, pressure_ratio=0.6
            )
            results["context_compaction"] = {
                "raw_chars": len(output.content),
                "model_chars": len(compacted),
                "context_window": configured_context_window("gpt-4o"),
                "raw_element_count": len(raw["observation"]["elements"]),
                "model_remaining_refs": compacted.count('"ref":'),
                "model_has_first_ref": '"ref": "e0"' in compacted,
                "content_duplicates_observation": json.loads(raw["content"]) == raw["observation"],
                "model_snippet": compacted,
            }

            observation = await page(
                """<div style='height:600px;width:100px;overflow:auto' role='textbox' id=box>
                <div style='height:2000px'>Scrollable</div></div>"""
            )
            scrolled = await act("scroll", observation, selector="#box", amount=300)
            await asyncio.sleep(0.15)
            results["targeted_scroll"] = {
                "success": scrolled["success"],
                "target_scroll_top": await js("document.querySelector('#box').scrollTop"),
            }
            await page("<div style='width:4000px;height:4000px'>Large</div>")
            await js("window.lastWheel=null;window.onwheel=e=>window.lastWheel={x:e.deltaX,y:e.deltaY}")
            observation = (
                await service.action("audit", BrowserAction(action="observe"))
            )["observation"]
            right = await act("scroll", observation, direction="right", amount=300)
            await asyncio.sleep(0.15)
            results["horizontal_scroll"] = {
                "success": right["success"], "actual_wheel": await js("window.lastWheel")
            }
            await js("window.scrollTo(0,0);true")

            observation = await page("<select id=s><option value=valid>Valid</option></select>")
            selected = await act("select", observation, selector="#s", text="missing")
            results["invalid_select"] = {
                "success": selected["success"],
                "execution": selected["receipt"]["execution"],
                "actual_value": await js("document.querySelector('#s').value"),
                "actual_index": await js("document.querySelector('#s').selectedIndex"),
            }
            observation = await page(
                "<button id=submit onclick='window.badFill=(window.badFill||0)+1'>Submit</button>"
            )
            bad_fill = await act("fill", observation, selector="#submit", text="draft")
            results["fill_non_editable"] = {
                "success": bad_fill["success"],
                "button_clicks": await js("window.badFill"),
            }

            observation = await page("<input aria-label=Draft id=q value=old>")
            await js("document.querySelector('#q').focus();document.querySelector('#q').setSelectionRange(3,3);true")
            pressed = await act("press", observation, key="Ctrl+A")
            results["keyboard_chord"] = {
                "success": pressed["success"],
                "selection": await js("[document.querySelector('#q').selectionStart,document.querySelector('#q').selectionEnd]"),
            }
            await page("<input aria-label=Draft id=q value=old>")
            step = SimpleNamespace(
                kind="fill", target={"selectorCandidates": ["#q"]}, value="replacement"
            )
            replayed = await _step(run, step, {})
            replay_value = await js("document.querySelector('#q').value")
            observation = (
                await service.action("audit", BrowserAction(action="observe"))
            )["observation"]
            filled = await act("fill", observation, selector="#q", text="replacement")
            results["replay_fill"] = {
                "replay_success": replayed.success, "replay_value": replay_value,
                "browser_use_success": filled["success"],
                "browser_use_value": await js("document.querySelector('#q').value"),
            }

            observation = await page("<p>" + "x" * 16500 + " LATE_SENTINEL</p>")
            checked = await service.action(
                "audit", BrowserAction(action="check_text", text="LATE_SENTINEL")
            )
            results["text_limit"] = {
                "actual_page_has_sentinel": await js("document.body.textContent.includes('LATE_SENTINEL')"),
                "observation_chars": len(observation["text"]),
                "truncated": observation["truncated"], "check_success": checked["success"],
            }
            observation = await page("".join(f"<button>Button {i}</button>" for i in range(270)))
            results["element_limit"] = {
                "actual_buttons": 270, "returned_elements": len(observation["elements"]),
                "truncated": observation["truncated"],
                "has_last_button": any(e["name"] == "Button 269" for e in observation["elements"]),
            }

            observation = await page("<input type=checkbox role=checkbox aria-label=Check id=q>")
            await js("document.querySelector('#q').onclick=e=>e.preventDefault();true")
            checked = await act("set_checked", observation, selector="#q", checked=True)
            results["set_checked_postcondition"] = {
                "success": checked["success"],
                "actual_checked": await js("document.querySelector('#q').checked"),
            }

            observation = await page("<button id=go onclick='window.count=(window.count||0)+1'>Submit</button>")
            run.recording = True
            capture = service._capture
            service._capture = AsyncMock(side_effect=RuntimeError("audit capture failure"))
            try:
                await act("click", observation, selector="#go")
            except BrowserActionError as error:
                results["recording_failure_after_click"] = {
                    "actual_clicks": await js("window.count"),
                    "execution": error.response["receipt"]["execution"],
                    "success": error.response["success"],
                }
            finally:
                service._capture = capture
                run.recording = False

            observation = await page(
                "<button onclick='window.count=(window.count||0)+1'>One</button>"
                "<button onclick='window.count=(window.count||0)+1'>Two</button>"
            )
            await act("click", observation, ref="e0")
            stale = await act("click", observation, ref="e1")
            results["batch_refs"] = {
                "second_success": stale["success"], "reason": stale["receipt"]["reason"]
            }

            await page("<button id=popup onclick=\"window.open('/popup')\">Popup</button>")
            observation = (
                await service.action("audit", BrowserAction(action="observe"))
            )["observation"]
            clicked = await act("click", observation, selector="#popup")
            tabs = await service.action("audit", BrowserAction(action="tabs"))
            results["popup_discovery"] = {
                "click_response_has_tabs": "tabs" in clicked,
                "click_observation_url": clicked["observation"]["url"],
                "explicit_tabs_count": len(tabs["tabs"]),
                "session_state_tabs_count": len(service.state("audit")["tabs"]),
            }

            await page(f"<iframe src='{other}'></iframe>")
            await asyncio.sleep(0.2)
            observation = (
                await service.action("audit", BrowserAction(action="observe"))
            )["observation"]
            results["cross_origin_frame"] = {
                "warnings": observation["warnings"],
                "frame_text_seen": "Fixture" in observation["text"],
                "has_frame_id_in_observation": "frames" in observation,
            }
            await run.session._internal.client.close()
            try:
                await BrowserUseTool().execute({"action": "status"}, context)
            except Exception as error:
                results["dead_session"] = {
                    "tool_exception": type(error).__name__,
                    "ensure_returns_same_session": await service.ensure("audit") is run,
                    "ui_still_claims_active": service.state("audit")["active"],
                }
        finally:
            await service.close_all()
    server.close()
    second.close()
    await server.wait_closed()
    await second.wait_closed()
    path = Path(__file__).with_name("probe-results.json")
    path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
