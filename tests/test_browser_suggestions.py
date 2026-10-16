"""Repeated agent workflows become skill suggestions without keeping old captures."""

import pytest
from octop_browser.record.models import SemanticStep, StepsDocument

from deepseek_tui.browser import suggestions as module
from deepseek_tui.browser.suggestions import SkillSuggestions, signature


def doc(*steps):
    return StepsDocument(recordingId="rec", startUrl="https://shop.example/", steps=[
        SemanticStep(id=f"step_{index:03d}", kind=kind, target=target, value="{{secret}}")
        for index, (kind, target) in enumerate(steps, 1)])


SEARCH = doc(("open", None), ("fill", {"role": "textbox", "name": "Search"}),
             ("click", {"role": "button", "name": "Go"}))


def test_signature_ignores_values_and_skips_browsing():
    masked_differently = SEARCH.model_copy(deep=True)
    masked_differently.steps[1].value = "{{other}}"
    assert signature(SEARCH, "shop.example") == signature(masked_differently, "shop.example")
    assert signature(SEARCH, "shop.example") != signature(SEARCH, "travel.example")
    assert signature(doc(("open", None), ("click", {"name": "Next"})), "shop.example") is None


def test_third_repetition_suggests_once_and_keeps_only_the_latest_capture(tmp_path):
    store = SkillSuggestions(tmp_path / "index.json")
    assert store.observe("a", "rec_1", SEARCH, "shop.example", set()) == []
    assert store.observe("b", "rec_2", SEARCH, "shop.example", set()) == [("a", "rec_1")]
    assert not store.pending
    assert store.observe("c", "rec_3", SEARCH, "shop.example", set()) == [("b", "rec_2")]
    assert store.pending["c"] == {"id": signature(SEARCH, "shop.example"),
                                  "site": "shop.example", "count": 3, "recording_id": "rec_3"}
    assert store.resolve("c", accepted=False)["recording_id"] == "rec_3"
    # Dismissed patterns stop suggesting and stop keeping captures.
    assert store.observe("d", "rec_4", SEARCH, "shop.example", set()) == [
        ("c", "rec_3"), ("d", "rec_4")]
    assert not store.pending
    reloaded = SkillSuggestions(tmp_path / "index.json")
    assert next(iter(reloaded.data["patterns"].values()))["closed"] == "dismissed"
    with pytest.raises(ValueError):
        reloaded.resolve("c", accepted=True)


def test_covered_sites_trivial_runs_and_disabled_store_do_not_suggest(tmp_path):
    store = SkillSuggestions(tmp_path / "index.json")
    for index in range(3):
        store.observe("a", f"rec_{index}", SEARCH, "shop.example", {"shop.example"})
    assert not store.pending
    browse = doc(("open", None), ("click", {"name": "Next"}))
    assert store.observe("a", "rec_x", browse, "shop.example", set()) == [("a", "rec_x")]
    store.set_enabled(False)
    store.observe("a", "rec_y", SEARCH, "shop.example", set())
    assert not store.pending and SkillSuggestions(tmp_path / "index.json").enabled is False


def test_oldest_patterns_are_evicted_with_their_captures(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "MAX_PATTERNS", 2)
    store = SkillSuggestions(tmp_path / "index.json")
    sites = ["one.example", "two.example", "three.example"]
    discarded = [store.observe("a", f"rec_{site}", SEARCH, site, set()) for site in sites]
    assert discarded[-1] == [("a", "rec_one.example")]
    assert {entry["site"] for entry in store.data["patterns"].values()} == set(sites[1:])


SEARCH_PAGE = """<!doctype html><html><meta charset="utf-8"><title>Find</title>
<input id="q" name="q" placeholder="Search"><button id="go">Search</button><p id="out"></p>
<script>document.querySelector('#go').onclick=()=>{document.querySelector('#out')
.textContent='Results for '+document.querySelector('#q').value}</script></html>"""


async def test_user_demonstration_replaces_a_background_capture(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from deepseek_tui.browser import recording, workflows
    from deepseek_tui.browser.service import BrowserRun, BrowserService

    service = BrowserService(tmp_path)
    run = BrowserRun("one", tmp_path, owner="user", session=object())
    run.recorder = SimpleNamespace(actor="agent", auto=True)
    service.runs["one"] = run

    async def end(thread_id, *, completed):
        assert not completed
        run.recorder = None

    monkeypatch.setattr(service, "end_agent_capture", end)
    monkeypatch.setattr(recording, "create_recording",
                        AsyncMock(return_value=("demo", {"recordingId": "rec_demo"})))
    assert (await workflows.start_recording(service, "one"))["recordingId"] == "rec_demo"
    assert run.recorder == "demo"


@pytest.mark.e2e
async def test_real_repeated_agent_search_is_suggested_with_one_kept_capture(
    tmp_path, monkeypatch
):
    """Explicit opt-in; real local Chromium driven through the agent's browser tool."""
    import functools
    import http.server
    import json
    import os
    import threading

    from deepseek_tui.browser.service import BrowserService
    from deepseek_tui.tools.browser import BrowserUseTool
    from deepseek_tui.tools.browser_skill import BrowserSkillTool
    from deepseek_tui.tools.registry import ToolContext

    if os.environ.get("DEEPSEEK_BROWSER_E2E") != "1":
        pytest.skip("Set DEEPSEEK_BROWSER_E2E=1 to run real Chromium")
    (tmp_path / "find.html").write_text(SEARCH_PAGE, encoding="utf-8")
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=tmp_path)
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{httpd.server_address[1]}/find.html"
    monkeypatch.setattr("deepseek_tui.integrations.skills.default_skills_dir",
                        lambda: tmp_path / "skills")
    service = BrowserService(tmp_path / "artifacts")
    tool = BrowserUseTool()

    async def use(context, **arguments):
        result = await tool.execute(arguments, context)
        assert result.success, result.content
        return json.loads(result.content)

    async def act(context, kind, name, **arguments):
        observation = (await use(context, action="observe", level="full"))["observation"]
        assert "Recording" not in json.dumps(observation)
        ref = next(e["ref"] for e in observation["elements"] if e.get("name") == name)
        await use(context, action=kind, ref=ref,
                  observation_id=observation["observation_id"], **arguments)

    try:
        for index, thread in enumerate(["t1", "t2", "t3", "t4"], 1):
            context = ToolContext(working_directory=tmp_path, metadata={
                "browser_service": service, "runtime_thread_id": thread})
            await use(context, action="open", url=url)
            await act(context, "fill", "Search", text=f"query {index}")
            await act(context, "click", "Search")
            await service.end_agent_capture(thread, completed=True)
            assert service.runs[thread].recorder is None
            assert bool(service.state(thread)["skill_suggestion"]) == (index >= 3)
        assert service.state("t3")["skill_suggestion"] is None
        suggestion = service.state("t4")["skill_suggestion"]
        assert suggestion["count"] == 4 and suggestion["site"] == "127.0.0.1"
        kept = list((tmp_path / "artifacts").glob("*/flows/recordings/rec_*"))
        assert [path.name for path in kept] == [suggestion["recording_id"]]
        summary = await BrowserSkillTool().execute(
            {"action": "read_demonstration", "recording_id": suggestion["recording_id"]},
            context)
        assert [s["kind"] for s in json.loads(summary.content)["steps"]] == [
            "open", "fill", "click"]
        service.suggestions.resolve("t4", accepted=True)
        assert service.state("t4")["skill_suggestion"] is None
    finally:
        await service.close_all()
        httpd.shutdown()


def test_replacing_capture_removes_suggestions_that_reference_it(tmp_path):
    store = SkillSuggestions(tmp_path / "index.json")
    for index in range(1, 4):
        store.observe(str(index), f"rec_{index}", SEARCH, "shop.example", set())
    assert "3" in store.pending
    discarded = store.observe("4", "rec_4", SEARCH, "shop.example", set())
    assert ("3", "rec_3") in discarded
    assert "3" not in store.pending
    assert store.pending["4"]["recording_id"] == "rec_4"
