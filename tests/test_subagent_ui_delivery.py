"""UI checks also apply to the independent child execution loop."""

import pytest

from deepseek_tui.protocol.responses import StreamDone, StreamTextDelta, StreamToolCallComplete, ToolCall
from deepseek_tui.tools.subagent.types import SubAgentStatusKind
from tests.engine.test_ui_progress import RepeatingScreen
from tests.test_subagent_tool_failure_streak import _run


def call(name, call_id, **arguments):
    return [StreamToolCallComplete(tool_call=ToolCall(id=call_id, name=name, arguments=arguments)),
            StreamDone(usage=None)]


REPORT = [StreamTextDelta(text="### SUMMARY\nChecked 1 desktop window."), StreamDone(usage=None)]


@pytest.fixture
def desktop(monkeypatch, tmp_path):
    from deepseek_tui.tools import registry

    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    build = registry.build_subagent_registry
    tool = RepeatingScreen()

    def with_desktop(*args, **kwargs):
        result = build(*args, **kwargs)
        result.register(tool)
        return result

    monkeypatch.setattr(registry, "build_subagent_registry", with_desktop)
    return tool


async def test_child_requires_delivery_and_pauses_a_dead_loop(tmp_path, desktop):
    clients = []
    scripts = [call("cua_js", f"look{i}", code=f"observe {i}") for i in range(10)]
    scripts += [
        REPORT,  # Summary alone cannot bypass the UI contract.
        call("finish_task", "invalid", status="completed", answer="Done.", evidence=[], remaining=[]),
        call("finish_task", "finished", status="completed", answer="Window observed.",
             evidence=["tool:look8"], remaining=[]),
        REPORT,
    ]
    snap = await _run(scripts, tmp_path, clients)
    assert snap.status.kind == SubAgentStatusKind.COMPLETED
    assert desktop.calls == 9  # the first capture, then STALL_STREAK repeats; look9 is refused
    contents = [str(getattr(b, "content", "")) for r in clients[0].requests
                for m in r.messages for b in m.content]
    assert any("may indicate stalled progress" in text for text in contents)
    assert any("Not executed: Further CUA code is paused" in text for text in contents)
    assert any("Completed requires evidence" in text for text in contents)
    assert '"status": "completed"' in snap.result
    assert "tool:look8" in snap.result
    assert clients[0].calls == len(scripts)


async def test_child_out_of_budget_delivers_unverified_partial(tmp_path, monkeypatch, desktop):
    monkeypatch.setattr("deepseek_tui.tools.subagent.loop.DEFAULT_MAX_STEPS", 3)
    snap = await _run([call("cua_js", "look", code="observe"), REPORT], tmp_path, [])
    assert snap.status.kind == SubAgentStatusKind.COMPLETED
    assert snap.max_steps_reached
    assert snap.task_outcome["status"] == "partial"
    assert snap.task_outcome["evidence"] == []
    assert "Checked 1 desktop window." in snap.result  # what the child wrote still reaches the parent


async def test_child_reports_remaining_work_from_partial_delivery(tmp_path, desktop):
    snap = await _run([
        call("cua_js", "look", code="observe"),
        call("finish_task", "partial", status="partial", answer="Waiting for permission.",
             evidence=["tool:look"], remaining=["User must grant access"]),
        REPORT,
    ], tmp_path, [])
    assert snap.status.kind == SubAgentStatusKind.COMPLETED
    assert '"status": "partial"' in snap.result
    assert "User must grant access" in snap.result


async def test_structured_child_cannot_bypass_delivery_and_preserves_partial_status(tmp_path, desktop):
    import asyncio
    from dataclasses import replace

    from deepseek_tui.tools.subagent.completion import build_completion_payload
    from deepseek_tui.tools.subagent.loop import run_subagent_loop
    from deepseek_tui.tools.subagent.store import agent_record, restore_agent
    from tests.test_subagent_audit_fixes import loop_fixture
    from tests.test_subagent_tool_failure_streak import _ScriptedClient

    manager, agent, runtime = await loop_fixture(tmp_path)
    agent.output_schema = {"type": "object", "properties": {"count": {"type": "integer"}},
                           "required": ["count"]}
    runtime.client = _ScriptedClient([
        call("cua_js", "look", code="observe"),
        call("structured_output", "early", count=0),
        call("finish_task", "blocked", status="blocked", answer="Permission needed.",
             evidence=[], remaining=["Grant access"]),
        call("structured_output", "final", count=0),
    ])
    try:
        result = await run_subagent_loop(agent, runtime, asyncio.Event())
        assert runtime.client.calls == 4
        assert result.structured == {"count": 0}
        assert result.task_outcome["status"] == "blocked"
        snap = replace(agent.snapshot(), result=result.text, structured=result.structured,
                       structured_received=True, task_outcome=result.task_outcome)
        payload = build_completion_payload(snap)
        assert payload.startswith("UI task blocked:")
        assert '"task_outcome"' in payload and "Grant access" in payload
        agent.task_outcome = result.task_outcome
        restored = restore_agent(agent_record(agent), tmp_path, "deepseek-chat")
        assert restored.task_outcome == result.task_outcome
    finally:
        await manager.shutdown()
