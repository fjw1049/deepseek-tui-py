from __future__ import annotations

import asyncio
from typing import Any

import pytest

from deepseek_tui.config.models import Config, FeatureConfig
from deepseek_tui.engine.orchestrator import Engine
from deepseek_tui.engine.handle import EngineHandle, GoalFollowUpOp
from deepseek_tui.protocol.responses import StreamDone, StreamTextDelta, Usage


class _OneShotClient:
    def __init__(self) -> None:
        self.requests: list[Any] = []

    async def stream_with_retry(self, request):  # noqa: ANN001
        self.requests.append(request)
        yield StreamTextDelta(text="continued")
        yield StreamDone(usage=Usage(input_tokens=10, output_tokens=5))


@pytest.mark.asyncio
async def test_hidden_goal_follow_up_does_not_persist_hidden_user_message(tmp_path) -> None:
    handle = EngineHandle()
    client = _OneShotClient()
    engine = await Engine.create(
        handle=handle,
        client=client,  # type: ignore[arg-type]
        config=Config(features=FeatureConfig(mcp=False, tasks=False, subagents=False)),
        working_directory=tmp_path,
    )
    try:
        goal = engine.goal_controller.create("continue without polluting history")
        task = asyncio.create_task(engine.run())
        await handle.send_op(GoalFollowUpOp(goal_id=goal.goal_id, content="hidden goal prompt"))

        events = []
        async for event in handle.events():
            events.append(event)
            if event.__class__.__name__ == "TurnCompleteEvent":
                break

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert client.requests
        assert client.requests[0].messages[-1].content[0].text == "hidden goal prompt"
        persisted_user_texts = [
            block.text
            for message in engine.session_messages
            if message.role.value == "user"
            for block in message.content
            if hasattr(block, "text")
        ]
        assert "hidden goal prompt" not in persisted_user_texts
    finally:
        await engine.shutdown_session()
