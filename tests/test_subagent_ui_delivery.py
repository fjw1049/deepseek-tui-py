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


async def test_child_without_browser_returns_web_ui_work_to_parent(tmp_path, desktop):
    clients = []
    await _run([REPORT], tmp_path, clients)
    request = clients[0].requests[0]
    assert not any(t["function"]["name"] == "browser_use" for t in request.tools)
    assert any(t["function"]["name"] == "cua_js" for t in request.tools)
    assert "return that step to the parent" in request.system_prompt
    assert "Do not substitute Chrome CUA" in request.system_prompt


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


async def test_child_ends_on_its_report_and_pauses_a_dead_loop(tmp_path, desktop):
    clients = []
    scripts = [call("cua_js", f"look{i}", code=f"observe {i}") for i in range(10)] + [REPORT]
    snap = await _run(scripts, tmp_path, clients)
    assert snap.status.kind == SubAgentStatusKind.COMPLETED
    assert desktop.calls == 9  # the first capture, then STALL_STREAK repeats; look9 is refused
    contents = [str(getattr(b, "content", "")) for r in clients[0].requests
                for m in r.messages for b in m.content]
    assert any("may indicate stalled progress" in text for text in contents)
    assert any("Not executed: Further CUA code is paused" in text for text in contents)
    assert clients[0].calls == len(scripts)


async def test_child_out_of_budget_reports_it_as_a_fact(tmp_path, monkeypatch, desktop):
    monkeypatch.setattr("deepseek_tui.tools.subagent.loop.DEFAULT_MAX_STEPS", 3)
    scripts = [call("cua_js", f"look{i}", code=f"observe {i}") for i in range(3)] + [REPORT]
    snap = await _run(scripts, tmp_path, [])
    assert snap.status.kind == SubAgentStatusKind.COMPLETED
    assert snap.max_steps_reached
    assert snap.task_outcome["status"] == "partial"
    assert snap.result.startswith("---")  # no stray blank lines when the child wrote nothing
    assert "Step budget exhausted" in snap.result


async def test_parent_reads_a_childs_unresolved_failure(tmp_path, monkeypatch, desktop):
    snap = await _run([
        call("exec_shell", "bad", command="false"),
        REPORT,
    ], tmp_path, [])
    assert snap.status.kind == SubAgentStatusKind.COMPLETED
    assert snap.task_outcome["status"] == "partial"
    assert "exec_shell false" in snap.result


async def test_structured_child_keeps_partial_status_through_store_and_payload(tmp_path, desktop):
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
        call("exec_shell", "bad", command="false"),
        call("structured_output", "final", count=0),
    ])
    try:
        result = await run_subagent_loop(agent, runtime, asyncio.Event())
        assert result.structured == {"count": 0}
        assert result.task_outcome["status"] == "partial"
        snap = replace(agent.snapshot(), result=result.text, structured=result.structured,
                       structured_received=True, task_outcome=result.task_outcome)
        payload = build_completion_payload(snap)
        assert payload.startswith("Partial: exec_shell false")
        assert '"task_outcome"' in payload
        agent.task_outcome = result.task_outcome
        restored = restore_agent(agent_record(agent), tmp_path, "deepseek-chat")
        assert restored.task_outcome == result.task_outcome
    finally:
        await manager.shutdown()


class _ActingDesktop(RepeatingScreen):
    """A desktop REPL whose trace shows one click for each code call."""

    async def execute(self, input_data, context):
        from deepseek_tui.tools.registry import ToolResult

        self.calls += 1
        return ToolResult(True, "clicked", metadata={
            "cua_trace": {"ready": True, "actions": [{"action": "click", "ok": True}]}})


async def test_a_childs_desktop_steps_need_no_closing_summary(tmp_path, monkeypatch):
    from deepseek_tui.tools import registry

    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    build = registry.build_subagent_registry

    def with_desktop(*args, **kwargs):
        result = build(*args, **kwargs)
        result.register(_ActingDesktop())
        return result

    monkeypatch.setattr(registry, "build_subagent_registry", with_desktop)
    snap = await _run([call("cua_js", "act", code="await app.click(3)"), REPORT], tmp_path, [])
    assert snap.status.kind == SubAgentStatusKind.COMPLETED
    assert "wrapped up" not in snap.result
    assert snap.task_outcome["status"] != "partial"
