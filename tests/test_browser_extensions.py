"""Installation lifecycle and generated Skill discovery/install behavior."""

import asyncio
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from deepseek_tui.browser import BrowserService
from deepseek_tui.browser_install import BrowserInstaller
from deepseek_tui.browser_skills import install_skill, preview_skill
from deepseek_tui.integrations.skills import discover_in_workspace


@pytest.mark.asyncio
async def test_cancel_before_installer_starts_updates_status():
    installer = BrowserInstaller()
    installer.start()
    await installer.close()
    assert installer.state["status"] == "stopped"


@pytest.mark.asyncio
@pytest.mark.parametrize("success", [True, False])
async def test_installer_reports_terminal_status_and_bounds_log(monkeypatch, success):
    from deepseek_tui import browser_install

    reader = asyncio.StreamReader()
    for index in range(60):
        reader.feed_data((json.dumps({"log": str(index)}) + "\n").encode())
    reader.feed_data((json.dumps({"done": True, "success": success}) + "\n").encode())
    reader.feed_eof()
    process = SimpleNamespace(stdout=reader, wait=AsyncMock(return_value=0), pid=123, returncode=0)
    monkeypatch.setattr(
        browser_install.asyncio, "create_subprocess_exec", AsyncMock(return_value=process)
    )
    monkeypatch.setattr(browser_install.os, "killpg", Mock(), raising=False)
    installer = BrowserInstaller()
    installer.start()
    task = installer.task
    installer.start()
    assert installer.task is task
    await task
    assert installer.state["status"] == ("passed" if success else "failed")
    assert len(installer.state["logs"]) == 40


@pytest.mark.asyncio
@pytest.mark.skipif(os.name == "nt", reason="POSIX process group cleanup")
async def test_cancel_install_kills_owned_process_group(monkeypatch):
    from deepseek_tui import browser_install

    process = SimpleNamespace(
        stdout=asyncio.StreamReader(), wait=AsyncMock(return_value=0), pid=123
    )
    launch = AsyncMock(return_value=process)
    kill = Mock()
    monkeypatch.setattr(browser_install.asyncio, "create_subprocess_exec", launch)
    monkeypatch.setattr(browser_install.os, "killpg", kill)
    installer = BrowserInstaller()
    installer.start()
    await asyncio.sleep(0)
    await installer.close()
    assert installer.state["status"] == "stopped"
    assert launch.call_args.kwargs["start_new_session"]
    kill.assert_called_once()


def test_skill_preview_install_discovery_and_no_overwrite(tmp_path, monkeypatch):
    from deepseek_tui import browser_skills

    models = pytest.importorskip("octop_browser.record.models")
    doc = models.StepsDocument(
        recordingId="rec_test",
        startUrl="file:///demo.html",
        inputs=[{"name": "name", "example": "private", "required": True}],
        steps=[
            models.SemanticStep(id="1", kind="open", url="file:///demo.html"),
            models.SemanticStep(id="2", kind="fill", value="{{name}}", target={"id": "name"}),
        ],
    )
    monkeypatch.setattr(browser_skills, "read_workflow", lambda *args: doc)
    service = BrowserService(tmp_path / "artifacts")
    args = (service, "one", "rec_test", "save-project", "保存项目设置；用户要求重复此流程时使用")
    preview = preview_skill(*args)
    assert "private" not in preview["content"]
    assert "file:///demo.html" not in preview["content"]
    with pytest.raises(ValueError, match="preview changed"):
        install_skill(*args, "old-digest", tmp_path)
    result = install_skill(*args, preview["digest"], tmp_path)
    registry = discover_in_workspace(workspace=tmp_path)
    skill = registry.get("save-project")
    assert skill and "browser_use" in skill.allowed_tools
    assert Path(result["path"]).read_text() == preview["content"]
    with pytest.raises(ValueError, match="already exists"):
        install_skill(*args, preview["digest"], tmp_path)
    assert Path(result["path"]).read_text() == preview["content"]
    with pytest.raises(ValueError, match="Skill name"):
        preview_skill(service, "one", "rec_test", "../escape", "test")
