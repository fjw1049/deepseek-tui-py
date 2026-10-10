"""2026-10-10 audit probes: assert current defects, NOT fixed behavior.

Run: .venv/bin/python -m pytest scratch/browser_audit_probe.py -q
No network, real account, or production browser is used.
"""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from deepseek_tui.browser.service import BrowserAction, BrowserRun, BrowserService
from deepseek_tui.config.models import Config, FeatureConfig
from deepseek_tui.engine.handle import EngineHandle
from deepseek_tui.engine.orchestrator import Engine
from deepseek_tui.engine.turn import TurnResult
from deepseek_tui.protocol.messages import Message
from deepseek_tui.tools.runtime import create_tool_runtime


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CLAUDE_PLUGINS_DIR", str(tmp_path / "plugins"))


@pytest.mark.parametrize("narration", [
    '出现了搜索建议列表。点第一项"洗浴中心"获取完整结果和评分。',
    "百度地图出结果了。把排序改成按好评，看看评分最高的几家。",
    "已按评分排序。点开排第一的那家看具体评分和详情。",
    "川沙在浦东。按川沙为中心重新搜洗浴场所，再排评分。",
])
async def test_main_loop_accepts_recorded_unfinished_narration(tmp_path, narration):
    cfg = Config(features=FeatureConfig(mcp=False, automations=False))
    runtime = await create_tool_runtime(
        config=cfg, working_directory=tmp_path, mode="agent",
        task_data_dir=tmp_path / "tasks", start_mcp=False,
    )
    handle = EngineHandle()
    engine = await Engine.create(
        handle=handle, client=AsyncMock(), config=cfg,
        working_directory=tmp_path, tool_runtime=runtime,
    )
    engine._handle_subagent_turn_handoff = AsyncMock(return_value=False)
    engine._handle_shell_process_turn_handoff = AsyncMock(return_value=False)
    engine.turn_loop = SimpleNamespace(run=AsyncMock(return_value=TurnResult(
        assistant_message=Message.assistant(narration), tool_calls=[],
    )))
    try:
        result = await engine._run_conversation(
            messages=[Message.user("用浏览器推荐附近评分好的洗浴场所。我在川沙。")],
            model="deepseek-chat", system_prompt="Complete the requested browser task.",
            max_tokens=None,
        )
        assert engine.turn_loop.run.await_count == 1
        assert result.assistant_message.text_content() == narration
        assert result.tool_round_count == 0
    finally:
        await engine.shutdown_session()
        await runtime.shutdown()
        handle.drain_events()


async def test_full_observation_loses_plain_text_and_includes_hidden_controls(tmp_path):
    from octop_browser import BrowserSession
    from octop_browser.dom.refs import RefCache

    # A representative raw CDP tree. The real Octop extraction is exercised;
    # only the browser transport is replaced, not the DOM builder.
    dom = {"nodeName": "BODY", "nodeId": 1, "children": [
        {"nodeName": "DIV", "nodeId": 2, "children": [
            {"nodeName": "SPAN", "nodeId": 3, "children": [
                {"nodeName": "#text", "nodeValue": "川沙测试浴场 4.8分 距离800米"},
            ]},
        ]},
        {"nodeName": "DIV", "nodeId": 4, "attributes": ["hidden", ""], "children": [
            {"nodeName": "BUTTON", "nodeId": 5, "children": [
                {"nodeName": "#text", "nodeValue": "隐藏登录按钮"},
            ]},
        ]},
    ]}

    async def send(method, params=None):
        if method == "DOM.getDocument":
            return {"root": dom}
        if method == "Runtime.evaluate":
            return {"result": {"value": json.dumps({"url": "https://example.test", "title": "Test"})}}
        if method == "Page.getFrameTree":
            return {"frameTree": {"frame": {"url": "https://example.test"}}}
        raise AssertionError(method)

    session = BrowserSession(SimpleNamespace(
        client=SimpleNamespace(send=send), ref_cache=RefCache(),
    ), "audit")
    session._record = AsyncMock()
    service = BrowserService(tmp_path)
    run = BrowserRun("audit", tmp_path, session=session)
    service.runs["audit"] = run
    result = await service.action("audit", BrowserAction(action="observe", level="full"))
    assert result["success"]
    assert "川沙测试浴场" not in result["content"]
    assert "4.8" not in result["content"]
    assert "隐藏登录按钮" in result["content"]


async def test_wait_matching_existing_url_does_not_wait_for_results():
    from octop_browser import BrowserSession

    send = AsyncMock(return_value={"result": {"value": json.dumps({
        "url": "https://www.amap.com/search", "text": "加载中", "selector": None,
    })}})
    session = BrowserSession(SimpleNamespace(client=SimpleNamespace(send=send)), "audit")
    session._record = AsyncMock()
    result = await session.wait(url_contains="amap.com", timeout_ms=3000)
    assert result.success
    assert send.await_count == 1
