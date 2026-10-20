from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path

import pytest

from deepseek_tui.config.models import Config, CuaConfig
from deepseek_tui.cua.approval import approval_question, approval_response
from deepseek_tui.cua.session import CuaSession, DesktopLease
from deepseek_tui.cua.tools import CuaTool
from deepseek_tui.tools.registry import ToolContext, ToolError, ToolResult


@pytest.fixture
def native():
    return {
        "mode": "form",
        "message": "Allow Notes?",
        "requestedSchema": {"type": "object", "properties": {}},
        "_meta": {
            "connector_id": "computer-use",
            "tool_params": {"app": "com.apple.Notes"},
            "persist": ["session"],
        },
    }


def test_approval_does_not_widen_scope(native):
    question = approval_question(native)
    assert [o["value"] for o in question["options"]] == ["decline", "once", "session"]

    def answer(value):
        return approval_response(native, {"answers": [{"id": "cua_permission", "value": value}]})

    assert answer("always") == {"action": "cancel"}
    assert answer("session") == {"action": "accept", "content": {}, "_meta": {"persist": "session"}}
    assert answer("once") == {"action": "accept", "content": {}}
    assert approval_response(native, None) == {"action": "cancel"}
    native["_meta"]["tool_params"]["app"] = "com.xingyuzhong.deepseekgui"
    assert approval_question(native) is None


def test_browser_exact_origin_and_unknown_forms(native):
    native["_meta"] = {"tool_name": "access_browser_origin", "origin": "https://example.com"}
    assert len(approval_question(native)["options"]) == 2
    native["_meta"]["origin"] = "https://example.com/path"
    assert approval_question(native) is None
    native["_meta"]["origin"] = "https://example.com"
    native["requestedSchema"]["properties"] = {"password": {"type": "string"}}
    assert approval_question(native) is None


@pytest.fixture
def installation(tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node required for bridge integration tests")
    root = tmp_path / "lcu"
    (root / "adapters").mkdir(parents=True)
    (root / "bin").mkdir()
    (root / "node-path").write_text(node)
    (root / "bin/lcu").write_text("fixture")
    shutil.copy(Path(__file__).parent / "fixtures/cua/client.mjs", root / "adapters/client.mjs")
    return CuaConfig(enabled=True, installation=root)


@pytest.fixture
def session(installation, tmp_path):
    session = CuaSession(installation, tmp_path, "session-a")
    session.lease = DesktopLease(tmp_path / "desktop.lock")
    return session


@pytest.mark.asyncio
async def test_bridge_catalog_metadata_and_cleanup(session, tmp_path):
    try:
        await session.connect()
        assert session.instructions.startswith("Original fixture")
        assert [t["name"] for t in session.descriptors] == ["js", "js_reset"]
        result = await session.call("js", {"code": "hello"}, "turn-a", "call-a")
        assert result["content"][0]["text"] == "hello"
        assert session.lease.fd is not None
        await session.end_turn()
        assert session.lease.fd is None
        entries = [json.loads(line) for line in (tmp_path / "calls.jsonl").read_text().splitlines()]
        assert entries[0]["hostTurn"] == "turn-a"
        assert entries[0]["turn"].startswith("turn-a:cua:")
        assert entries[0]["call"] == "call-a"
        assert entries[1]["end"]["event"] == "Stop"
        assert entries[1]["end"]["turnId"] == entries[0]["turn"]
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_idle_takeover_releases_lease_and_blocks_stale_code(session, tmp_path):
    await session.connect()
    pause = asyncio.Event()
    tool = CuaTool(session, session.descriptors[0], [pause])
    context = ToolContext(tmp_path, metadata={"cua_turn_id": "t", "cua_call_id": "c"})
    try:
        await tool.execute({"code": "hello"}, context)
        monitor = session._monitor
        pause.set()
        await asyncio.wait_for(monitor, 2)
        assert session.process is None
        assert session.lease.fd is None
        pause.clear()
        with pytest.raises(ToolError, match="entry point"):
            await tool.execute({"code": "oldApp.click()"}, context)
        entries = [json.loads(line) for line in (tmp_path / "calls.jsonl").read_text().splitlines()]
        assert len([entry for entry in entries if "args" in entry]) == 1
        assert any(entry.get("end", {}).get("event") == "Interrupt" for entry in entries)
        result = await tool.execute({"code": "fresh observation"}, context)
        assert result.success
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_stop_interrupts_connection_initialization(session, monkeypatch):
    entered = asyncio.Event()

    async def connect():
        entered.set()
        await asyncio.Future()

    monkeypatch.setattr(session, "connect", connect)
    stop = asyncio.Event()
    task = asyncio.create_task(session.run(session.connect, [stop]))
    await entered.wait()
    stop.set()
    with pytest.raises(ToolError, match="interrupted"):
        await asyncio.wait_for(task, 1)
    assert session.process is None
    assert session._monitor is None


@pytest.mark.asyncio
async def test_handoff_only_resets_a_session_holding_the_desktop(session, tmp_path):
    try:
        await session.connect()
        process = session.process
        assert not await session.handoff()
        assert session.process is process
        await session.call("js", {"code": "observe"}, "t", "c")
        assert await session.handoff()
        assert session.process is None
        assert session.lease.fd is None
        assert session.reset_reason
        await session.call("js", {"code": "fresh observe"}, "t", "next")
        entries = [json.loads(line) for line in (tmp_path / "calls.jsonl").read_text().splitlines()]
        calls = [e for e in entries if "args" in e]
        assert calls[0]["hostTurn"] == calls[1]["hostTurn"] == "t"
        assert calls[0]["turn"] != calls[1]["turn"]
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_timeout_discards_uncertain_session(session, monkeypatch):
    await session.connect()
    original = session._request

    async def request(kind, **values):
        if kind == "call":
            raise ToolError("CUA call timed out; action outcome may be unknown")
        return await original(kind, **values)

    monkeypatch.setattr(session, "_request", request)
    with pytest.raises(ToolError, match="timed out"):
        await session.call("js", {"code": "submit"}, "t", "c")
    assert session.process is None
    assert session.lease.fd is None


@pytest.mark.asyncio
async def test_oversized_cua_output_is_saved_without_partial_instructions(
    session, tmp_path, monkeypatch
):
    from deepseek_tui.cua.tools import MAX_CUA_TEXT_BYTES
    from deepseek_tui.tools import runtime

    monkeypatch.setattr(runtime, "_TEST_SPILLOVER_ROOT", tmp_path / "output")
    await session.connect()
    tool = CuaTool(session, session.descriptors[0])
    context = ToolContext(tmp_path, metadata={"cua_turn_id": "t", "cua_call_id": "large"})
    text = "界" * (MAX_CUA_TEXT_BYTES // 3 + 1)
    try:
        result = await tool.execute({"code": text}, context)
        assert not result.success
        assert "Do not replay" in result.content
        assert "界" not in result.content
        assert (tmp_path / "output/large.txt").read_text() == text
        assert len(result.content) < 1500
    finally:
        await session.close()


def test_original_image_detail_survives_and_is_adapted_per_provider(tmp_path, monkeypatch):
    import base64
    import io

    from PIL import Image

    from deepseek_tui.client.chat_messages import build_chat_messages
    from deepseek_tui.mcp.execute import mcp_response_to_tool_result
    from deepseek_tui.protocol.messages import Message

    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path))
    data = io.BytesIO()
    Image.new("RGB", (16, 16)).save(data, "PNG")
    result = mcp_response_to_tool_result(
        "cua_js",
        {
            "content": [
                {
                    "type": "image",
                    "data": base64.b64encode(data.getvalue()).decode(),
                    "_meta": {"codex/imageDetail": "original"},
                }
            ]
        },
    )
    image = result.images[0]
    assert image.detail == "original"
    message = Message.user("screen", images=[image])
    for supported, expected in [(False, "high"), (True, "original")]:
        wire = build_chat_messages([message], model="test", image_detail_original=supported)
        assert wire[0]["content"][1]["image_url"]["detail"] == expected
    assert image.detail == "original"


@pytest.mark.asyncio
async def test_text_only_route_hides_cua_before_connecting(installation, tmp_path, monkeypatch):
    from unittest.mock import AsyncMock

    from deepseek_tui.engine.handle import EngineHandle
    from deepseek_tui.engine.orchestrator import Engine

    connect = AsyncMock()
    monkeypatch.setattr(CuaSession, "connect", connect)
    engine = Engine(handle=EngineHandle(), client=AsyncMock(), tool_context=ToolContext(tmp_path))
    engine._app_config = Config(cua=installation)
    tools = await engine._get_tools_with_mcp()
    assert not any(t["function"]["name"].startswith("cua_") for t in tools)
    assert "vision" in engine._cua_prompt()
    connect.assert_not_awaited()


def test_vision_readiness_checks_helper_and_actual_route():
    from deepseek_tui.cua.readiness import vision_error

    assert vision_error(Config(), "deepseek-chat")
    assert vision_error(Config(vision={"model": "deepseek::deepseek-chat"}), "deepseek-chat")
    assert not vision_error(
        Config(vision={"model": "deepseek::deepseek-v4-flash-vision-exp"}), "deepseek-chat"
    )
    assert not vision_error(Config(), "deepseek-v4-flash-vision-exp")


@pytest.mark.asyncio
async def test_failed_connection_has_backoff(installation, tmp_path, monkeypatch):
    from unittest.mock import AsyncMock

    from deepseek_tui.engine.handle import EngineHandle
    from deepseek_tui.engine.orchestrator import Engine

    connect = AsyncMock(side_effect=ToolError("offline"))
    monkeypatch.setattr(CuaSession, "connect", connect)
    engine = Engine(handle=EngineHandle(), client=AsyncMock(), tool_context=ToolContext(tmp_path))
    engine._app_config = Config(
        cua=installation, vision={"model": "deepseek::deepseek-v4-flash-vision-exp"}
    )
    try:
        await engine._get_tools_with_mcp()
        await engine._get_tools_with_mcp()
        assert connect.await_count == 1
        engine._cua_retry_after = 0
        await engine._get_tools_with_mcp()
        assert connect.await_count == 2
    finally:
        await engine._close_cua()


@pytest.mark.asyncio
async def test_engine_stop_during_bootstrap_does_not_wait_for_timeout(
    installation, tmp_path, monkeypatch
):
    from unittest.mock import AsyncMock

    from deepseek_tui.engine.handle import EngineHandle
    from deepseek_tui.engine.orchestrator import Engine

    entered = asyncio.Event()

    async def connect(self):
        entered.set()
        await asyncio.Future()

    monkeypatch.setattr(CuaSession, "connect", connect)
    engine = Engine(handle=EngineHandle(), client=AsyncMock(), tool_context=ToolContext(tmp_path))
    engine._app_config = Config(cua=installation, vision={
        "model": "deepseek::deepseek-v4-flash-vision-exp"
    })
    task = asyncio.create_task(engine._get_tools_with_mcp())
    await entered.wait()
    await engine.handle.cancel()
    tools = await asyncio.wait_for(task, 1)
    assert not any(t["function"]["name"].startswith("cua_") for t in tools)
    assert engine._cua_session.process is None
    assert engine._cua_retry_after == 0


@pytest.mark.asyncio
async def test_text_only_child_does_not_connect(installation, tmp_path, monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from deepseek_tui.cua.subagent import prepare_subagent_cua
    from deepseek_tui.tools.registry import ToolRegistry

    connect = AsyncMock()
    monkeypatch.setattr(CuaSession, "connect", connect)
    context = ToolContext(tmp_path, metadata={"task_model": "deepseek-chat"})
    result = await prepare_subagent_cua(
        SimpleNamespace(id="child"), SimpleNamespace(config=Config(cua=installation)),
        context, ToolRegistry(), None, asyncio.Event(),
    )
    assert result is None
    assert "vision" in context.metadata["cua_error"]
    connect.assert_not_awaited()


def test_pruned_cua_history_explicitly_requires_documentation():
    from deepseek_tui.engine.capacity import ToolPruneConfig, prune_old_tool_results
    from deepseek_tui.protocol.messages import Message, ToolUseBlock

    messages = [
        Message.assistant_with_tools([ToolUseBlock(id="c", name="cua_js", input={})]),
        Message.tool_result("c", "runtime documentation\n" * 1000),
    ]
    assert prune_old_tool_results(
        messages,
        config=ToolPruneConfig(
            keep_last_n_turns=0, soft_trim_threshold=100, soft_trim_head=10, soft_trim_tail=10
        ),
    )
    assert "rewriteDocumentation" in messages[-1].text_content()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["interrupt", "endTurn", "close"])
async def test_control_timeout_is_not_paused_by_unresponsive_approval(session, monkeypatch, kind):
    from unittest.mock import AsyncMock

    monkeypatch.setattr(session, "_write", AsyncMock())
    approval = asyncio.create_task(asyncio.sleep(60))
    session.approvals[1] = approval
    try:
        with pytest.raises(ToolError, match="timed out"):
            await asyncio.wait_for(session._request(kind, timeout=0.05), 0.5)
    finally:
        approval.cancel()
        await asyncio.gather(approval, return_exceptions=True)
        session.approvals.clear()


@pytest.mark.asyncio
async def test_action_deadline_still_pauses_for_human_approval(session, monkeypatch):
    from unittest.mock import AsyncMock

    monkeypatch.setattr(session, "_write", AsyncMock())
    approval = asyncio.create_task(asyncio.sleep(60))
    session.approvals[1] = approval
    action = asyncio.create_task(session._request("call", timeout=0.05))
    try:
        await asyncio.sleep(0.15)
        assert not action.done()
        session.pending[session.sequence].set_result({"content": []})
        assert await asyncio.wait_for(action, 0.5) == {"content": []}
    finally:
        action.cancel()
        approval.cancel()
        await asyncio.gather(action, approval, return_exceptions=True)
        session.approvals.clear()


@pytest.mark.asyncio
async def test_engine_can_recover_after_idle_bridge_exit(installation, tmp_path):
    from unittest.mock import AsyncMock

    from deepseek_tui.engine.handle import EngineHandle
    from deepseek_tui.engine.orchestrator import Engine

    engine = Engine(handle=EngineHandle(), client=AsyncMock(), tool_context=ToolContext(tmp_path))
    engine._app_config = Config(
        cua=installation, vision={"model": "deepseek::deepseek-v4-flash-vision-exp"}
    )
    try:
        await engine._get_tools_with_mcp()
        session = engine._cua_session
        session.process.kill()
        await session.process.wait()
        await engine._get_tools_with_mcp()
        engine._cua_retry_after = 0
        tools = await engine._get_tools_with_mcp()
        assert any(t["function"]["name"] == "cua_js" for t in tools)
    finally:
        await engine._close_cua()


@pytest.mark.asyncio
async def test_missing_cua_does_not_abort_unrelated_child_work(tmp_path):
    from types import SimpleNamespace

    from deepseek_tui.cua.subagent import prepare_subagent_cua
    from deepseek_tui.tools.registry import ToolRegistry

    runtime = SimpleNamespace(
        manager=SimpleNamespace(parent_pause=None),
        config=Config(
            cua=CuaConfig(enabled=True, installation=tmp_path),
            vision={"model": "deepseek::deepseek-v4-flash-vision-exp"},
        ),
    )
    context = ToolContext(tmp_path)
    registry = ToolRegistry()
    result = await prepare_subagent_cua(
        SimpleNamespace(
            id="child",
            cancel_token=asyncio.Event(),
            interrupt_event=asyncio.Event(),
            parent_cancel=None,
        ),
        runtime,
        context,
        registry,
        None,
        asyncio.Event(),
    )
    assert result is None
    assert "LCU is not installed" in context.metadata["cua_error"]
    assert not registry.contains("cua_js")


@pytest.mark.asyncio
async def test_pending_approval_does_not_block_interrupt(session):
    entered = asyncio.Event()

    async def approve(params):
        entered.set()
        await asyncio.Future()

    session.on_approval = approve
    task = asyncio.create_task(session.call("js", {"code": "approve"}, "turn-a", "call-a"))
    try:
        await asyncio.wait_for(entered.wait(), 5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 5)
        assert session.lease.fd is None
        await asyncio.sleep(0)
        assert not session.approvals
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_actual_approval_response_and_error_preserved(session):
    async def approve(params):
        return {"action": "accept", "content": {}}

    session.on_approval = approve
    try:
        result = await session.call("js", {"code": "approve"}, "t", "c")
        assert not result["isError"]
        result = await session.call("js", {"code": "error"}, "t", "d")
        assert result["isError"]
        await session.end_turn()
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_desktop_lease_is_held_across_calls_and_wait_is_cancellable(tmp_path):
    a, b = DesktopLease(tmp_path / "lock"), DesktopLease(tmp_path / "lock")
    try:
        await a.acquire()
        waiting = asyncio.create_task(b.acquire())
        await asyncio.sleep(0.15)
        assert not waiting.done()
        waiting.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiting
        assert b.fd is None
        a.release()
        await asyncio.wait_for(b.acquire(), 1)
    finally:
        a.release()
        b.release()


@pytest.mark.asyncio
async def test_crash_never_replays_action(session, tmp_path):
    try:
        with pytest.raises(ToolError):
            await session.call("js", {"code": "crash"}, "t", "c")
        assert session.lease.fd is None
        entries = (tmp_path / "calls.jsonl").read_text().splitlines()
        assert len(entries) == 1
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_takeover_cancels_active_tool_and_discards_repl(session, tmp_path):
    await session.connect()
    stop = asyncio.Event()
    tool = CuaTool(session, session.descriptors[0], [stop])
    context = ToolContext(tmp_path, metadata={"cua_turn_id": "t", "cua_call_id": "c"})
    task = asyncio.create_task(tool.execute({"code": "hang"}, context))
    await asyncio.sleep(0.2)
    stop.set()
    with pytest.raises(ToolError, match="interrupted"):
        await asyncio.wait_for(task, 5)
    assert session.process is None
    assert session.lease.fd is None


@pytest.mark.asyncio
async def test_outer_task_cancellation_discards_repl(session, tmp_path):
    await session.connect()
    tool = CuaTool(session, session.descriptors[0])
    context = ToolContext(tmp_path, metadata={"cua_turn_id": "t", "cua_call_id": "c"})
    task = asyncio.create_task(tool.execute({"code": "hang"}, context))
    await asyncio.sleep(0.2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 5)
    assert session.process is None
    assert session.lease.fd is None


def test_runtime_documentation_is_not_truncated():
    from deepseek_tui.engine.context import compact_tool_result_for_context
    from deepseek_tui.tools.runtime import apply_spillover

    text = "Runtime guide\n" * 10000
    result = ToolResult(True, text, {"cua_runtime_content": True})
    assert apply_spillover(result, "c").content == text
    assert compact_tool_result_for_context("test", "cua_js", result) == text.strip()


def test_project_cannot_enable_executable_cua_config():
    from deepseek_tui.config.loader import _PROJECT_SENSITIVE_KEYS

    assert "cua" in _PROJECT_SENSITIVE_KEYS
    assert Config().cua.enabled is False


@pytest.mark.asyncio
async def test_engine_catalog_uses_upstream_schema_and_hides_host_tools(installation, tmp_path):
    from unittest.mock import AsyncMock

    from deepseek_tui.engine.handle import EngineHandle
    from deepseek_tui.engine.orchestrator import Engine

    engine = Engine(handle=EngineHandle(), client=AsyncMock(), tool_context=ToolContext(tmp_path))
    engine._app_config = Config(
        cua=installation, vision={"model": "deepseek::deepseek-v4-flash-vision-exp"}
    )
    try:
        tools = await engine._get_tools_with_mcp()
        definitions = {tool["function"]["name"]: tool["function"] for tool in tools}
        assert definitions["cua_js"]["description"] == "Original js"
        assert "code" in definitions["cua_js"]["parameters"]["properties"]
        assert "cua_turn_ended" not in definitions
        assert "Original fixture instructions" in engine._cua_prompt()
        engine.mode = "plan"
        tools = await engine._get_tools_with_mcp()
        assert not any(t["function"]["name"].startswith("cua_") for t in tools)
    finally:
        await engine._close_cua()


def test_cua_images_preserve_wire_bytes_and_coordinate_dimensions(tmp_path, monkeypatch):
    import base64
    import io

    from PIL import Image

    from deepseek_tui.media import image_data_url, import_image

    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path))
    buffer = io.BytesIO()
    Image.new("RGB", (2600, 1200), "white").save(buffer, "PNG")
    data = buffer.getvalue()
    image = import_image(data).model_copy(update={"source": {"kind": "cua"}})
    wire = image_data_url(image, max_side=100)
    assert base64.b64decode(wire.split(",", 1)[1]) == data
    assert image.width == 2600


def test_mcp_execute_can_be_imported_first():
    import os
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "-c", "from deepseek_tui.mcp.execute import mcp_response_to_tool_result"],
        env={**os.environ, "PYTHONPATH": str(Path(__file__).parents[1] / "src")},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.asyncio
async def test_child_runtime_approval_emits_card_and_keeps_once_scope(
    installation, tmp_path, native
):
    from contextlib import nullcontext
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, Mock

    from deepseek_tui.cua.subagent import prepare_subagent_cua
    from deepseek_tui.tools.approval import ApprovalDecision
    from deepseek_tui.tools.registry import ToolRegistry

    handler = SimpleNamespace(
        approval_scope=Mock(return_value=nullcontext()),
        request_approval=AsyncMock(return_value=ApprovalDecision.APPROVED_SESSION),
    )
    runtime = SimpleNamespace(
        config=Config(cua=installation, vision={"model": "deepseek::deepseek-v4-flash-vision-exp"}),
        approval_handler=handler,
        emit_event=AsyncMock(),
        manager=SimpleNamespace(parent_pause=None),
    )
    agent = SimpleNamespace(
        id="child",
        cancel_token=asyncio.Event(),
        interrupt_event=asyncio.Event(),
        parent_cancel=None,
    )
    context = ToolContext(tmp_path)
    session = await prepare_subagent_cua(
        agent, runtime, context, ToolRegistry(), None, asyncio.Event()
    )
    try:
        assert await session.on_approval(native) == {"action": "accept", "content": {}}
        event = runtime.emit_event.call_args.args[0]
        assert event.request.force_prompt is True
        assert event.tool_call_id == handler.request_approval.call_args.args[0]
    finally:
        await session.close()
