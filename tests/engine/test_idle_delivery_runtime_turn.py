"""Idle deliveries go through the host's turn starter when it has one.

Under the Workbench runtime the engine must not queue its own hidden turn (it
would run unmonitored). When the runtime cannot open the turn because one is
already running, the payload goes back to the queue for that turn's handoff.
"""

from __future__ import annotations

from deepseek_tui.engine.handle import (
    PROCESS_BACKGROUND_DONE_KIND,
    SUBAGENT_BACKGROUND_DONE_KIND,
)
from deepseek_tui.tools.subagent import SubAgentAssignment, SubAgentCompletion, SubAgentType
from deepseek_tui.tools.subagent.agent import SubAgent
from deepseek_tui.tools.subagent.types import SubAgentStatus


def _completed_child(engine, agent_id: str) -> None:  # noqa: ANN001
    mgr = engine.tool_context.subagent_manager
    agent = SubAgent(
        agent_type=SubAgentType.EXPLORE,
        prompt="hi",
        assignment=SubAgentAssignment(objective="hi"),
        model="deepseek-chat",
        nickname=None,
        allowed_tools=None,
        session_boot_id=mgr.session_boot_id,
        workspace=engine.tool_context.working_directory,
    )
    agent.id = agent_id
    agent.status = SubAgentStatus.completed()
    agent.result = "### SUMMARY\nfound 3 files in src/"
    mgr._agents[agent_id] = agent  # noqa: SLF001


def _starter(result: bool, calls: list[tuple[str, str]]):  # noqa: ANN202
    async def start(content: str, internal_kind: str) -> bool:
        calls.append((internal_kind, content))
        return result

    return start


async def test_runtime_starts_the_turn_instead_of_the_engine(engine_ctx) -> None:  # noqa: ANN001
    engine, handle = engine_ctx
    _completed_child(engine, "agent_idle")
    engine._enqueue_subagent_completion(  # noqa: SLF001
        SubAgentCompletion(agent_id="agent_idle", payload="payload-idle")
    )
    calls: list[tuple[str, str]] = []
    engine.tool_context.metadata["start_internal_turn"] = _starter(True, calls)

    await engine._deliver_subagent_completions_when_idle()  # noqa: SLF001

    assert [kind for kind, _ in calls] == [SUBAGENT_BACKGROUND_DONE_KIND]
    assert "payload-idle" in calls[0][1]
    assert handle._op_queue.empty()  # noqa: SLF001


async def test_busy_runtime_leaves_subagent_results_for_the_handoff(engine_ctx) -> None:  # noqa: ANN001
    engine, _handle = engine_ctx
    _completed_child(engine, "agent_busy")
    engine._enqueue_subagent_completion(  # noqa: SLF001
        SubAgentCompletion(agent_id="agent_busy", payload="payload-busy")
    )
    calls: list[tuple[str, str]] = []
    engine.tool_context.metadata["start_internal_turn"] = _starter(False, calls)

    await engine._deliver_subagent_completions_when_idle()  # noqa: SLF001

    assert len(calls) == 1
    messages: list = []
    assert await engine._handle_subagent_turn_handoff(messages) is True  # noqa: SLF001
    assert any("payload-busy" in m.text_content() for m in messages)


async def test_busy_runtime_leaves_shell_results_for_the_handoff(engine_ctx) -> None:  # noqa: ANN001
    engine, _handle = engine_ctx
    engine._enqueue_shell_process_completion(  # noqa: SLF001
        {"process_id": "p1", "command": "echo x", "returncode": 0, "output": "x"}
    )
    calls: list[tuple[str, str]] = []
    engine.tool_context.metadata["start_internal_turn"] = _starter(False, calls)

    await engine._deliver_process_completions_when_idle()  # noqa: SLF001

    assert [kind for kind, _ in calls] == [PROCESS_BACKGROUND_DONE_KIND]
    assert [item["process_id"] for item in engine._drain_process_completions()] == ["p1"]  # noqa: SLF001
