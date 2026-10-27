from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from deepseek_tui.config.models import Config, CuaConfig
from deepseek_tui.cua import session as cua_session
from deepseek_tui.cua.approval import approval_question, approval_response, auto_allow_response
from deepseek_tui.cua.session import CuaSession, DesktopLease
from deepseek_tui.cua.tools import CuaObserveTool, CuaTool
from deepseek_tui.tools.registry import ToolContext, ToolError, ToolResult

VISION = {"model": "deepseek::deepseek-v4-flash-vision-exp"}


@pytest.fixture(autouse=True)
def fresh_runtime_cache(tmp_path, monkeypatch):
    # Never contend with a real desktop session's lock.
    monkeypatch.setattr(cua_session, "LOCK_DIR", tmp_path)
    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    cua_session.reset_runtime_cache()
    yield
    cua_session.reset_runtime_cache()


def _engine(tmp_path, installation, **config):
    from unittest.mock import AsyncMock

    from deepseek_tui.engine.handle import EngineHandle
    from deepseek_tui.engine.orchestrator import Engine

    engine = Engine(handle=EngineHandle(), client=AsyncMock(), tool_context=ToolContext(tmp_path))
    engine._app_config = Config(cua=installation, **config)
    return engine


def _calls(tmp_path):
    lines = (tmp_path / "calls.jsonl").read_text().splitlines()
    return [entry for entry in map(json.loads, lines) if "args" in entry]


@pytest.mark.asyncio
async def test_shared_runtime_does_not_replace_another_engines_cua(installation, tmp_path):
    from types import SimpleNamespace
    from deepseek_tui.tools.registry import ToolRegistry

    shared = ToolRegistry()
    runtime = SimpleNamespace(registry=shared)
    first = _engine(tmp_path, installation, vision=VISION)
    second = _engine(tmp_path, installation, vision=VISION)
    for engine in (first, second):
        engine.tool_runtime = runtime
        engine.tool_registry = shared
    try:
        await first._prepare_cua()
        first_tool = first.tool_registry.get("cua_js")
        await second._prepare_cua()
        assert first.tool_registry.get("cua_js") is first_tool
        assert second.tool_registry.get("cua_js").session is second._cua_session
        assert not shared.contains("cua_js")
    finally:
        await first._close_cua()
        await second._close_cua()


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
    # An unpackaged (development) Workbench is Electron itself.
    native["_meta"]["tool_params"]["app"] = "com.github.Electron"
    assert approval_question(native) is None


def test_approval_copy_uses_one_language_and_preserves_scope(native):
    native["message"] = 'Allow Computer Use to use "汽水音乐 Helper"?'
    native["_meta"]["persist"] = ["session", "always"]
    zh = approval_question(native, "zh")
    en = approval_question(native, "en")
    assert zh["question"] == "允许操作「汽水音乐 Helper」吗？"
    assert en["question"] == 'Allow control of "汽水音乐 Helper"?'
    assert zh["allow_custom"] is False
    assert [o["value"] for o in en["options"]] == ["decline", "once", "session", "always"]
    assert en["options"][0]["label"] == "Deny"
    assert approval_response(native, {"answers": [{"id": "cua_permission", "label": "Always allow"}]}) == {
        "action": "accept", "content": {}, "_meta": {"persist": "always"}
    }
    assert zh["options"][0]["description"] == ""
    native["message"] = "Custom access request with important scope details"
    assert approval_question(native)["question"] == native["message"]


def test_auto_allow_accepts_native_apps_only(native):
    assert auto_allow_response(native) == {
        "action": "accept", "content": {}, "_meta": {"persist": "session"}
    }
    native["_meta"]["persist"] = []
    assert auto_allow_response(native) == {"action": "accept", "content": {}}
    native["_meta"]["tool_params"]["app"] = "com.xingyuzhong.deepseekgui"
    assert auto_allow_response(native) is None
    native["_meta"] = {"tool_name": "access_browser_origin", "origin": "https://example.com"}
    assert auto_allow_response(native) is None


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
        with pytest.raises(ToolError, match="cua_observe"):
            await tool.execute({"code": "oldApp.click()"}, context)
        entries = [json.loads(line) for line in (tmp_path / "calls.jsonl").read_text().splitlines()]
        assert len([entry for entry in entries if "args" in entry]) == 1
        assert any(entry.get("end", {}).get("event") == "Interrupt" for entry in entries)
        result = await CuaObserveTool(session, [pause]).execute({"app": "dev.fixture"}, context)
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
        await session.call("observe", {"app": "dev.fixture"}, "t", "next")
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
    await engine._prepare_cua()
    tools = await engine._get_tools_with_mcp()
    assert not any(t["function"]["name"].startswith("cua_") for t in tools)
    assert "vision" in engine._cua_prompt()
    connect.assert_not_awaited()


@pytest.mark.asyncio
async def test_polled_context_estimate_never_starts_or_waits_for_cua(
    installation, tmp_path, monkeypatch
):
    from unittest.mock import AsyncMock

    connect = AsyncMock()
    monkeypatch.setattr(CuaSession, "connect", connect)
    engine = _engine(tmp_path, installation, vision=VISION)
    # A CUA call holding the session (e.g. waiting for a human) must not stall the estimate.
    engine._cua_session = CuaSession(installation, tmp_path, "busy")
    await engine._cua_session._operation_lock.acquire()
    try:
        tools = await asyncio.wait_for(engine._get_tools_with_mcp(), 1)
        await asyncio.wait_for(engine.context_breakdown_live(), 1)
    finally:
        engine._cua_session._operation_lock.release()
    assert not any(t["function"]["name"].startswith("cua_") for t in tools)
    connect.assert_not_awaited()


def test_prompt_surfaces_follow_cua_readiness_without_connecting(installation, tmp_path):
    from unittest.mock import AsyncMock

    from deepseek_tui.engine.handle import EngineHandle
    from deepseek_tui.engine.orchestrator import Engine

    engine = Engine(handle=EngineHandle(), client=AsyncMock(), tool_context=ToolContext(tmp_path))
    engine._app_config = Config(cua=installation)
    engine.default_model = "deepseek-v4-pro"
    assert engine._cua_surfaces() == frozenset()  # text-only route, no helper
    engine.default_model = "deepseek-flash"
    assert engine._cua_surfaces() == {"desktop"}
    engine._app_config = Config(cua=installation.model_copy(update={"chrome": True}))
    assert engine._cua_surfaces() == {"desktop", "chrome"}
    engine.mode = "plan"
    assert engine._cua_surfaces() == frozenset()


def test_vision_readiness_checks_helper_and_actual_route():
    from deepseek_tui.cua.readiness import vision_error

    assert vision_error(Config(), "deepseek-chat")
    assert vision_error(Config(vision={"model": "deepseek::deepseek-chat"}), "deepseek-chat")
    assert not vision_error(
        Config(vision={"model": "deepseek::deepseek-v4-flash-vision-exp"}), "deepseek-chat"
    )
    assert not vision_error(Config(), "deepseek-v4-flash-vision-exp")


@pytest.mark.asyncio
async def test_failed_connection_backoff_is_shared_by_conversations_and_children(
    installation, tmp_path, monkeypatch
):
    from types import SimpleNamespace

    from deepseek_tui.cua.subagent import prepare_subagent_cua
    from deepseek_tui.tools.registry import ToolRegistry

    attempts = []

    def offline(installation):
        attempts.append(installation)
        raise ToolError("offline")

    monkeypatch.setattr(CuaSession, "_paths", staticmethod(offline))
    first = _engine(tmp_path, installation, vision=VISION)
    second = _engine(tmp_path, installation, vision=VISION)
    try:
        await first._prepare_cua()
        await second._prepare_cua()
        context = ToolContext(tmp_path)
        child = await prepare_subagent_cua(
            SimpleNamespace(id="child", cancel_token=asyncio.Event(),
                            interrupt_event=asyncio.Event(), parent_cancel=None),
            SimpleNamespace(config=first._app_config, manager=SimpleNamespace(parent_pause=None)),
            context, ToolRegistry(), None, asyncio.Event(),
        )
        assert child is None
        assert len(attempts) == 1
        assert "offline" in second._cua_error and "retries in" in second._cua_error
        assert "retries in" in context.metadata["cua_error"]
        assert not second.tool_registry.contains("cua_js")
        cua_session._RUNTIMES[cua_session._runtime_key(installation)]["retry_after"] = 0
        await second._prepare_cua()
        assert len(attempts) == 2
    finally:
        await first._close_cua()
        await second._close_cua()


@pytest.mark.asyncio
async def test_lazy_connection_failure_drops_stale_catalog(installation, tmp_path, monkeypatch):
    first = _engine(tmp_path, installation, vision=VISION)
    await first._prepare_cua()
    await first._close_cua()

    def missing(installation):
        raise ToolError("LCU is not installed")

    monkeypatch.setattr(CuaSession, "_paths", staticmethod(missing))
    second = _engine(tmp_path, installation, vision=VISION)
    await second._prepare_cua()
    tool = second.tool_registry.get("cua_js")
    context = ToolContext(tmp_path, metadata={"cua_turn_id": "t", "cua_call_id": "c"})
    with pytest.raises(ToolError, match="not installed"):
        await tool.execute({"code": "observe"}, context)
    # The next turn reports the runtime as unavailable instead of offering stale tools.
    third = _engine(tmp_path, installation, vision=VISION)
    await third._prepare_cua()
    assert not third.tool_registry.contains("cua_js")
    assert "not installed" in third._cua_prompt()


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
    task = asyncio.create_task(engine._prepare_cua())
    await entered.wait()
    await engine.handle.cancel()
    await asyncio.wait_for(task, 1)
    tools = await engine._get_tools_with_mcp()
    assert not any(t["function"]["name"].startswith("cua_") for t in tools)
    assert engine._cua_session.process is None
    # A stop is not a runtime failure and must not start the retry window.
    runtime = cua_session._RUNTIMES.get(cua_session._runtime_key(installation), {})
    assert "retry_after" not in runtime


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


def test_pruning_other_tool_output_does_not_request_cua_documentation():
    from deepseek_tui.engine.capacity import ToolPruneConfig, prune_old_tool_results
    from deepseek_tui.protocol.messages import Message, ToolUseBlock

    messages = [
        Message.assistant_with_tools([ToolUseBlock(id="r", name="read_file", input={})]),
        Message.tool_result("r", "file body\n" * 1000),
        Message.assistant_with_tools([ToolUseBlock(id="c", name="cua_js", input={})]),
        Message.tool_result("c", "short observation"),
    ]
    assert prune_old_tool_results(
        messages,
        config=ToolPruneConfig(
            keep_last_n_turns=0, soft_trim_threshold=100, soft_trim_head=10, soft_trim_tail=10
        ),
    )
    assert len(messages) == 4
    assert not any("rewriteDocumentation" in m.text_content() for m in messages)


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
@pytest.mark.parametrize("used", [False, True])
async def test_engine_recovers_after_idle_bridge_exit(installation, tmp_path, used):
    engine = _engine(tmp_path, installation, vision=VISION)
    context = ToolContext(tmp_path, metadata={"cua_turn_id": "t", "cua_call_id": "c"})
    try:
        await engine._prepare_cua()
        tool = engine.tool_registry.get("cua_js")
        session = engine._cua_session
        if used:
            await tool.execute({"code": "observe"}, context)
            await session.end_turn()
        session.process.kill()
        await session.process.wait()
        await engine._prepare_cua()
        assert engine.tool_registry.contains("cua_js")
        if used:
            # Old bindings remain unusable until a fresh observation.
            with pytest.raises(ToolError, match="between calls"):
                await tool.execute({"code": "oldApp.click()"}, context)
            await CuaObserveTool(session).execute({"app": "dev.fixture"}, context)
        result = await tool.execute({"code": "fresh"}, context)
        assert result.success
        codes = [call["args"]["code"] for call in _calls(tmp_path)]
        assert codes[-1] == "fresh" and "oldApp.click()" not in codes
        assert len(codes) == (4 if used else 1)
    finally:
        await engine._close_cua()


@pytest.mark.asyncio
async def test_later_conversations_and_children_reuse_catalog_without_starting_lcu(
    installation, tmp_path
):
    from types import SimpleNamespace

    from deepseek_tui.cua.subagent import prepare_subagent_cua
    from deepseek_tui.tools.registry import ToolRegistry

    first = _engine(tmp_path, installation, vision=VISION)
    second = _engine(tmp_path, installation, vision=VISION)
    registry = ToolRegistry()
    child = None
    try:
        await first._prepare_cua()
        assert first._cua_session.process is not None
        await second._prepare_cua()
        assert second._cua_session.process is None
        assert second.tool_registry.get("cua_js").input_schema() == (
            first.tool_registry.get("cua_js").input_schema()
        )
        assert "Original fixture instructions" in second._cua_prompt()
        context = ToolContext(tmp_path)
        child = await prepare_subagent_cua(
            SimpleNamespace(id="child", cancel_token=asyncio.Event(),
                            interrupt_event=asyncio.Event(), parent_cancel=None),
            SimpleNamespace(config=first._app_config, manager=SimpleNamespace(parent_pause=None)),
            context, registry, None, asyncio.Event(),
        )
        assert child is not None and child.process is None
        assert registry.contains("cua_js")
        # The first real call connects lazily and runs once.
        call = ToolContext(tmp_path, metadata={"cua_turn_id": "t2", "cua_call_id": "c2"})
        result = await second.tool_registry.get("cua_js").execute({"code": "lazy"}, call)
        assert result.success and second._cua_session.process is not None
        assert [entry["args"]["code"] for entry in _calls(tmp_path)] == ["lazy"]
    finally:
        await first._close_cua()
        await second._close_cua()
        if child is not None:
            await child.close()


@pytest.mark.asyncio
async def test_changed_runtime_instructions_reach_the_model_after_lazy_connect(
    installation, tmp_path
):
    key = cua_session._runtime_key(installation)
    probe = CuaSession(installation, tmp_path, "probe")
    await probe.connect()
    await probe.close()
    instructions, tools = cua_session._RUNTIMES[key]["catalog"]
    cua_session._RUNTIMES[key]["catalog"] = ("Stale instructions", tools)
    session = CuaSession(installation, tmp_path, "s")
    session.lease = DesktopLease(tmp_path / "desktop.lock")
    try:
        assert session.use_cached_catalog() and session.instructions == "Stale instructions"
        result = await session.call("js", {"code": "hello"}, "t", "c")
        assert result["content"][-1]["text"] == instructions
        assert cua_session._RUNTIMES[key]["catalog"][0] == instructions
    finally:
        await session.close()


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
async def test_busy_desktop_times_out_clearly_without_dropping_the_connection(
    installation, tmp_path, monkeypatch
):
    monkeypatch.setattr(cua_session, "LEASE_WAIT_SECONDS", 0.2)
    holder = CuaSession(installation, tmp_path, "holder")
    waiter = CuaSession(installation, tmp_path, "waiter")
    try:
        await holder.call("js", {"code": "holder"}, "turn-a", "a")
        with pytest.raises(ToolError, match="in use by another computer-use task"):
            await asyncio.wait_for(waiter.call("js", {"code": "blocked"}, "turn-b", "b"), 2)
        assert waiter.process is not None and waiter.turn_id is None
        assert not waiter.reset_reason
        await holder.end_turn()
        await waiter.call("js", {"code": "after"}, "turn-b", "c")
        assert [entry["args"]["code"] for entry in _calls(tmp_path)] == ["holder", "after"]
    finally:
        await holder.close()
        await waiter.close()


@pytest.mark.asyncio
async def test_reset_notice_only_follows_code_that_ran(session, tmp_path):
    stop = asyncio.Event()
    await session.run(session.connect, [stop])
    monitor = session._monitor
    stop.set()
    await asyncio.wait_for(monitor, 2)
    assert session.process is None
    # Nothing ran in the discarded REPL, so the first call is not refused.
    assert session.reset_reason == ""
    stop.clear()
    tool = CuaTool(session, session.descriptors[0], [stop])
    context = ToolContext(tmp_path, metadata={"cua_turn_id": "t", "cua_call_id": "c"})
    try:
        assert (await tool.execute({"code": "first"}, context)).success
    finally:
        await session.close()


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
        await engine._prepare_cua()
        tools = await engine._get_tools_with_mcp()
        definitions = {tool["function"]["name"]: tool["function"] for tool in tools}
        assert definitions["cua_js"]["description"] == "Original js"
        assert "code" in definitions["cua_js"]["parameters"]["properties"]
        assert "cua_turn_ended" not in definitions
        assert "Original fixture instructions" in engine._cua_prompt()
        engine.mode = "plan"
        await engine._prepare_cua()
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


@pytest.mark.parametrize("size", [(1400, 1000), (3840, 2160)])
def test_oversized_cua_screenshot_fits_provider_limit_at_the_same_pixel_size(
    tmp_path, monkeypatch, size
):
    import base64
    import io
    import os

    from PIL import Image

    from deepseek_tui.media import CUA_RAW_IMAGE_BYTES, image_data_url, import_image

    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path))
    buffer = io.BytesIO()
    Image.frombytes("RGB", size, os.urandom(size[0] * size[1] * 3)).save(buffer, "PNG")
    assert len(buffer.getvalue()) > CUA_RAW_IMAGE_BYTES
    image = import_image(buffer.getvalue()).model_copy(update={"source": {"kind": "cua"}})
    wire = base64.b64decode(image_data_url(image, max_side=100).split(",", 1)[1])
    assert len(wire) <= CUA_RAW_IMAGE_BYTES
    with Image.open(io.BytesIO(wire)) as encoded:
        assert encoded.size == size


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


@pytest.mark.asyncio
async def test_desktop_assistance_releases_desktop_and_requires_fresh_observation(
    installation, tmp_path
):
    from unittest.mock import AsyncMock

    from deepseek_tui.engine.handle import EngineHandle
    from deepseek_tui.engine.orchestrator import Engine

    engine = Engine(handle=EngineHandle(), client=AsyncMock(), tool_context=ToolContext(tmp_path))
    engine._app_config = Config()
    action = {"kind": "action", "surface": "desktop", "reason": "请在弹窗里输入验证码"}
    with pytest.raises(ToolError, match="unavailable"):
        await engine._await_user_input("ask", action)

    engine._app_config = Config(cua=installation)
    engine.default_model = "deepseek-flash"
    session = CuaSession(installation, tmp_path, "manual-step")
    engine._cua_session = session
    task = asyncio.create_task(engine._await_user_input("ask", action))
    for _ in range(50):
        if "ask" in engine.handle.pending_user_inputs:
            break
        await asyncio.sleep(0.01)
    assert session.human_reserved
    assert session.lease.fd is not None
    other = DesktopLease()
    with pytest.raises(ToolError, match="desktop is in use"):
        await other.acquire(timeout=0.01)
    engine.handle.pending_user_inputs["ask"].set_result(
        {"answers": [{"question_id": "desktop_action", "label": "我已完成"}]}
    )
    result = await asyncio.wait_for(task, 1)
    payload = json.loads(result.content)
    assert not session.human_reserved and session.lease.fd is None
    assert result.success and payload["choice"] == "done"
    assert "observe" in payload["instructions"] and "not a verified" in payload["instructions"]


def test_desktop_assistance_answers_map_to_choices():
    from deepseek_tui.cua.tools import desktop_action_question, desktop_action_result

    question = desktop_action_question("Approve the dialog", "en")
    assert [o["label"] for o in question["options"]] == ["Done", "Skip this step"]
    assert desktop_action_result(question, {"answers": [{"value": "Skip this step"}]})[
        "choice"
    ] == "skip"
    typed = desktop_action_result(question, {"answers": {"desktop_action": "code is on my phone"}})
    assert typed["choice"] == "information" and typed["user_text"] == "code is on my phone"
    assert desktop_action_result(question, {"cancelled": True})["choice"] == "dismissed"


@pytest.mark.asyncio
async def test_auto_allow_skips_the_card_even_unattended(installation, native, tmp_path):
    from unittest.mock import AsyncMock

    from deepseek_tui.engine.handle import EngineHandle
    from deepseek_tui.engine.orchestrator import Engine

    engine = Engine(handle=EngineHandle(), client=AsyncMock(), tool_context=ToolContext(tmp_path))
    installation.auto_allow_apps = True
    engine._app_config = Config(cua=installation)
    engine.default_model = "deepseek-flash"
    engine.tool_context.metadata["unattended"] = True
    try:
        await engine._prepare_cua()
        assert await asyncio.wait_for(engine._cua_session.on_approval(native), 1) == {
            "action": "accept", "content": {}, "_meta": {"persist": "session"}
        }
        assert not engine.handle.pending_user_inputs
        assert "unattended" in engine._cua_prompt()
        assert "browser-site grants" in engine._cua_prompt()
        assert "stop and report" in engine._cua_prompt()
        origin = {**native, "_meta": {"origin": "https://example.com",
                                      "tool_name": "access_browser_origin"}}
        assert await engine._cua_session.on_approval(origin) == {"action": "cancel"}
    finally:
        await engine._close_cua()


@pytest.mark.asyncio
async def test_unattended_runs_decline_app_access_instead_of_waiting(
    installation, native, tmp_path
):
    from unittest.mock import AsyncMock

    from deepseek_tui.engine.handle import EngineHandle
    from deepseek_tui.engine.orchestrator import Engine

    engine = Engine(handle=EngineHandle(), client=AsyncMock(), tool_context=ToolContext(tmp_path))
    engine._app_config = Config(cua=installation)
    engine.default_model = "deepseek-flash"
    engine.tool_context.metadata["unattended"] = True
    cua_session.reset_runtime_cache()
    try:
        await engine._prepare_cua()
        assert await asyncio.wait_for(engine._cua_session.on_approval(native), 1) == {
            "action": "cancel"
        }
        assert not engine.handle.pending_user_inputs
        assert "unattended" in engine._cua_prompt()
        with pytest.raises(ToolError, match="Nobody is watching"):
            await engine._await_user_input(
                "ask", {"kind": "action", "surface": "desktop", "reason": "approve"}
            )
    finally:
        await engine._close_cua()
        cua_session.reset_runtime_cache()


@pytest.mark.asyncio
async def test_missing_api_error_points_back_to_the_documentation(session, tmp_path):
    await session.connect()
    tool = CuaTool(session, session.descriptors[0])
    context = ToolContext(tmp_path, metadata={"cua_turn_id": "t", "cua_call_id": "c"})
    try:
        result = await tool.execute({"code": "throw:app.screenshot is not a function"}, context)
        assert not result.success
        assert result.content.startswith("app.screenshot is not a function")
        assert "rewriteDocumentation" in result.content
        await CuaObserveTool(session).execute({"app": "dev.fixture"}, context)
        other = await tool.execute({"code": "throw:Accessibility error"}, context)
        assert "rewriteDocumentation" not in other.content
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_call_after_the_user_raised_the_app_needs_observation(session, tmp_path):
    await session.connect()
    tool = CuaTool(session, session.descriptors[0])
    context = ToolContext(tmp_path, metadata={"cua_turn_id": "t", "cua_call_id": "c"})
    try:
        session.outside_change = "The user brought the app to the front."
        with pytest.raises(ToolError, match="Not executed.*front.*cua_observe"):
            await tool.execute({"code": "await app.click([1, 2]);"}, context)
        await CuaObserveTool(session).execute({"app": "dev.fixture"}, context)
        assert (await tool.execute({"code": "ok"}, context)).content == "ok"
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_results_flag_truncated_trees_and_unverified_coordinate_clicks(session, tmp_path):
    await session.connect()
    tool = CuaTool(session, session.descriptors[0])
    context = ToolContext(tmp_path, metadata={"cua_turn_id": "t", "cua_call_id": "c"})
    try:
        code = "await app.click([114, 501]);\n2 HTML (showing 0-100 of 350 items)"
        result = await tool.execute({"code": code}, context)
        assert result.content.startswith(code)
        assert "truncated" in result.content and "not evidence" in result.content
        # The runtime recorded no click, so code text alone is not a coordinate click.
        assert "coordinate click" not in result.content
        clicked = await tool.execute(
            {"code": 'actions:[{"action":"click","coordinate":true,"ok":true}]'}, context)
        assert "coordinate click" in clicked.content
        indexed = await tool.execute(
            {"code": 'actions:[{"action":"click","coordinate":false,"ok":true}]'}, context)
        assert "coordinate click" not in indexed.content
        complete = "await app.click(75);\n2 HTML (showing 0-40 of 40 items)"
        assert (await tool.execute({"code": complete}, context)).content == complete
        # Without a record from the runtime, the code is read instead.
        await tool.execute({"code": "untraced"}, context)
        fallback = await tool.execute({"code": "await app.click([114, 501]);"}, context)
        assert "coordinate click" in fallback.content
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_runtime_failures_are_named_without_argument_hints(session, tmp_path):
    await session.connect()
    tool = CuaTool(session, session.descriptors[0])
    context = ToolContext(tmp_path, metadata={"cua_turn_id": "t", "cua_call_id": "c"})
    try:
        missing = await tool.execute({"code": "throw:Invalid app: com.example.none"}, context)
        assert not missing.success and missing.metadata["cua_error_kind"] == "unknown_app"
        assert "cua.listApps()" in missing.content
        assert "Do not guess parameter names" not in missing.content
        # No input reached the UI, so the model may continue without a forced observation.
        assert not session.outside_change
        assert (await tool.execute({"code": "listApps"}, context)).success
        stale = await tool.execute(
            {"code": 'actions:[{"action":"click","coordinate":false,"ok":false}]'}, context)
        assert stale.metadata["cua_error_kind"] == "stale_element"
        # The runtime rejected the only input before sending it.
        assert not session.outside_change
        acted = await tool.execute({"code": 'actions:[{"action":"pressKey","ok":true},'
                                            '{"action":"click","coordinate":false,"ok":false}]'},
                                   context)
        assert acted.metadata["cua_error_kind"] == "stale_element"
        # An earlier input was dispatched: its effect is unknown until observed.
        assert session.outside_change
        with pytest.raises(ToolError, match="cua_observe"):
            await tool.execute({"code": "listApps"}, context)
        assert (await CuaObserveTool(session).execute({"app": "dev.fixture"}, context)).success
        stopped = await tool.execute({"code": "throw:Computer Use server error -10016: x"}, context)
        assert stopped.metadata["cua_error_kind"] == "user_intervened"
        assert "user operated the app" in session.outside_change
        await CuaObserveTool(session).execute({"app": "dev.fixture"}, context)
        await tool.execute({"code": "untraced"}, context)
        unknown = await tool.execute({"code": "throw:boom"}, context)
        assert "cua_error_kind" not in unknown.metadata
        # Without a record, any failure still requires an observation.
        assert session.outside_change
    finally:
        await session.close()


def test_runtime_error_names_cover_observed_messages():
    from deepseek_tui.cua.tools import runtime_error

    key = runtime_error('Computer Use server error -10005: keyNotFound("down")')
    assert key[0] == "invalid_key"
    assert runtime_error("Computer Use server error -10005: 99999 is an invalid element ID")[0] \
        == "stale_element"
    assert runtime_error("Invalid app: 文本编辑")[0] == "unknown_app"
    assert runtime_error("Typing into a specific element is only supported on Linux.")[0] \
        == "unsupported_form"
    assert runtime_error("Computer Use server error -10020: locked")[0] == "screen_locked"
    assert runtime_error("TypeError: Cannot read properties of undefined") is None


def test_expected_text_ignores_presentation_not_content():
    from deepseek_tui.cua.tools import text_observed

    page = "订单号：A-1024\nTotal  price: $42\nHe said “ship it”\n状态：已发货"
    for fragment in ["订单号: A-1024", "total price: $42", 'He said "ship it"', "状态:已发货"]:
        assert text_observed(page, fragment), fragment
    for fragment in ["订单号：A-9999", "已取消", "Total price: $43", "He said “stop it”",
                     "Totalprice"]:
        assert not text_observed(page, fragment), fragment


@pytest.mark.asyncio
async def test_runtime_surface_names_the_touched_app_for_the_preview(session, tmp_path):
    await session.connect()
    tool = CuaTool(session, session.descriptors[0])
    context = ToolContext(tmp_path, metadata={"cua_turn_id": "t", "cua_call_id": "c"})
    try:
        app = await tool.execute({"code": "surface:com.apple.TextEdit"}, context)
        assert app.metadata["cua_surface"] == {"kind": "app", "app_id": "com.apple.TextEdit"}
        browser = await tool.execute({"code": "surface:browser"}, context)
        assert browser.metadata["cua_surface"] == {"kind": "browser"}
        plain = await tool.execute({"code": "listApps"}, context)
        assert "cua_surface" not in plain.metadata
    finally:
        await session.close()


GUIDE = "## Computer Use\n" + "Use cua.getApp(id) and observe before acting.\n" * 200


def _cua_exchange(call_id, code, result):
    from deepseek_tui.protocol.messages import Message, Role, ToolUseBlock

    use = Message(role=Role.ASSISTANT, content=[
        ToolUseBlock(id=call_id, name="cua_js", input={"code": code})])
    return [use, Message.tool_result(call_id, result)]


def test_reconnect_guide_is_collapsed_while_the_earlier_copy_is_in_context():
    from deepseek_tui.cua.tools import collapse_repeated_texts

    messages = [*_cua_exchange("first", "await cua.getState()", GUIDE + "\nApps: Notes"),
                *_cua_exchange("again", "await cua.getApp('notes')", GUIDE + "\nWindow: Notes")]
    collapse_repeated_texts(messages, 2, [GUIDE])
    latest = messages[-1].content[0].content
    assert GUIDE not in latest and latest.endswith("\nWindow: Notes")
    assert "first" in latest  # names where the full text is
    assert GUIDE in messages[1].content[0].content


def test_guide_is_kept_whole_when_the_earlier_copy_is_gone_or_requested():
    from deepseek_tui.cua.tools import collapse_repeated_texts

    pruned = [*_cua_exchange("first", "await cua.getState()", "[pruned]"),
              *_cua_exchange("again", "await cua.getApp('notes')", GUIDE)]
    collapse_repeated_texts(pruned, 2, [GUIDE])
    assert pruned[-1].content[0].content == GUIDE
    asked = [*_cua_exchange("first", "await cua.getState()", GUIDE),
             *_cua_exchange("docs", "await cua.rewriteDocumentation()", GUIDE)]
    collapse_repeated_texts(asked, 2, [GUIDE])
    assert asked[-1].content[0].content == GUIDE


@pytest.mark.asyncio
async def test_large_runtime_text_blocks_are_remembered(session, tmp_path):
    await session.connect()
    tool = CuaTool(session, session.descriptors[0])
    context = ToolContext(tmp_path, metadata={"cua_turn_id": "t", "cua_call_id": "c"})
    try:
        await tool.execute({"code": GUIDE}, context)
        await tool.execute({"code": "small"}, context)
        assert session.large_texts == [GUIDE]
    finally:
        await session.close()


@pytest.mark.parametrize("failure", ["crash", "error"])
async def test_uncertain_cua_requires_new_evidence_even_after_reset(session, tmp_path, failure):
    from deepseek_tui.tools.task_delivery import FinishTaskTool, TaskDelivery

    await session.connect()
    delivery = TaskDelivery(active=True, evidence={"tool:before"})
    context = ToolContext(tmp_path, metadata={
        "cua_turn_id": "t", "cua_call_id": "failed", "task_delivery": delivery,
    })
    tool = CuaTool(session, session.descriptors[0])
    args = dict(status="completed", answer="Saved", evidence=["tool:before"], remaining=[])
    try:
        try:
            result = await tool.execute({"code": failure}, context)
            assert not result.success
        except ToolError:
            assert failure == "crash"
        with pytest.raises(ToolError, match="observation"):
            await FinishTaskTool().execute(args, context)
        session.reset_reason = ""
        reset = CuaTool(session, session.descriptors[1])
        reset_result = await reset.execute({}, context)
        assert reset_result.metadata.get("task_evidence") is False
        with pytest.raises(ToolError, match="observation"):
            await FinishTaskTool().execute(args, context)
        delivery.evidence.add("tool:verified-file")
        with pytest.raises(ToolError, match="observation"):
            await FinishTaskTool().execute({**args, "evidence": ["tool:verified-file"]}, context)
        if session.unresolved:
            await session.acknowledge(session.unresolved["call_id"])
        result = await CuaObserveTool(session).execute({"app": "dev.fixture"}, context)
        delivery.remember_evidence("tool:observed", result.metadata)
        result = await FinishTaskTool().execute({**args, "evidence": ["tool:observed"],
            "verification": [{"claim": "Saved", "evidence": ["tool:observed"], "limitations": []}]}, context)
        assert result.success
    finally:
        await session.close()


async def test_runtime_cancel_closes_permission_event(installation, tmp_path):
    from deepseek_tui.engine.events import UserInputRequiredEvent, UserInputResolvedEvent

    engine = _engine(tmp_path, installation)
    events = []
    async def emit(event):
        events.append(event)
    engine.handle.emit = emit
    task = asyncio.create_task(engine._await_user_input_raw(
        "permission", [], purpose="cua_permission"
    ))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert [type(event) for event in events] == [UserInputRequiredEvent, UserInputResolvedEvent]
    assert events[-1].response is None
    assert not engine.handle.pending_user_inputs


async def test_information_handoff_drops_repl_and_tells_model(installation, tmp_path):
    from unittest.mock import AsyncMock

    engine = _engine(tmp_path, installation)
    session = SimpleNamespace(end_turn=AsyncMock(), close=AsyncMock(), reset_reason="old")
    engine._cua_session = session
    task = asyncio.create_task(engine._await_user_input("ask", {
        "questions": [{"id": "next", "header": "Next", "question": "Which document?"}],
    }))
    await asyncio.sleep(0)
    engine.handle.pending_user_inputs["ask"].set_result({"answers": []})
    result = await task
    session.close.assert_awaited_once()
    assert "CUA session reset" in result.content
    assert session.reset_reason == "old"


def test_subagent_cua_step_reports_its_app_to_the_parent_ui():
    from deepseek_tui.server.threads.manager import _mailbox_message_payload
    from deepseek_tui.tools.subagent.mailbox import MailboxMessage

    surface = {"kind": "app", "app_id": "com.apple.Notes"}
    payload = _mailbox_message_payload(MailboxMessage.tool_call_completed(
        "child", "cua_js", 2, True, tool_call_id="call-9", cua_surface=surface))
    assert payload["cua_surface"] == surface
    plain = _mailbox_message_payload(MailboxMessage.tool_call_completed("child", "read_file", 3, True))
    assert plain["cua_surface"] is None

@pytest.mark.asyncio
async def test_human_reservation_survives_connection_close(installation, tmp_path):
    session = CuaSession(installation, tmp_path, 'human-owner')
    other = DesktopLease()
    try:
        await session.reserve_human()
        await session.close()
        assert session.control_state()['owner'] == 'user'
        with pytest.raises(ToolError, match='desktop is in use'):
            await other.acquire(timeout=0.01)
        session.release_human()
        await other.acquire(timeout=0.1)
    finally:
        session.release_human()
        other.release()
        await session.close()

@pytest.mark.asyncio
async def test_unknown_receipt_survives_reset_and_requires_matching_ack(installation, tmp_path):
    session = CuaSession(installation, tmp_path, 'receipt-owner')
    await session.record_outcome('turn', 'call', 'unknown')
    await session.close()
    restored = CuaSession(installation, tmp_path, 'receipt-owner')
    assert restored.control_state()['unresolved']['call_id'] == 'call'
    with pytest.raises(ToolError, match='changed'):
        await restored.acknowledge('old-call')
    await restored.acknowledge('call')
    assert restored.control_state()['unresolved'] is None


@pytest.mark.asyncio
async def test_receipt_write_failure_still_closes_native_session(session, monkeypatch):
    await session.connect()
    original_request = session._request
    original_record = session.record_outcome

    async def request(kind, **values):
        if kind == "call":
            raise ToolError("connection lost")
        return await original_request(kind, **values)

    async def record(turn_id, call_id, outcome):
        await original_record(turn_id, call_id, outcome)
        if outcome == "unknown":
            raise OSError("receipt storage unavailable")

    monkeypatch.setattr(session, "_request", request)
    monkeypatch.setattr(session, "record_outcome", record)
    with pytest.raises(OSError, match="storage unavailable"):
        await session.call("js", {"code": "submit"}, "turn", "call")
    assert session.unresolved["call_id"] == "call"
    assert session.process is None and session.lease.fd is None


def test_finalization_keeps_the_observation_completion_requires():
    from deepseek_tui.tools.task_delivery import TaskDelivery

    catalog = [{"name": n} for n in ("finish_task", "cua_observe", "cua_js", "read_file")]
    plain = TaskDelivery(active=True, stop_reminded=True)
    assert [t["name"] for t in plain.tools(catalog)] == ["finish_task"]
    assert not plain.allows("cua_observe")
    used = TaskDelivery(active=True, stop_reminded=True, cua_used=True)
    assert [t["name"] for t in used.tools(catalog)] == ["finish_task", "cua_observe"]
    assert used.allows("cua_observe") and not used.allows("cua_js")
    # One round to observe, one to finish; without computer use a single round remains.
    plain.finalization_rounds = used.finalization_rounds = 1
    assert plain.finalization_exhausted() and not used.finalization_exhausted()
    used.finalization_rounds = 2
    assert used.finalization_exhausted()
