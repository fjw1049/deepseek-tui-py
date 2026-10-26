"""Recovery and completion use observations, never arbitrary REPL output."""

from dataclasses import replace

import pytest

from deepseek_tui.cua.tools import CuaObserveTool, CuaTool, register_tools
from deepseek_tui.engine.ui_progress import UiProgress
from deepseek_tui.tools.registry import ToolContext, ToolError, ToolRegistry, ToolResult
from deepseek_tui.tools.task_delivery import FinishTaskTool, TaskDelivery
from tests import test_cua as fixtures

fresh_runtime_cache = fixtures.fresh_runtime_cache
installation = fixtures.installation
session = fixtures.session


@pytest.mark.asyncio
async def test_recovery_allows_observation_and_keeps_blocking_actions(session, tmp_path):
    await session.connect()
    context = ToolContext(tmp_path, metadata={"cua_turn_id": "t", "cua_call_id": "c"})
    registry = ToolRegistry(context)
    register_tools(registry, session)
    session.invalidate_observation("The user brought the app to the front.")
    try:
        for _ in range(2):
            with pytest.raises(ToolError, match="cua_observe"):
                await registry.get("cua_js").execute({"code": "click"}, context)
        result = await registry.get("cua_observe").execute({"app": "dev.fixture"}, context)
        assert result.success and result.metadata["cua_observation"]["text"]
        assert not session.outside_change
        assert (await registry.get("cua_js").execute({"code": "ok"}, context)).success
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_observing_unknown_outcome_preserves_receipt(session, tmp_path):
    await session.connect()
    await session.record_outcome("old-turn", "uncertain-click", "unknown")
    context = ToolContext(tmp_path, metadata={"cua_turn_id": "t", "cua_call_id": "c"})
    registry = ToolRegistry(context)
    register_tools(registry, session)
    try:
        result = await registry.get("cua_observe").execute({"app": "dev.fixture"}, context)
        assert result.success
        assert session.unresolved["call_id"] == "uncertain-click"
        with pytest.raises(ToolError, match="unknown outcome"):
            await registry.get("cua_js").execute({"code": "click again"}, context)
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_print_only_cannot_supply_completion_evidence(session, tmp_path):
    await session.connect()
    state = TaskDelivery(active=True)
    context = ToolContext(
        tmp_path, metadata={"task_delivery": state, "cua_turn_id": "t", "cua_call_id": "c"}
    )
    try:
        result = await CuaTool(session, session.descriptors[0]).execute({"code": "ok"}, context)
        assert result.metadata["task_evidence"] is False
        state.evidence.add("tool:unrelated-read")
        with pytest.raises(ToolError, match="observation"):
            await FinishTaskTool().execute(
                dict(
                    status="completed",
                    answer="Saved",
                    evidence=["tool:unrelated-read"],
                    remaining=[],
                ),
                context,
            )
    finally:
        await session.close()


def observed(text):
    return ToolResult(
        True,
        "arbitrary model commentary",
        metadata={
            "cua_observation": {"target": {"app": "dev.fixture"}, "text": text, "complete": True}
        },
    )


def test_focus_ids_and_filtered_prints_do_not_disguise_stall():
    progress = UiProgress()
    for i in range(12):
        progress.record_result(
            "cua_observe",
            observed(
                f"Window: Form, App: Fixture.\n{i + 1} 按钮 Save\n"
                f"The focused UI element is {i + 1} 按钮 Save"
            ),
        )
        progress.record_result(
            "cua_js",
            ToolResult(
                True, f"different filtered output {i}", metadata={"cua_runtime_content": True}
            ),
        )
    assert progress.blocked_content("cua_js")
    assert progress.blocked_content("cua_observe") is None
    progress.record_result("cua_observe", observed("Window: Form\n22 文本 Saved successfully"))
    assert progress.blocked_content("cua_js") is None


def test_returning_to_same_two_states_does_not_count_as_unlimited_progress():
    progress = UiProgress()
    for i in range(14):
        progress.record_result("cua_observe", observed(f"Window: Form\n1 文本 Tab {i % 2}"))
    assert progress.blocked_content("cua_js")


def test_unmet_expected_result_does_not_reset_on_unrelated_changes():
    progress = UiProgress()
    for i in range(10):
        result = observed(f"Window: Form\n1 文本 Loading {i}")
        result.metadata["cua_observation"]["expectations"] = [{"text": "Saved", "matched": False}]
        progress.record_result("cua_observe", result)
    assert progress.blocked_content("cua_js")
    assert progress.blocked_content("cua_observe") is None
    result = observed("Window: Form\n1 文本 Saved")
    result.metadata["cua_observation"]["expectations"] = [{"text": "Saved", "matched": True}]
    progress.record_result("cua_observe", result)
    assert progress.blocked_content("cua_js") is None


@pytest.mark.asyncio
async def test_observation_cannot_accept_code_and_matches_expected_text(session, tmp_path):
    context = ToolContext(tmp_path, metadata={"cua_turn_id": "t", "cua_call_id": "c"})
    tool = CuaObserveTool(session)
    with pytest.raises(ToolError, match="no code"):
        await tool.execute({"app": "dev.fixture", "code": "click()"}, context)
    assert session.process is None
    try:
        result = await tool.execute({"app": "dev.fixture", "expect": ["Saved", "Missing"]}, context)
        assert result.metadata["cua_observation"]["expectations"] == [
            {"text": "Saved", "matched": True},
            {"text": "Missing", "matched": False},
        ]
        assert "Not verified: Missing" in result.content
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_change_during_observation_cannot_release_guard(session, tmp_path, monkeypatch):
    context = ToolContext(tmp_path, metadata={"cua_turn_id": "t", "cua_call_id": "c"})
    request = session._request

    async def interrupted(kind, **kwargs):
        result = await request(kind, **kwargs)
        if kind == "observe":
            session.invalidate_observation("user changed the app again")
        return result

    monkeypatch.setattr(session, "_request", interrupted)
    try:
        result = await CuaObserveTool(session).execute({"app": "dev.fixture"}, context)
        assert not result.success and not result.metadata["task_evidence"]
        assert session.outside_change
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_observer_handles_existing_browser_tab(session, tmp_path):
    context = ToolContext(tmp_path, metadata={"cua_turn_id": "t", "cua_call_id": "c"})
    try:
        result = await CuaObserveTool(session).execute(
            {"browser": "chrome", "tab_id": 'tab"1', "expect": ["Saved"]}, context
        )
        assert result.success
        observation = result.metadata["cua_observation"]
        assert observation["target"] == {"browser": "chrome", "tab_id": 'tab"1'}
        assert observation["expectations"][0]["matched"]
        assert "documentation" not in observation["text"]
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_other_app_cannot_verify_previous_action(session, tmp_path):
    state = TaskDelivery(active=True)
    context = ToolContext(
        tmp_path, metadata={"task_delivery": state, "cua_turn_id": "t", "cua_call_id": "c"}
    )
    await session.connect()
    try:
        await CuaTool(session, session.descriptors[0]).execute(
            {"code": "surface:dev.original"}, context
        )
        for _ in range(2):
            result = await CuaObserveTool(session).execute({"app": "dev.other"}, context)
            state.remember_evidence("tool:other", result.metadata)
            assert not state.cua_observation_evidence
        result = await CuaObserveTool(session).execute({"app": "dev.original"}, context)
        state.remember_evidence("tool:original", result.metadata)
        assert "tool:original" in state.cua_observation_evidence
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_other_app_does_not_release_recovery_guard(session, tmp_path):
    context = ToolContext(tmp_path, metadata={"cua_turn_id": "t", "cua_call_id": "c"})
    await session.connect()
    try:
        tool = CuaTool(session, session.descriptors[0])
        await tool.execute({"code": "surface:dev.original"}, context)
        session.invalidate_observation("The original app changed")
        for _ in range(2):
            await CuaObserveTool(session).execute({"app": "dev.other"}, context)
            assert session.outside_change
            with pytest.raises(ToolError, match="cua_observe"):
                await tool.execute({"code": "click"}, context)
        await CuaObserveTool(session).execute({"app": "dev.original"}, context)
        assert not session.outside_change
    finally:
        await session.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("failed", [False, True])
async def test_new_observation_cannot_reuse_old_success(session, tmp_path, monkeypatch, failed):
    state = TaskDelivery(active=True)
    context = ToolContext(
        tmp_path, metadata={"task_delivery": state, "cua_turn_id": "t", "cua_call_id": "c"}
    )
    tool = CuaObserveTool(session)
    try:
        result = await tool.execute({"app": "dev.fixture", "expect": ["Saved"]}, context)
        state.remember_evidence("tool:old", result.metadata)
        request = session._request

        async def fail_observation(kind, **kwargs):
            payload = await request(kind, **kwargs)
            if kind == "observe" and failed:
                payload["isError"] = True
            return payload

        monkeypatch.setattr(session, "_request", fail_observation)
        result = await tool.execute({"app": "dev.fixture", "expect": ["Missing"]}, context)
        if result.success:
            state.remember_evidence("tool:new", result.metadata)
        state.evidence.add("tool:unrelated")
        assert "tool:old" not in state.cua_observation_evidence
        with pytest.raises(ToolError, match="observation|not verified"):
            await FinishTaskTool().execute(
                dict(
                    status="completed",
                    answer="Saved",
                    evidence=sorted(state.evidence),
                    remaining=[],
                ),
                context,
            )
    finally:
        await session.close()


def test_canvas_pixels_are_preserved_and_cannot_override_missing_expectation(tmp_path, monkeypatch):
    from tests.engine.test_ui_progress import screen

    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    progress = UiProgress()
    for i in range(10):
        result = observed("Window: Drawing\n1 canvas")
        result = replace(result, images=[screen(text=f"Frame {i}")])
        progress.record_result("cua_observe", result)
        assert progress.blocked_content("cua_js") is None
    for i in range(10):
        result = replace(result, images=[screen(text=f"Other {i}")])
        result.metadata["cua_observation"]["expectations"] = [{"text": "Saved", "matched": False}]
        progress.record_result("cua_observe", result)
    assert progress.blocked_content("cua_js")


@pytest.mark.asyncio
async def test_completion_discloses_incomplete_evidence(tmp_path):
    observation = {"complete": False}
    state = TaskDelivery(
        active=True,
        cua_used=True,
        evidence={"tool:seen"},
        cua_observation_evidence={"tool:seen": observation},
    )
    context = ToolContext(tmp_path, metadata={"task_delivery": state})
    args = dict(
        status="completed",
        answer="One visible row",
        evidence=["tool:seen"],
        remaining=[],
        verification=[{"claim": "One visible row", "evidence": ["tool:seen"], "limitations": []}],
    )
    with pytest.raises(ToolError, match="incomplete observation"):
        await FinishTaskTool().execute(args, context)
    args["answer"] += "; total not verified"
    args["verification"][0]["limitations"] = ["total not verified"]
    assert (await FinishTaskTool().execute(args, context)).success


@pytest.mark.asyncio
async def test_engine_delivers_only_after_observation(session, tmp_path):
    from unittest.mock import AsyncMock

    from deepseek_tui.config.models import Config, FeatureConfig
    from deepseek_tui.engine.handle import EngineHandle
    from deepseek_tui.engine.orchestrator import Engine
    from deepseek_tui.protocol.messages import Message
    from deepseek_tui.protocol.responses import ToolCall
    from tests.engine.test_browser_primary_loop import ScriptedClient

    client = ScriptedClient(
        [
            ToolCall(id="act", name="cua_js", arguments={"code": "surface:dev.fixture"}),
            ToolCall(
                id="observe",
                name="cua_observe",
                arguments={"app": "dev.fixture", "expect": ["Saved"]},
            ),
            ToolCall(
                id="finish",
                name="finish_task",
                arguments=dict(
                    status="completed",
                    answer="Saved",
                    evidence=["tool:observe"],
                    remaining=[],
                    verification=[
                        {"claim": "Saved", "evidence": ["tool:observe"], "limitations": []}
                    ],
                ),
            ),
        ]
    )
    engine = await Engine.create(
        handle=EngineHandle(),
        client=client,
        working_directory=tmp_path,
        config=Config(
            features=FeatureConfig(tasks=False, subagents=False, mcp=False, automations=False)
        ),
        start_mcp=False,
    )
    await session.connect()
    register_tools(engine.tool_registry, session)
    engine.tool_context.metadata["cua_turn_id"] = "test-turn"
    engine._handle_approval_flow = AsyncMock(return_value=False)
    try:
        result = await engine._run_conversation(
            [Message.user("Save the document")], "test", "sys", None
        )
        assert result.task_outcome["status"] == "completed"
        assert result.task_outcome["evidence"] == ["tool:observe"]
        state = engine.tool_context.metadata["task_delivery"]
        assert "tool:act" not in state.evidence
    finally:
        await session.close()
        await engine.shutdown_session()
