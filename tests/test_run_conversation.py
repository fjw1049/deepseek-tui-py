"""Display history retains messages independently of execution checkpoints."""

import asyncio
from types import SimpleNamespace

import pytest

from deepseek_tui.engine.dispatch import _collect_turn_events
from deepseek_tui.engine.events import (
    AgentRoundCompleteEvent,
    TextDeltaEvent,
    ToolResultEvent,
    TurnCancelledEvent,
    TurnCompleteEvent,
)
from deepseek_tui.protocol.messages import Message
from deepseek_tui.protocol.responses import ToolCall
from deepseek_tui.tools.run_conversation import RunConversation, load_run_conversation


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path))


def test_stream_finalize_reload_and_resume_keep_ids_and_full_tool_output(tmp_path):
    history = RunConversation("subagent", "agent_1", "Original assignment", tmp_path)
    history.delta("Inspect ")
    history.delta("files")
    live_id = history.data["liveId"]
    history.settle("Inspect files")
    for call in ("a", "b"):
        history.tool(call, "read_file", {"path": call})
    output = "full output" * 1000
    history.tool("a", "read_file", {"path": "a"}, output, True)
    history.tool("b", "read_file", {"path": "b"}, "failed", False)
    history.delta("Result")
    history.settle("Result", final=True)
    history.finish("completed")
    loaded = load_run_conversation("subagent", "agent_1")
    assert loaded["blocks"][1]["id"] == live_id
    assert loaded["blocks"][2]["detail"] == output
    assert loaded["blocks"][3]["status"] == "error"
    assert loaded["liveId"] is None
    ids = [b["id"] for b in loaded["blocks"]]
    resumed = RunConversation("subagent", "agent_1", "Original assignment", tmp_path)
    resumed.user("Follow-up")
    resumed.tool("a", "read_file", {"path": "new"})
    resumed.finish("cancelled")
    assert [b["id"] for b in resumed.blocks[: len(ids)]] == ids
    assert len({b["id"] for b in resumed.blocks}) == len(resumed.blocks)
    assert resumed.blocks[-1]["status"] == "error"


class Handle:
    def __init__(self, events):
        self.items = events

    async def events(self):
        for event in self.items:
            yield event


async def test_real_task_collector_preserves_order_and_does_not_duplicate_final(tmp_path):
    call = ToolCall(id="call_1", name="read_file", arguments={"path": "example.py"})
    events = [
        TextDeltaEvent("Inspect file"),
        AgentRoundCompleteEvent(1, (call,), "Inspect file"),
        ToolResultEvent("call_1", "read_file", "content" * 2000, True),
        TextDeltaEvent("Answer"),
        AgentRoundCompleteEvent(2, (), "Answer"),
        TurnCompleteEvent(assistant_message=Message.assistant("Answer")),
    ]
    task = SimpleNamespace(id="task_1", prompt="Read example.py", workspace=tmp_path)
    await _collect_turn_events(Handle(events), asyncio.Event(), task=task)
    data = load_run_conversation("task", "task_1")
    assert [b["kind"] for b in data["blocks"]] == ["user", "assistant", "tool", "assistant"]
    assert data["blocks"][2]["meta"]["tool_input"] == {"path": "example.py"}
    assert data["blocks"][2]["detail"] == "content" * 2000
    assert data["blocks"][-1]["agentSegment"] == "final_answer"
    assert data["status"] == "completed"


async def test_cancel_event_is_not_recorded_as_completed(tmp_path):
    task = SimpleNamespace(id="task_1", prompt="Work", workspace=tmp_path)
    await _collect_turn_events(Handle([TurnCancelledEvent("stop")]), asyncio.Event(), task=task)
    assert load_run_conversation("task", "task_1")["status"] == "cancelled"


@pytest.mark.parametrize("owner_id", ["../secret", "x/y", ""])
def test_invalid_owner_cannot_escape_history_directory(owner_id):
    with pytest.raises(ValueError):
        load_run_conversation("task", owner_id)


def test_response_uses_main_tool_kinds_and_stops_interrupted_tools(tmp_path):
    from deepseek_tui.server.threads.items import run_conversation_response

    history = RunConversation("subagent", "agent_1", "Work", tmp_path)
    history.tool("a", "write_file", {"path": "file.py"})
    history.tool("b", "exec_shell", {"command": "pytest"})
    response = run_conversation_response(history.data, "interrupted")["conversation"]
    assert response["blocks"][1]["toolKind"] == "file_change"
    assert response["blocks"][2]["toolKind"] == "command_execution"
    assert all(b.get("status") != "running" for b in response["blocks"])
    assert history.blocks[1]["status"] == "running"  # Reading never mutates live state.


def test_display_write_failure_does_not_fail_execution(tmp_path, monkeypatch):
    def fail(*args):
        raise OSError("disk unavailable")

    monkeypatch.setattr("deepseek_tui.tools.run_conversation.write_json_atomic", fail)
    history = RunConversation("task", "task_1", "Work", tmp_path)
    history.delta("Answer")
    history.settle("Answer", final=True)
    history.finish("completed")
    assert history.blocks[-1]["text"] == "Answer"
