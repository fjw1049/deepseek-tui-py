"""Workspace pages open without a local server, and only workspace pages reach the model."""

import asyncio
import json
import os
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from deepseek_tui.browser.permissions import (
    local_page_allowed,
    navigation_needs_approval,
    origin_of,
    preview,
    site_trust,
)
from deepseek_tui.browser.service import BrowserAction, BrowserService
from deepseek_tui.tools.browser import BrowserUseTool
from deepseek_tui.tools.registry import ToolContext


def test_local_page_stays_inside_the_workspace(tmp_path):
    page = tmp_path / "site" / "index.html"
    page.parent.mkdir()
    page.write_text("<p>ok")
    (tmp_path / "escape").symlink_to("/etc")

    assert local_page_allowed(page.as_uri(), tmp_path)
    assert local_page_allowed(page.as_uri() + "?tab=1#top", tmp_path)
    assert local_page_allowed("https://example.test", tmp_path)
    assert not local_page_allowed("file:///etc/passwd", tmp_path)
    assert not local_page_allowed(f"file://{tmp_path}/../outside.html", tmp_path)
    assert not local_page_allowed(f"file://{tmp_path}/escape/passwd", tmp_path)
    assert not local_page_allowed(f"file://{tmp_path}/%2e%2e/outside.html", tmp_path)
    assert not local_page_allowed(f"file://evil.test{tmp_path}/index.html", tmp_path)
    assert not local_page_allowed(page.as_uri(), None)


def test_only_a_caller_that_names_a_workspace_opens_files(tmp_path):
    action = {"action": "open", "url": (tmp_path / "index.html").as_uri()}
    assert BrowserAction.model_validate(action, context={"local_root": tmp_path}).url
    with pytest.raises(ValidationError):
        BrowserAction.model_validate(action)
    with pytest.raises(ValidationError):
        BrowserAction.model_validate(
            {"action": "open", "url": "file:///etc/passwd"}, context={"local_root": tmp_path})


def test_blank_page_opens_without_a_workspace():
    assert BrowserAction(action="open", url="about:blank").url == "about:blank"


@pytest.mark.parametrize("url,asks", [
    ("about:blank", False), ("file:///w/index.html", False),
    ("http://127.0.0.1:3000/", False), ("https://example.test/", True),
])
def test_only_remote_navigation_asks(url, asks):
    assert navigation_needs_approval({"action": "open", "url": url}) is asks


def test_workspace_pages_share_one_session_approval():
    assert origin_of("file:///w/a.html") == origin_of("file:///w/b.html")
    assert site_trust(origin_of("file:///w/a.html")) == "site"


def test_approval_card_names_the_element_when_observation_id_is_omitted():
    run = SimpleNamespace(url="https://shop.test/", latest_observation={
        "observation_id": "obs", "url": "https://shop.test/",
        "elements": [{"ref": "e1", "name": "Place order", "role": "button"}],
    })
    card = preview(run, {"action": "click", "ref": "e1"}, "en")
    assert "Place order" in card["title"]


async def _call_with_page(tmp_path, url):
    async def action(*args, **kwargs):
        return {"success": True, "content": "", "artifact": None,
                "observation": {"url": url, "text": "SECRET", "elements": []}}

    browser = SimpleNamespace(action=action, runs={})
    context = ToolContext(working_directory=tmp_path,
                          metadata={"browser_service": browser, "runtime_thread_id": "t"})
    return await BrowserUseTool().execute({"action": "observe"}, context)


async def test_page_outside_the_workspace_is_withheld(tmp_path):
    result = await _call_with_page(tmp_path, "file:///etc/passwd")
    assert not result.success
    assert "SECRET" not in result.content


async def test_page_inside_the_workspace_is_returned(tmp_path):
    result = await _call_with_page(tmp_path, (tmp_path / "index.html").as_uri())
    assert result.success
    assert "SECRET" in result.content


async def test_real_browser_reads_workspace_page_but_not_a_linked_file(tmp_path):
    if os.environ.get("DEEPSEEK_BROWSER_E2E") != "1":
        pytest.skip("Set DEEPSEEK_BROWSER_E2E=1 for actual Chrome")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.html"
    outside.write_text("<p>OUTSIDE_SENTINEL</p>")
    page = workspace / "index.html"
    page.write_text(f"<title>Local</title><p>INSIDE_SENTINEL</p><a href='{outside.as_uri()}'>go</a>")
    service = BrowserService(tmp_path / "artifacts", profile_root=tmp_path / "private")
    service.configure("t", persistent=False)
    context = ToolContext(working_directory=workspace,
                          metadata={"browser_service": service, "runtime_thread_id": "t"})
    tool = BrowserUseTool()
    try:
        opened = await tool.execute({"action": "open", "url": page.as_uri()}, context)
        assert opened.success, opened.content
        assert "INSIDE_SENTINEL" in opened.content
        link = next(e for e in json.loads(opened.content)["observation"]["elements"]
                    if e.get("name") == "go")
        result = await tool.execute({"action": "click", "ref": link["ref"]}, context)
        await asyncio.sleep(0.2)
        observed = await tool.execute({"action": "observe"}, context)
        assert not observed.success and "OUTSIDE_SENTINEL" not in observed.content
        assert "OUTSIDE_SENTINEL" not in result.content
    finally:
        await service.close("t")
