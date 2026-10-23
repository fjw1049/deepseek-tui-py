"""Demonstrations become user-level skills with recorded site examples."""

import json
from pathlib import Path

import pytest
from octop_browser.record.models import RecordingManifest

from deepseek_tui.browser.recording import ScopedSemanticProcessor
from deepseek_tui.browser.service import BrowserService
from deepseek_tui.browser.skills import demonstration_summary, read_site, save_demonstration_skill
from deepseek_tui.browser.workflows import recording_store
from deepseek_tui.integrations.skills import SkillRegistry
from deepseek_tui.tools.browser_skill import BrowserSkillTool
from deepseek_tui.tools.registry import ApprovalRequirement, ToolContext, build_default_registry

PAGE = {"url": "https://shop.example/login?token=PRIVATE", "title": "Login"}
ACCOUNT = {"tag": "input", "type": "text", "role": "textbox", "label": "Account",
           "nameAttr": "loginId", "selectorCandidates": ['[name="loginId"]']}
PASSWORD = {**ACCOUNT, "type": "password", "label": "Password", "nameAttr": "password",
            "selectorCandidates": ['[name="password"]']}
SUBMIT = {"tag": "button", "role": "button", "name": "Sign in", "id": "go",
          "selectorCandidates": ['[id="go"]']}


@pytest.fixture
def service(tmp_path):
    service = BrowserService(tmp_path / "artifacts")
    store = recording_store(service, "one")
    manifest = RecordingManifest(recordingId="rec_login", createdAt="2026-10-15", status="stopped")
    manifest.stats.steps = 4
    store.create(manifest)
    events = [
        {"seq": 1, "kind": "recorder_installed", "targetId": "tab", "page": PAGE},
        {"seq": 2, "kind": "input", "targetId": "tab", "page": PAGE, "target": ACCOUNT,
         "value": "{{sensitive_value}}", "redacted": True},
        {"seq": 3, "kind": "input", "targetId": "tab", "page": PAGE, "target": PASSWORD,
         "value": "{{sensitive_value}}", "redacted": True},
        {"seq": 4, "kind": "click", "targetId": "tab", "page": PAGE, "target": SUBMIT},
    ]
    store.write_steps("rec_login", ScopedSemanticProcessor("rec_login", events).process())
    return service


def test_summary_shows_intent_without_selectors(service):
    summary = demonstration_summary(service, "one", "rec_login")
    assert summary["site"] == "shop.example"
    assert [item["name"] for item in summary["inputs"]] == ["loginid", "password"]
    assert [step["kind"] for step in summary["steps"]] == ["open", "fill", "fill", "click"]
    assert summary["steps"][2]["target"]["label"] == "Password"
    assert "selectorCandidates" not in json.dumps(summary)


def test_saved_skill_carries_procedure_and_site_example(service, tmp_path):
    skills = tmp_path / "skills"
    result = save_demonstration_skill(service, "one", "rec_login", "site-login",
                                      "Sign in to a website", "## Steps\n1. Open login", skills)
    directory = skills / "site-login"
    content = (directory / "SKILL.md").read_text(encoding="utf-8")
    assert result["site"] == "shop.example"
    assert content.startswith("---\nname: site-login\n") and "## Steps\n1. Open login" in content
    assert "`name=site-login`" in content and "run_site" in content and "PRIVATE" not in content
    assert read_site(directory) == {"sites": ["shop.example"]}
    example = read_site(directory, "shop.example")
    assert example["steps"][-1]["target"]["selectorCandidates"] == ['[id="go"]']
    with pytest.raises(ValueError, match="No recorded example"):
        read_site(directory, "../site-login/SKILL")
    with pytest.raises(ValueError):
        save_demonstration_skill(service, "one", "rec_login", "site-login",
                                 "Sign in to a website", "again", skills)


def test_incomplete_demonstration_cannot_become_a_skill(service, tmp_path):
    store = recording_store(service, "one")
    manifest = store.read_manifest("rec_login")
    manifest.status = "failed"
    store.write_manifest(manifest)
    with pytest.raises(ValueError, match="incomplete browser capture"):
        save_demonstration_skill(service, "one", "rec_login", "site-login",
                                 "Sign in", "steps", tmp_path / "skills")
    assert not (tmp_path / "skills").exists()


async def test_tool_saves_with_approval_and_reads_back_before_reload(
    service, tmp_path, monkeypatch
):
    monkeypatch.setattr("deepseek_tui.integrations.skills.default_skills_dir",
                        lambda: tmp_path / "skills")
    tool = BrowserSkillTool()
    context = ToolContext(working_directory=tmp_path, metadata={
        "browser_service": service, "runtime_thread_id": "one",
        "skill_registry": SkillRegistry()})
    requirement = tool.approval_requirement_for_input
    assert requirement({"action": "save"}) == ApprovalRequirement.REQUIRED
    assert requirement({"action": "read_demonstration"}) == ApprovalRequirement.AUTO
    read = await tool.execute(
        {"action": "read_demonstration", "recording_id": "rec_login"}, context)
    assert read.success and json.loads(read.content)["site"] == "shop.example"
    saved = await tool.execute({"action": "save", "recording_id": "rec_login", "name": "site-login",
                                "description": "Sign in", "instructions": "1. Open login"}, context)
    assert saved.success and Path(json.loads(saved.content)["path"]).is_file()
    sites = await tool.execute({"action": "read_site", "name": "site-login"}, context)
    assert json.loads(sites.content) == {"sites": ["shop.example"]}
    missing = await tool.execute({"action": "read_site", "name": "../escape"}, context)
    assert not missing.success


def test_tool_is_hidden_without_a_browser_thread(tmp_path):
    registry = build_default_registry(mode="agent")
    registry.set_context(ToolContext(working_directory=tmp_path))
    names = {tool["function"]["name"] for tool in registry.to_api_tools()}
    assert "browser_skill" not in names and "browser_use" not in names


async def test_tool_defaults_to_the_latest_completed_demonstration(service, tmp_path):
    store = recording_store(service, "one")
    store.create(RecordingManifest(recordingId="rec_newer_failed", createdAt="2026-10-16",
                                   status="failed"))
    tool = BrowserSkillTool()
    context = ToolContext(working_directory=tmp_path,
                          metadata={"browser_service": service, "runtime_thread_id": "one"})
    read = await tool.execute({"action": "read_demonstration"}, context)
    assert read.success and json.loads(read.content)["recordingId"] == "rec_login"
    other = ToolContext(working_directory=tmp_path,
                        metadata={"browser_service": service, "runtime_thread_id": "two"})
    empty = await tool.execute({"action": "read_demonstration"}, other)
    assert not empty.success and "No completed demonstration" in empty.content


def _agent_run(service, owner="agent"):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from deepseek_tui.browser.service import BrowserRun

    client = SimpleNamespace(send=AsyncMock(return_value={}))
    run = BrowserRun("one", service.artifact_root, owner=owner,
                     session=SimpleNamespace(_internal=SimpleNamespace(client=client)))
    service.runs["one"] = run
    return run


async def test_run_trace_stops_before_secrets_and_resumes_after_the_user(service, monkeypatch):
    from deepseek_tui.browser import workflows

    ran = []

    async def step(service, run, step, inputs):
        ran.append((step.id, step.value))
        return {"success": True}

    monkeypatch.setattr(workflows, "_step", step)
    _agent_run(service)
    doc = workflows.read_workflow(service, "one", "rec_login")
    secrets = {"password"}
    with pytest.raises(ValueError, match="entered by the user"):
        await workflows.run_trace(service, "one", doc, {"password": "x"}, secrets=secrets)
    with pytest.raises(ValueError, match="Missing string replay input: loginid"):
        await workflows.run_trace(service, "one", doc, {}, secrets=secrets)
    assert ran == []
    first = await workflows.run_trace(service, "one", doc, {"loginid": "alice"}, secrets=secrets)
    assert ran == [("step_001", ""), ("step_002", "alice")]
    assert first["stopped_at"]["id"] == "step_003" and first["stopped_at"]["reason"] == "needs_user"
    assert first["resume_from"] == "step_004"
    ran.clear()
    second = await workflows.run_trace(service, "one", doc, {"loginid": "alice"},
                                       secrets=secrets, from_step="step_004")
    assert ran == [("step_004", "")] and second["stopped_at"] is None
    assert second["completed"] == ["step_004"]


@pytest.mark.parametrize("reason", ["mismatch", "outcome_unknown", "failed"])
async def test_run_trace_hands_a_changed_page_back_to_the_agent(service, monkeypatch, reason):
    from deepseek_tui.browser import workflows
    from deepseek_tui.browser.service import BrowserActionError

    async def step(service, run, step, inputs):
        if step.kind == "open":
            return {"success": True}
        if reason == "mismatch":
            raise ValueError("Replay target must have one current, matching, observable element")
        if reason == "outcome_unknown":
            raise BrowserActionError({"content": "outcome unknown. Observe before retrying."})
        return {"success": False, "content": "Click was blocked"}

    monkeypatch.setattr(workflows, "_step", step)
    _agent_run(service)
    doc = workflows.read_workflow(service, "one", "rec_login")
    result = await workflows.run_trace(service, "one", doc, {"loginid": "a"}, secrets={"password"})
    assert result["completed"] == ["step_001"]
    assert result["stopped_at"]["id"] == "step_002" and result["stopped_at"]["reason"] == reason
    assert result["stopped_at"]["detail"] and "resume_from" not in result


async def test_run_trace_requires_agent_control(service):
    from deepseek_tui.browser import workflows

    _agent_run(service, owner="user")
    doc = workflows.read_workflow(service, "one", "rec_login")
    with pytest.raises(ValueError, match="user controls this browser"):
        await workflows.run_trace(service, "one", doc, {"loginid": "a"}, secrets={"password"})


async def test_tool_runs_a_saved_site_example_with_approval(service, tmp_path, monkeypatch):
    from deepseek_tui.browser import workflows

    monkeypatch.setattr("deepseek_tui.integrations.skills.default_skills_dir",
                        lambda: tmp_path / "skills")
    ran = []

    async def step(service, run, step, inputs):
        ran.append(step.id)
        return {"success": True}

    monkeypatch.setattr(workflows, "_step", step)
    _agent_run(service)
    save_demonstration_skill(service, "one", "rec_login", "site-login", "Sign in", "1. Open")
    tool = BrowserSkillTool()
    assert tool.approval_requirement_for_input(
        {"action": "run_site"}) == ApprovalRequirement.REQUIRED
    context = ToolContext(working_directory=tmp_path, metadata={
        "browser_service": service, "runtime_thread_id": "one", "skill_registry": SkillRegistry()})
    result = await tool.execute({"action": "run_site", "name": "site-login", "site": "shop.example",
                                 "inputs": {"loginid": "alice"}}, context)
    assert result.success and ran == ["step_001", "step_002"]
    assert json.loads(result.content)["stopped_at"]["reason"] == "needs_user"
    assert result.metadata["task_evidence"] is False


def _second_site(service, host):
    page = {"url": f"https://{host}/signin", "title": "Sign in"}
    store = recording_store(service, "one")
    manifest = RecordingManifest(recordingId="rec_other", createdAt="2026-10-16", status="stopped")
    manifest.stats.steps = 3
    store.create(manifest)
    events = [
        {"seq": 1, "kind": "recorder_installed", "targetId": "tab", "page": page},
        {"seq": 2, "kind": "input", "targetId": "tab", "page": page, "target": ACCOUNT,
         "value": "{{sensitive_value}}", "redacted": True},
        {"seq": 3, "kind": "click", "targetId": "tab", "page": page, "target": SUBMIT},
    ]
    store.write_steps("rec_other", ScopedSemanticProcessor("rec_other", events).process())


def test_add_site_extends_only_demonstration_skills(service, tmp_path):
    from deepseek_tui.browser.skills import add_site

    skills = tmp_path / "skills"
    save_demonstration_skill(service, "one", "rec_login", "site-login", "Sign in", "1. Open",
                             skills)
    _second_site(service, "travel.example")
    directory = skills / "site-login"
    assert add_site(service, "one", "rec_other", directory) == {
        "site": "travel.example", "replaced": False}
    assert read_site(directory) == {"sites": ["shop.example", "travel.example"]}
    assert add_site(service, "one", "rec_other", directory)["replaced"] is True
    third_party = tmp_path / "other"
    third_party.mkdir()
    (third_party / "SKILL.md").write_text("---\nname: other\n---\n", encoding="utf-8")
    with pytest.raises(ValueError, match="demonstrated skills"):
        add_site(service, "one", "rec_other", third_party)
    assert not list(third_party.glob("site-*.json"))


def test_capture_and_add_site_approvals():
    requirement = BrowserSkillTool().approval_requirement_for_input
    assert requirement({"action": "add_site"}) == ApprovalRequirement.REQUIRED
    assert requirement({"action": "capture_start"}) == ApprovalRequirement.AUTO
    assert requirement({"action": "capture_stop"}) == ApprovalRequirement.AUTO


LOGIN_PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>Shop</title></head><body>
<form onsubmit="event.preventDefault();document.getElementById('out').textContent=
'Welcome '+document.getElementById('account').value+
(document.getElementById('password').value?'!':'')">
<label>Account <input id="account" name="loginId"></label>
<label>Password <input id="password" name="password" type="password"></label>
<button id="go" type="submit">Sign in</button></form><p id="out"></p></body></html>"""


@pytest.mark.e2e
async def test_real_demonstration_becomes_a_skill_that_learns_a_second_site(
    tmp_path, monkeypatch
):
    """Explicit opt-in; real local Chromium against a local page, never a model."""
    import asyncio
    import functools
    import http.server
    import os
    import threading

    from deepseek_tui.browser.service import BrowserAction
    from deepseek_tui.browser.workflows import finish_recording, start_recording

    if os.environ.get("DEEPSEEK_BROWSER_E2E") != "1":
        pytest.skip("Set DEEPSEEK_BROWSER_E2E=1 to run real Chromium")
    (tmp_path / "login.html").write_text(LOGIN_PAGE, encoding="utf-8")
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=tmp_path)
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{httpd.server_address[1]}/login.html"
    monkeypatch.setattr("deepseek_tui.integrations.skills.default_skills_dir",
                        lambda: tmp_path / "skills")
    service = BrowserService(tmp_path / "artifacts")
    user = functools.partial(service.action, "flow", actor="user")
    try:
        await service.action("flow", BrowserAction(action="open", url=url))
        await service.control("flow", "user")
        await start_recording(service, "flow")
        await user(BrowserAction(action="fill", selector="#account", text="alice"))
        await user(BrowserAction(action="fill", selector="#password", text="PRIVATE-SECRET"))
        await user(BrowserAction(action="click", selector="#go"))
        await asyncio.sleep(0.5)
        demo = await finish_recording(service.runs["flow"])
        recorded = (tmp_path / "artifacts").rglob("*.json*")
        assert not any("PRIVATE-SECRET" in path.read_text() for path in recorded)
        await service.control("flow", "agent")

        tool = BrowserSkillTool()
        context = ToolContext(working_directory=tmp_path, metadata={
            "browser_service": service, "runtime_thread_id": "flow",
            "skill_registry": SkillRegistry()})
        saved = await tool.execute({"action": "save", "recording_id": demo["recordingId"],
                                    "name": "shop-login", "description": "Sign in",
                                    "instructions": "1. Fill account 2. Fill password"}, context)
        assert saved.success, saved.content
        run = {"action": "run_site", "name": "shop-login", "site": "127.0.0.1",
               "inputs": {"loginid": "bob"}}
        first = json.loads((await tool.execute(run, context)).content)
        assert first["stopped_at"]["reason"] == "needs_user", first

        await service.control("flow", "user")
        await user(BrowserAction(action="fill", selector="#password", text="typed-by-user"))
        await service.control("flow", "agent")
        second = json.loads((await tool.execute(
            {**run, "from_step": first["resume_from"]}, context)).content)
        assert second["stopped_at"] is None, second
        check = await service.action(
            "flow", BrowserAction(action="check_text", text="Welcome bob!"))
        assert check["success"]

        # The same page under another host is a site the skill has not seen yet.
        other = url.replace("127.0.0.1", "localhost")
        await service.action("flow", BrowserAction(action="open", url=other))
        started = await tool.execute({"action": "capture_start"}, context)
        assert started.success, started.content
        await service.action("flow", BrowserAction(action="fill", selector="#account", text="eve"))
        await service.control("flow", "user")
        await user(BrowserAction(action="fill", selector="#password", text="PRIVATE-SECRET"))
        await service.control("flow", "agent")
        assert service.runs["flow"].recorder is not None
        await service.action("flow", BrowserAction(action="click", selector="#go"))
        await asyncio.sleep(0.5)
        captured = await tool.execute({"action": "capture_stop"}, context)
        assert captured.success and json.loads(captured.content)["steps"] == 4, captured.content
        added = await tool.execute({"action": "add_site", "name": "shop-login"}, context)
        assert json.loads(added.content) == {"site": "localhost", "replaced": False}
        sites = await tool.execute({"action": "read_site", "name": "shop-login"}, context)
        assert json.loads(sites.content) == {"sites": ["127.0.0.1", "localhost"]}
        third = json.loads((await tool.execute(
            {**run, "site": "localhost", "inputs": {"loginid": "mallory"}}, context)).content)
        assert third["completed"] == ["step_001", "step_002"], third
        assert third["stopped_at"]["reason"] == "needs_user"
        files = [*(tmp_path / "artifacts").rglob("*.json*"), *(tmp_path / "skills").rglob("*")]
        assert not any("PRIVATE-SECRET" in path.read_text() for path in files if path.is_file())
    finally:
        await service.close_all()
        httpd.shutdown()
