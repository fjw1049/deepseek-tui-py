from __future__ import annotations

from typing import Any

import pytest

from deepseek_tui.memory.native.agent_loop import run_memory_subagent_loop
from deepseek_tui.protocol.responses import StreamTextDelta, StreamToolCallComplete, ToolCall
from deepseek_tui.tools.context import ToolContext
from deepseek_tui.tools.file_tools import WriteFileTool
from deepseek_tui.tools.registry import ToolRegistry


class _ToolLoopClient:
    def __init__(self) -> None:
        self.requests: list[Any] = []

    async def stream_with_retry(self, request):  # noqa: ANN001
        self.requests.append(request)
        if len(self.requests) == 1:
            yield StreamToolCallComplete(
                tool_call=ToolCall(
                    id="call_1",
                    name="write_file",
                    arguments={"path": "scene.md", "content": "# Scene\n"},
                )
            )
            return
        assert request.messages[-1].role.value == "tool"
        assert request.messages[-1].content[0].content == "ok"
        yield StreamTextDelta(text="done")


@pytest.mark.asyncio
async def test_memory_subagent_loop_executes_tool_and_continues(tmp_path) -> None:
    registry = ToolRegistry()
    registry.register(WriteFileTool())
    client = _ToolLoopClient()

    result = await run_memory_subagent_loop(
        client,  # type: ignore[arg-type]
        model="fake-model",
        system_prompt="system",
        user_prompt="user",
        registry=registry,
        context=ToolContext(working_directory=tmp_path),
    )

    assert result.final_text == "done"
    assert result.steps == 2
    assert result.tool_calls == 1
    assert result.errors == []
    assert (tmp_path / "scene.md").read_text(encoding="utf-8") == "# Scene\n"


class _EscapingClient:
    def __init__(self) -> None:
        self.requests: list[Any] = []

    async def stream_with_retry(self, request):  # noqa: ANN001
        self.requests.append(request)
        if len(self.requests) == 1:
            yield StreamToolCallComplete(
                tool_call=ToolCall(
                    id="call_1",
                    name="write_file",
                    arguments={"path": "../escape.md", "content": "bad"},
                )
            )
            return
        assert request.messages[-1].role.value == "tool"
        assert request.messages[-1].content[0].is_error
        yield StreamTextDelta(text="saw error")


@pytest.mark.asyncio
async def test_memory_subagent_loop_returns_tool_errors_to_model(tmp_path) -> None:
    registry = ToolRegistry()
    registry.register(WriteFileTool())
    client = _EscapingClient()

    result = await run_memory_subagent_loop(
        client,  # type: ignore[arg-type]
        model="fake-model",
        system_prompt="system",
        user_prompt="user",
        registry=registry,
        context=ToolContext(working_directory=tmp_path),
    )

    assert result.final_text == "saw error"
    assert result.errors
    assert not (tmp_path.parent / "escape.md").exists()
