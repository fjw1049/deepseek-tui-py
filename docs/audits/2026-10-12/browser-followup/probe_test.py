"""Local audit probes: a passing probe confirms the described boundary, not safety.

Uses current project Chrome fixtures with a temporary profile and localhost only.
No external website, credentials or language model is used; source is unchanged.
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "tests"))
from test_browser_chromium import act, chrome, read
from deepseek_tui.browser.context import project_result
from deepseek_tui.browser.observation import evaluate


def save(name, result):
    Path(__file__).with_name(name + ".json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    )


async def test_page_can_rebind_main_world_observed_ref(chrome):
    service, run = chrome
    client = run.session._internal.client
    await evaluate(client, """document.body.innerHTML=`
      <button id=expected onclick='window.expectedClicks++'>Preview</button>
      <button id=other onclick='window.otherClicks++'>Preview</button>`;
      window.expectedClicks=0;window.otherClicks=0;true""")
    observation = await read(service)
    ref = next(e["ref"] for e in observation["elements"] if e.get("selector") == "#expected")
    # This runs in the webpage's main world, where ordinary page JavaScript runs.
    # It changes only a Map entry, leaving DOM, revision and control IDs unchanged.
    await evaluate(client,
        "window.__deepseekObservation.refs.get(" + json.dumps(ref)
        + ").element=document.querySelector('#other');true")
    response = await act(service, observation, "click", ref=ref)
    counts = await evaluate(client, "[window.expectedClicks,window.otherClicks]")
    save("main-world-ref", {
        "boundary": "Real Chrome/current BrowserService; controlled local page counters only",
        "target_originally_observed": "#expected", "ref": ref,
        "expected_clicks": counts[0], "other_clicks": counts[1],
        "receipt": response["receipt"],
        "interpretation": "Page-accessible ref Map can redirect the validated target without changing observation identity.",
    })
    assert counts == [0, 1]
    assert response["receipt"]["execution"] == "executed"


async def test_dom_quiet_is_only_point_in_time_field_confirmation(chrome):
    service, run = chrome
    client = run.session._internal.client
    await evaluate(client, """document.body.innerHTML=`<input id=q value=old
      oninput=\"setTimeout(()=>this.value='old',900)\">`;true""")
    observation = await read(service)
    started = time.monotonic()
    response = await act(service, observation, "fill", selector="#q", text="replacement")
    elapsed = round((time.monotonic() - started) * 1000)
    immediate = await evaluate(client, "document.querySelector('#q').value")
    await asyncio.sleep(1)
    later = await evaluate(client, "document.querySelector('#q').value")
    save("delayed-rollback", {
        "boundary": "Real Chrome/current BrowserService; controlled local input only",
        "rollback_delay_ms": 900, "response_elapsed_ms": elapsed,
        "fixture_value_at_return": immediate, "fixture_value_after_delay": later,
        "receipt": response["receipt"],
        "interpretation": "DOM quiet plus value equality confirms an instant; it does not establish acceptance by an asynchronous application.",
    })
    assert response["receipt"]["effect"] == "confirmed"
    assert immediate == "replacement" and later == "old"


def test_oversized_option_detail_has_no_explicit_continuation_after_fallback():
    # The option value is within BrowserAction.text's 8000 character input limit.
    result = {"success": True, "observation": {
        "observation_id": "obs-current", "tab_id": "tab", "document_id": "doc",
        "scope_selector": None, "text": "",
        "elements": [{"ref": "e0", "role": "select", "name": "Choice",
                      "options": [{"value": "v" * 7000, "text": "Large choice"}],
                      "option_offset": 0, "total_options": 1, "next_option_offset": None}],
    }}
    data = json.loads(project_result(result, 6000))
    element = data["observation"]["elements"][0]
    save("oversized-detail", {
        "boundary": "Real project_result; synthetic observation and 6000-character budget",
        "input_option_value_chars": 7000, "projected_element": element,
        "context_truncated": data["observation"].get("context_truncated"),
        "interpretation": "Fallback retains ref/role/name but drops options and their continuation; generic truncation alone does not identify what detail to fetch.",
    })
    assert "options" not in element and "next_option_offset" not in element

