"""Opt-in macOS integration: open Calculator, Soda Music and a disposable TextEdit file."""

import asyncio
import json
import os
import subprocess
import sys
from uuid import uuid4

import pytest

from deepseek_tui.config.models import CuaConfig
from deepseek_tui.cua.approval import auto_allow_response
from deepseek_tui.cua.session import CuaSession


@pytest.mark.skipif(
    sys.platform != "darwin" or os.getenv("RUN_CUA_NATIVE") != "1",
    reason="requires an authorized real Mac desktop with Soda Music installed",
)
async def test_three_native_apps_and_a_queued_second_player(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    document = tmp_path / f"CUA parallel check {uuid4().hex[:8]}.txt"
    document.write_text("workbench-native-check")
    await asyncio.to_thread(subprocess.run, ["open", "-a", "TextEdit", str(document)], check=True)
    for identifier in ("com.apple.calculator", "com.soda.music"):
        await asyncio.to_thread(subprocess.run, ["open", "-b", identifier], check=True)
    # open(1) can return before the native window exists.
    from deepseek_tui.cua.apps import open_window_count

    for identifier in ("com.soda.music", "com.apple.calculator", "com.apple.TextEdit"):
        for attempt in range(30):
            if await asyncio.to_thread(open_window_count, identifier):
                break
            if attempt in (5, 15):
                await asyncio.to_thread(subprocess.run, ["open", "-b", identifier], check=True)
            await asyncio.sleep(0.2)
        else:
            pytest.fail(f"No capturable window for {identifier}")
    apps = ["com.soda.music", "com.apple.calculator", "com.apple.TextEdit", "com.soda.music"]

    async def approve(params):
        return auto_allow_response(params) or {"action": "cancel"}

    sessions = [CuaSession(CuaConfig(), tmp_path, uuid4().hex, approve) for _ in apps]

    async def call(i, name, args):
        result = await sessions[i].call(name, args, f"live-{i}", uuid4().hex)
        texts = [b["text"] for b in result.get("content", []) if b.get("type") == "text"]
        assert not result.get("isError"), str(texts)[-1200:]
        return result

    async def bind(i):
        return await call(i, "js", {"code": f"let app = await cua.getApp({json.dumps(apps[i])});"})

    try:
        await asyncio.wait_for(asyncio.gather(*(bind(i) for i in range(3))), 90)
        assert all(s.lease.app == app for s, app in zip(sessions[:3], apps[:3], strict=True))
        waiter = asyncio.create_task(bind(3))
        await asyncio.sleep(0.4)
        assert not waiter.done()
        before = await call(2, "observe", {"app": apps[2]})
        assert document.name in before["observation"]["text"]
        assert "workbench-native-check" in before["observation"]["text"]
        await asyncio.gather(
            call(
                2,
                "js",
                {"code": 'await app.pressKey("super+a"); await app.typeText("并行校验-317");'},
            ),
            call(
                1,
                "js",
                {
                    "code": ('await app.pressKey("Escape"); await app.pressKey("7"); '
                             'await app.pressKey("9");')
                },
            ),
        )
        results = await asyncio.gather(*(call(i, "observe", {"app": apps[i]}) for i in range(3)))
        assert "并行校验-317" in results[2]["observation"]["text"]
        assert "79" in results[1]["observation"]["text"]
        for result in results[:2]:
            assert "并行校验-317" not in result["observation"]["text"]
        for result in results:
            assert any(block.get("type") == "image" for block in result["content"])
        await sessions[0].end_turn()
        await asyncio.wait_for(waiter, 30)
        assert sessions[1].lease.fd is not None and sessions[2].lease.fd is not None
    finally:
        if "waiter" in locals():
            waiter.cancel()
            await asyncio.gather(waiter, return_exceptions=True)
        await asyncio.gather(*(session.close() for session in sessions))


@pytest.mark.skipif(
    sys.platform != "darwin" or os.getenv("RUN_CUA_NATIVE") != "1",
    reason="requires an authorized real Mac desktop with TextEdit",
)
async def test_typed_actions_edit_a_disposable_document_and_reobserve_after_release(tmp_path, monkeypatch):
    from deepseek_tui.cua.tools import CuaActTool, CuaObserveTool
    from deepseek_tui.tools.registry import ToolContext

    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    document = tmp_path / f"CUA typed check {uuid4().hex[:8]}.txt"
    document.write_text("temporary-cua-document")
    await asyncio.to_thread(subprocess.run, ["open", "-a", "TextEdit", str(document)], check=True)

    async def approve(params):
        return auto_allow_response(params) or {"action": "cancel"}

    session = CuaSession(CuaConfig(), tmp_path, uuid4().hex, approve)
    context = ToolContext(tmp_path, metadata={"cua_turn_id": "typed-live"})
    app = "com.apple.TextEdit"

    async def execute(tool, request):
        context.metadata["cua_call_id"] = uuid4().hex
        return await tool.execute(request, context)

    try:
        observe = CuaObserveTool(session)
        before = await execute(observe, {"app": app, "expect": [document.name], "wait_ms": 5000})
        assert before.success and document.name in before.content, before.content
        act = CuaActTool(session)
        written = await execute(act, {"app": app, "actions": [
            {"type": "key", "key": "super+a"},
            {"type": "type", "text": "真实中文输入校验-317"},
        ]})
        assert written.success and "真实中文输入校验-317" in written.content, written.content
        assert session.lease.app == app
        await session.end_turn()
        request = {"app": app, "actions": [{"type": "type", "text": "-恢复后输入"}]}
        held = await execute(act, request)
        assert not held.success and held.metadata["cua_stats"]["replaced_by_observation"], held.content
        assert "真实中文输入校验-317" in held.content and "-恢复后输入" not in held.content
        resumed = await execute(act, request)
        assert resumed.success and "-恢复后输入" in resumed.content, resumed.content
        # Saving this disposable document uses a non-local shortcut and holds the desktop.
        saved = await execute(act, {"app": app, "actions": [{"type": "key", "key": "super+s"}]})
        assert saved.success and session.lease.fd is not None and session.lease.app is None, saved.content
        for _ in range(20):
            if "-恢复后输入" in document.read_text():
                break
            await asyncio.sleep(0.1)
        assert document.read_text() == "真实中文输入校验-317-恢复后输入"
    finally:
        await session.close()
        # Close only the uniquely named test document, preserving other open documents.
        await asyncio.to_thread(subprocess.run, ["osascript", "-e",
            'on run argv\n tell application "TextEdit"\n'
            ' if exists document (item 1 of argv) then close document (item 1 of argv) saving no\n'
            ' end tell\nend run', document.name], check=True, capture_output=True)
