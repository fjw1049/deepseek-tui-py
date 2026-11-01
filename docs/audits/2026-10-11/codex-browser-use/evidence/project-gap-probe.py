"""Reproduce browser result projection and scroll dispatch at defined boundaries.

Run with this project's environment, for example:
  PYTHONDONTWRITEBYTECODE=1 .venv/bin/python /private/tmp/rea-review/project-gap-probe.py

The observations are synthetic inputs to the real context/spillover functions.
The scroll test invokes the real BrowserService.action with mocked CDP/session
and target resolution. The Octop wheel test invokes its real scroll function
with a mocked CDP client. No Chrome, real website, or real model is invoked.
"""

import argparse
import asyncio
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.dont_write_bytecode = True


def synthetic_observation(count, text_chars, long_names=False):
    return {
        "url": "https://example.test",
        "title": "Results",
        "text": ("Visible content. " * (text_chars // 17 + 1))[:text_chars],
        "elements": [
            {
                "ref": f"e{i}",
                "role": "button",
                "name": f"Control {i:03d} " + (
                    "x" * 100 if long_names else "long enough to name accurately"
                ),
                "box": {"x": 20, "y": i * 30, "width": 120, "height": 24},
            }
            for i in range(count)
        ],
        "observation_id": "obs_current",
        "tab_id": "tab",
        "document_id": "doc",
        "control_generation": 0,
    }


def context_probe(output_dir):
    from deepseek_tui.engine.context import (
        _tool_result_context_limits,
        compact_tool_result_for_context,
    )
    from deepseek_tui.tools.registry import ToolResult
    from deepseek_tui.tools.runtime import apply_spillover, set_test_spillover_root

    cases = []
    previous = set_test_spillover_root(output_dir / "spillover")
    try:
        for count, text_chars, long_names in (
            (120, 8000, False), (250, 8000, False), (250, 16000, True)
        ):
            observation = synthetic_observation(count, text_chars, long_names)
            # Match service.py's observe content plus complete observation field.
            response = {
                "success": True,
                "content": json.dumps(observation),
                "artifact": None,
                "receipt": {"execution": "executed", "effect": "unchecked"},
                "observation": observation,
            }
            raw = json.dumps(response)
            result = ToolResult(True, raw, metadata={"browser": response})
            # Match tooling.py:465-472: spillover, then context projection.
            spilled = apply_spillover(result, f"browser_observe_{count}_{text_chars}")
            projected = compact_tool_result_for_context(
                "deepseek-chat", "browser_use", spilled
            )
            cases.append({
                "boundary": "synthetic observation -> real spillover/context projection",
                "control_count": count,
                "visible_text_chars": len(observation["text"]),
                "context_limits": _tool_result_context_limits("deepseek-chat"),
                "raw_chars": len(raw),
                "after_spillover_chars": len(spilled.content),
                "projected_chars": len(projected),
                "observation_id_preserved": "obs_current" in projected,
                "middle_ref_preserved": f'"e{count // 2}"' in projected,
                "middle_name_preserved": f"Control {count // 2:03d}" in projected,
                "spillover_reread_path_present": "Full output saved" in projected,
            })
    finally:
        set_test_spillover_root(previous)
    return cases


async def scroll_probe(output_dir):
    from deepseek_tui.browser.service import BrowserAction, BrowserRun, BrowserService
    from octop_browser.actions.interact import scroll

    with tempfile.TemporaryDirectory(prefix="service-scroll-", dir=output_dir) as temp:
        root = Path(temp)
        service = BrowserService(root)
        page = {"text": "Fixture", "elements": [], "url": "https://example.test"}

        async def send(method, params=None):
            if method == "Page.getFrameTree":
                return {"frameTree": {"frame": {
                    "id": "tab", "loaderId": "doc", "url": page["url"]
                }}}
            if method == "Runtime.evaluate":
                return {"result": {"value": page}}
            raise AssertionError(method)

        session = SimpleNamespace(
            scroll=AsyncMock(return_value=SimpleNamespace(success=True, content="Scrolled")),
            _internal=SimpleNamespace(client=SimpleNamespace(send=AsyncMock(side_effect=send))),
        )
        service.runs["t"] = BrowserRun("t", root, session=session)
        target = {"selector": "#nested-list", "x": 80, "y": 650}
        with patch("deepseek_tui.browser.service.target", AsyncMock(return_value=target)):
            result = await service.action(
                "t", BrowserAction(action="scroll", ref="e2", observation_id="current",
                                   direction="down", amount=300), require_observation=True,
            )
        service_case = {
            "boundary": "real BrowserService.action; mocked target/CDP/session, no Chrome",
            "validated_target": target,
            "actual_scroll_arguments": session.scroll.call_args.kwargs,
            "receipt_execution": result["receipt"]["execution"],
        }
        client = SimpleNamespace(send=AsyncMock(return_value={}))
        await scroll(client, None, direction="right", amount=300)
        dependency_case = {
            "boundary": "real installed Octop scroll; mocked CDP client, no Chrome",
            "requested_direction": "right",
            "requested_amount": 300,
            "actual_cdp_method": client.send.call_args.args[0],
            "actual_cdp_parameters": client.send.call_args.args[1],
        }
        return [service_case, dependency_case]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path,
                        default=Path("/Users/fjw/Desktop/deepseek-tui-py-main"))
    parser.add_argument("--output-dir", type=Path,
                        default=Path("/private/tmp/rea-review/project-gap-probe-output"))
    args = parser.parse_args()
    sys.path.insert(0, str(args.repo.resolve() / "src"))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "scope": "Synthetic/mocked boundary probes; no real model/browser success claims.",
        "context_projection": context_probe(args.output_dir),
        "scroll_dispatch": asyncio.run(scroll_probe(args.output_dir)),
    }
    text = json.dumps(report, ensure_ascii=False, indent=2)
    (args.output_dir / "result.json").write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
