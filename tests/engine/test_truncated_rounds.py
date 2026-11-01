"""A round cut off at the output cap must not pass as a finished one."""

from deepseek_tui.config.models import Config, FeatureConfig
from deepseek_tui.engine.events import ToolResultEvent
from deepseek_tui.engine.handle import EngineHandle
from deepseek_tui.engine.orchestrator import Engine
from deepseek_tui.engine.turn import TurnOutcomeStatus
from deepseek_tui.protocol.messages import Message
from deepseek_tui.protocol.responses import (
    StreamDone,
    StreamTextDelta,
    StreamToolCallComplete,
    ToolCall,
)
from tests.engine.test_browser_primary_loop import ScriptedClient


class Cut:
    """A reply that hits the output cap."""

    def __init__(self, reply):
        self.reply = reply


class CappingClient(ScriptedClient):
    async def stream_chat_completion(self, request):
        self.requests.append(request)
        reply = next(self.replies)
        cut = isinstance(reply, Cut)
        reply = reply.reply if cut else reply
        if isinstance(reply, ToolCall):
            yield StreamToolCallComplete(tool_call=reply)
        else:
            yield StreamTextDelta(text=reply)
        yield StreamDone(truncated=cut)


async def engine_for(tmp_path, replies):
    client = CappingClient(replies)
    engine = await Engine.create(
        handle=EngineHandle(), client=client, working_directory=tmp_path,
        config=Config(features=FeatureConfig(
            tasks=False, subagents=False, mcp=False, automations=False)),
        start_mcp=False,
    )
    engine.reply_locale = "en"
    return engine, client


def write(path, call_id="w"):
    return ToolCall(id=call_id, name="write_file", arguments={"path": path, "content": "x"})


async def test_cut_off_tool_call_does_not_run_and_the_round_is_redone_smaller(tmp_path):
    engine, client = await engine_for(tmp_path, [
        Cut(write("big.txt", "cut")), write("small.txt"), "Wrote it in parts.",
    ])
    engine._handle_approval_flow = _allow
    try:
        result = await engine._run_conversation([Message.user("Write")], "test", "sys", None)
        assert not (tmp_path / "big.txt").exists()
        assert (tmp_path / "small.txt").exists()
        assert "cut off at the output cap" in str(client.requests[1].messages[-1].content)
        assert result.outcome is TurnOutcomeStatus.SUCCESS
        assert result.assistant_message.text_content() == "Wrote it in parts."
        events = engine.handle.drain_events()
        assert any(isinstance(e, ToolResultEvent) and e.tool_call_id == "cut" and not e.success
                   for e in events)
    finally:
        await engine.shutdown_session()


async def test_cut_off_text_is_not_taken_as_the_final_answer(tmp_path):
    engine, client = await engine_for(tmp_path, [Cut("The report begins"), "Short report."])
    try:
        result = await engine._run_conversation([Message.user("Report")], "test", "sys", None)
        assert len(client.requests) == 2
        assert result.assistant_message.text_content() == "Short report."
        sent = [m.text_content() for m in client.requests[1].messages]
        assert "The report begins" not in sent  # the fragment never enters history
    finally:
        await engine.shutdown_session()


async def test_repeated_cut_off_ends_failed_and_keeps_what_was_written(tmp_path):
    engine, client = await engine_for(tmp_path, [Cut("Part one"), Cut("Part one again")])
    try:
        result = await engine._run_conversation([Message.user("Report")], "test", "sys", None)
        assert len(client.requests) == 2
        assert result.outcome is TurnOutcomeStatus.FAILED
        assert result.assistant_message.text_content() == "Part one again"
        assert result.task_outcome["status"] == "partial"
        assert "output cap" in result.completion_note
    finally:
        await engine.shutdown_session()


async def test_an_earlier_cut_off_does_not_count_against_a_later_one(tmp_path):
    engine, client = await engine_for(tmp_path, [
        Cut("a"), write("one.txt"), Cut("b"), "Done.",
    ])
    engine._handle_approval_flow = _allow
    try:
        result = await engine._run_conversation([Message.user("Work")], "test", "sys", None)
        assert result.outcome is TurnOutcomeStatus.SUCCESS
        assert result.assistant_message.text_content() == "Done."
    finally:
        await engine.shutdown_session()


async def _allow(*args, **kwargs):
    return False
