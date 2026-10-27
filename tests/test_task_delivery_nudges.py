"""An open UI task's announce-only stops each get one round to take the announced step."""

from unittest.mock import AsyncMock

from deepseek_tui.client.base import LLMClient


class NoSecondaryRequests(LLMClient):
    async def stream_chat_completion(self, request):
        raise AssertionError("Only the primary model should be called")
        yield


async def test_each_stop_after_acting_gets_its_own_continue_nudge(tmp_path):
    from deepseek_tui.config.models import Config, FeatureConfig
    from deepseek_tui.engine.handle import EngineHandle
    from deepseek_tui.engine.orchestrator import Engine
    from deepseek_tui.engine.turn import TurnResult
    from deepseek_tui.protocol.messages import Message
    from deepseek_tui.protocol.responses import ToolCall

    engine = await Engine.create(
        handle=EngineHandle(), client=NoSecondaryRequests(), working_directory=tmp_path,
        config=Config(features=FeatureConfig(
            tasks=False, subagents=False, mcp=False, automations=False)), start_mcp=False)
    engine._handle_subagent_turn_handoff = AsyncMock(return_value=False)
    engine._handle_shell_process_turn_handoff = AsyncMock(return_value=False)

    def act(call_id):
        return TurnResult(assistant_message=None, tool_calls=[
            ToolCall(id=call_id, name="read_file", arguments={"path": "note.txt"})])

    # Observed with deepseek: announce a step in one round, take it in the next.
    script = iter([
        act("edit"),
        TurnResult(assistant_message=Message.assistant("An extra blank line appeared; checking.")),
        act("check"),
        TurnResult(assistant_message=Message.assistant("Both lines are right. Saving now.")),
        act("save"),
    ])
    rounds = []

    async def primary(request, *args, **kwargs):
        rounds.append(sorted((t.get("function") or t)["name"] for t in kwargs["tools"]))
        return next(script, TurnResult(assistant_message=Message.assistant("Stopped.")))

    executed = []

    async def execute(tool_calls, model):
        engine.tool_context.metadata["task_delivery"].active = True
        executed.extend(call.id for call in tool_calls)
        return [Message.tool_result(call.id, "ok") for call in tool_calls]

    engine.turn_loop.run = primary
    engine._execute_tool_calls = execute
    try:
        await engine._run_conversation([Message.user("edit and save note.txt")], "test", "sys",
                                       None)
        assert executed[:3] == ["edit", "check", "save"]
        # The round that saves still offers the working tools, not finalization only.
        assert "read_file" in rounds[4]
    finally:
        await engine.shutdown_session()
